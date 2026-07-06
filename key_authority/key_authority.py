import os
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import sqlite3, hmac, hashlib, secrets, time, threading
from contextlib import contextmanager
from datetime import datetime, timedelta

PEPPER_FILE = os.getenv("PEPPER_FILE", "pepper.txt")
DB_FILE = os.getenv("DB_FILE", "keys.db")
MASTER_ADMIN_KEY = os.getenv("MASTER_ADMIN_KEY", "sov_master_admin_do_not_share")
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX_REQUESTS = 100

app = FastAPI(title="Sovereign Key Authority", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health_check():
    return {"status": "ok", "version": "2.0"}

def load_or_create_pepper():
    if not os.path.exists(PEPPER_FILE):
        with open(PEPPER_FILE, "wb") as f:
            f.write(secrets.token_bytes(32))
    with open(PEPPER_FILE, "rb") as f:
        return f.read()

PEPPER = load_or_create_pepper()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try: yield conn
    finally: conn.close()

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                prefix TEXT NOT NULL UNIQUE,
                hash TEXT NOT NULL,
                environment TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                expires_at TEXT,
                created_by TEXT,
                requests_count INTEGER DEFAULT 0,
                last_used TEXT,
                label TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_prefix ON api_keys(prefix);
            CREATE INDEX IF NOT EXISTS idx_status ON api_keys(status);
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event TEXT NOT NULL,
                key_id TEXT,
                details TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
        """)
        conn.commit()
        # Migration: add columns that may be missing from older DBs
        try:
            conn.execute("ALTER TABLE api_keys ADD COLUMN label TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists

def generate_prefix(length=12): return secrets.token_hex(length//2)
def generate_secret(length=32): return secrets.token_hex(length//2)
def hash_secret(secret: str, pepper: bytes, version: int = 1) -> str:
    return f"{version}:{hmac.new(pepper, secret.encode(), hashlib.sha256).hexdigest()}"
def format_key(environment: str, prefix: str, secret: str) -> str:
    return f"sov_{environment}_{prefix}_{secret}"

rate_limits = {}
rate_lock = threading.Lock()
def check_rate_limit(key_id: str) -> bool:
    now = time.time()
    with rate_lock:
        if key_id in rate_limits:
            start, count = rate_limits[key_id]
            if now - start > RATE_LIMIT_WINDOW:
                rate_limits[key_id] = (now, 1); return True
            elif count < RATE_LIMIT_MAX_REQUESTS:
                rate_limits[key_id] = (start, count+1); return True
            else: return False
        else:
            rate_limits[key_id] = (now, 1); return True

def require_admin(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or auth != f"Bearer {MASTER_ADMIN_KEY}":
        raise HTTPException(401, "Invalid admin credentials")

class KeyCreateRequest(BaseModel):
    environment: str = "test"
    duration_days: int = 30
    label: Optional[str] = None

class KeyResponse(BaseModel):
    full_key: str
    key_id: str
    prefix: str
    environment: str
    expires_at: Optional[str]

@app.on_event("startup")
def startup(): init_db()

@app.post("/admin/keys", response_model=KeyResponse)
def create_key(req: KeyCreateRequest, admin=Depends(require_admin)):
    if req.environment not in ("test", "live", "int"): raise HTTPException(400, "Invalid environment")
    prefix = generate_prefix()
    secret = generate_secret()
    full_key = format_key(req.environment, prefix, secret)
    key_id = secrets.token_hex(16)
    key_hash = hash_secret(secret, PEPPER)
    expires_at = (datetime.utcnow() + timedelta(days=req.duration_days)).isoformat()
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        try:
            conn.execute("INSERT INTO api_keys (key_id, prefix, hash, environment, status, created_at, expires_at, created_by, label) VALUES (?,?,?,?,?,?,?,?,?)",
                         (key_id, prefix, key_hash, req.environment, "active", now, expires_at, "admin", req.label))
            conn.commit()
        except sqlite3.IntegrityError: raise HTTPException(409, "Prefix collision")
        conn.execute("INSERT INTO audit_log (timestamp, event, key_id, details) VALUES (?,?,?,?)",
                     (now, "key_created", key_id, f"env={req.environment}, exp={expires_at}" + (f", label={req.label}" if req.label else "")))
        conn.commit()
    return KeyResponse(full_key=full_key, key_id=key_id, prefix=prefix, environment=req.environment, expires_at=expires_at)

@app.post("/validate")
def validate_key(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "): raise HTTPException(401)
    raw_key = auth.split(" ", 1)[1]
    parts = raw_key.split("_", 3)
    if len(parts) != 4 or parts[0] != "sov": raise HTTPException(401)
    env, prefix, secret = parts[1], parts[2], parts[3]
    if len(prefix) != 12 or len(secret) != 32: raise HTTPException(401)
    with get_db() as conn:
        row = conn.execute("SELECT key_id, hash, status, expires_at FROM api_keys WHERE prefix=? AND environment=?",
                           (prefix, env)).fetchone()
        if not row: raise HTTPException(401)
        if row["status"] != "active": raise HTTPException(401)
        if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) < datetime.utcnow(): raise HTTPException(401)
        expected_hash = hash_secret(secret, PEPPER)
        if not hmac.compare_digest(expected_hash, row["hash"]): raise HTTPException(401)
        key_id = row["key_id"]
        if not check_rate_limit(key_id): raise HTTPException(429, "Rate limit exceeded")
        now = datetime.utcnow().isoformat()
        conn.execute("UPDATE api_keys SET requests_count = requests_count + 1, last_used = ? WHERE key_id = ?", (now, key_id))
        conn.commit()
        # Log validation
        conn.execute("INSERT INTO audit_log (timestamp, event, key_id, details) VALUES (?,?,?,?)",
                     (now, "key_validated", key_id, f"env={env}"))
        conn.commit()
        return {"key_id": key_id, "environment": env, "status": "active", "expires_at": row["expires_at"]}

@app.post("/admin/revoke")
async def revoke_key(request: Request, admin=Depends(require_admin)):
    data = await request.json()
    prefix = data.get("prefix")
    if not prefix: raise HTTPException(400)
    with get_db() as conn:
        row = conn.execute("SELECT key_id, status FROM api_keys WHERE prefix=?", (prefix,)).fetchone()
        if not row: raise HTTPException(404)
        if row["status"] != "active": raise HTTPException(400, f"Key is already {row['status']}")
        now = datetime.utcnow().isoformat()
        conn.execute("UPDATE api_keys SET status='revoked' WHERE prefix=?", (prefix,))
        conn.execute("INSERT INTO audit_log (timestamp, event, key_id, details) VALUES (?,?,?,?)",
                     (now, "key_revoked", row["key_id"], f"prefix={prefix}"))
        conn.commit()
    return {"status": "revoked", "prefix": prefix}

@app.get("/admin/keys", response_model=List[dict])
def list_keys(admin=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT key_id, prefix, environment, status, created_at, expires_at, requests_count, last_used, label FROM api_keys ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

@app.get("/admin/keys/stats")
def key_stats(admin=Depends(require_admin)):
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM api_keys").fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) as c FROM api_keys WHERE status='active'").fetchone()["c"]
        revoked = conn.execute("SELECT COUNT(*) as c FROM api_keys WHERE status='revoked'").fetchone()["c"]
        expired = conn.execute("SELECT COUNT(*) as c FROM api_keys WHERE status='expired'").fetchone()["c"]
        total_requests = conn.execute("SELECT SUM(requests_count) as c FROM api_keys").fetchone()["c"] or 0
        by_env = [dict(r) for r in conn.execute(
            "SELECT environment, COUNT(*) as count, SUM(requests_count) as total_requests FROM api_keys GROUP BY environment"
        ).fetchall()]
    return {
        "total_keys": total,
        "active_keys": active,
        "revoked_keys": revoked,
        "expired_keys": expired,
        "total_requests_served": total_requests,
        "by_environment": by_env
    }

@app.get("/admin/audit-log")
def audit_log(limit: int = 100, admin=Depends(require_admin)):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT timestamp, event, key_id, details FROM audit_log ORDER BY id DESC LIMIT ?", (min(limit, 500),)
        ).fetchall()
        return [dict(r) for r in rows]

@app.post("/admin/rotate-pepper")
def rotate_pepper(admin=Depends(require_admin)):
    """Rotate the pepper. WARNING: invalidates all existing keys."""
    global PEPPER
    new_pepper = secrets.token_bytes(32)
    with open(PEPPER_FILE, "wb") as f:
        f.write(new_pepper)
    PEPPER = new_pepper
    now = datetime.utcnow().isoformat()
    with get_db() as conn:
        conn.execute("INSERT INTO audit_log (timestamp, event, key_id, details) VALUES (?,?,?,?)",
                     (now, "pepper_rotated", None, "All keys invalidated"))
        conn.commit()
    return {"status": "pepper_rotated", "warning": "All existing API keys are now invalid"}