import os, httpx, json, time, uuid, logging, random, sqlite3
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
from contextlib import contextmanager
from typing import Optional
import threading

KEY_AUTHORITY_URL = os.getenv("KEY_AUTHORITY_URL", "http://127.0.0.1:8001/validate")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
ML_ADVERSARIAL_URL = os.getenv("ML_ADVERSARIAL_URL", "http://ml-adversarial:8010")
ML_EXTRACTION_URL = os.getenv("ML_EXTRACTION_URL", "http://ml-extraction:8011")
STATS_DB = os.getenv("STATS_DB", "/data/gateway_stats.db")

def load_keys(var_name):
    raw = os.getenv(var_name, "")
    return [k.strip() for k in raw.split(",") if k.strip()]

GROQ_KEYS = load_keys("GROQ_API_KEY")
GEMINI_KEYS = load_keys("GEMINI_API_KEY")
MISTRAL_KEYS = load_keys("MISTRAL_API_KEY")
DEEPSEEK_KEYS = load_keys("DEEPSEEK_API_KEY")
OPENAI_KEYS = load_keys("OPENAI_API_KEY")

app = FastAPI(title="GODMODE Sovereign AI Gateway", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gateway")
stats_lock = threading.Lock()

# ── Persistent Stats DB ──────────────────────────────────────────────
os.makedirs(os.path.dirname(STATS_DB) if os.path.dirname(STATS_DB) else "/data", exist_ok=True)

@contextmanager
def get_stats_db():
    conn = sqlite3.connect(STATS_DB)
    conn.row_factory = sqlite3.Row
    try: yield conn
    finally: conn.close()

def init_stats_db():
    with get_stats_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS request_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                key_id TEXT,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms REAL,
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_req_ts ON request_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_req_provider ON request_log(provider);
            CREATE INDEX IF NOT EXISTS idx_req_status ON request_log(status);
            CREATE TABLE IF NOT EXISTS provider_latency (
                provider TEXT PRIMARY KEY,
                avg_latency_ms REAL,
                last_checked TEXT,
                status TEXT DEFAULT 'unknown'
            );
        """)
        conn.commit()

init_stats_db()

def log_request(key_id, provider, model, status, latency_ms, prompt_tokens=0, completion_tokens=0, error=""):
    with stats_lock:
        try:
            with get_stats_db() as conn:
                conn.execute(
                    "INSERT INTO request_log (timestamp, key_id, provider, model, status, latency_ms, prompt_tokens, completion_tokens, error_message) VALUES (?,?,?,?,?,?,?,?,?)",
                    (datetime.utcnow().isoformat(), key_id, provider, model, status, latency_ms, prompt_tokens, completion_tokens, error[:500])
                )
                conn.commit()
            # Update provider latency
            with get_stats_db() as conn:
                existing = conn.execute("SELECT avg_latency_ms FROM provider_latency WHERE provider=?", (provider,)).fetchone()
                if existing and existing["avg_latency_ms"]:
                    new_avg = (existing["avg_latency_ms"] * 0.9) + (latency_ms * 0.1)
                else:
                    new_avg = latency_ms
                conn.execute(
                    "INSERT OR REPLACE INTO provider_latency (provider, avg_latency_ms, last_checked, status) VALUES (?,?,?,?)",
                    (provider, round(new_avg, 1), datetime.utcnow().isoformat(), "ok" if status == "success" else "error")
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to log request: {e}")

# ── Provider Routing ─────────────────────────────────────────────────

async def try_provider_call(api_url, payload, headers_list):
    last_exception = None
    for headers in headers_list:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(api_url, json=payload, headers=headers, timeout=120)
                resp.raise_for_status()
                return resp.json(), None
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 503):
                logger.warning(f"Rate limited on {api_url}, trying next key...")
                last_exception = e
                continue
            else:
                raise HTTPException(e.response.status_code, e.response.text)
        except Exception as e:
            logger.error(f"Connection error for {api_url}: {e}")
            last_exception = e
            continue
    if last_exception:
        raise HTTPException(429, "All keys exhausted for this provider")

def build_headers_list(keys, provider):
    if not keys: return []
    headers_list = []
    for key in keys:
        if provider == "groq":
            headers_list.append({"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        elif provider == "gemini":
            headers_list.append({"Content-Type": "application/json"})
        elif provider == "mistral":
            headers_list.append({"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        elif provider == "deepseek":
            headers_list.append({"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        elif provider == "openai":
            headers_list.append({"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return headers_list

MODEL_PRICING = {
    "groq": {"input": 0.0, "output": 0.0},  # Free tier
    "gemini": {"input": 0.0, "output": 0.0},  # Free tier (flash)
    "mistral": {"input": 0.0, "output": 0.0},
    "deepseek": {"input": 0.14, "output": 0.28},  # Per 1M tokens
    "openai": {"input": 0.15, "output": 0.60},   # gpt-3.5-turbo approx
    "ollama": {"input": 0.0, "output": 0.0},
}

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    t0 = time.time()
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(401, "Missing Authorization header")

    # Validate key
    headers_for_validation = {"Authorization": auth_header}
    key_id = "anonymous"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(KEY_AUTHORITY_URL, headers=headers_for_validation)
            resp.raise_for_status()
            key_info = resp.json()
            key_id = key_info.get("key_id", "anonymous")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429: raise HTTPException(429, "Rate limit exceeded")
        else: raise HTTPException(401, "Invalid API key")
    except httpx.RequestError:
        logger.warning("Key authority unreachable — allowing request through")
    except Exception:
        logger.warning("Key validation failed — allowing request through")

    body = await request.json()
    model = body.get("model", "llama3.2:3b")
    messages = body.get("messages")
    stream_flag = body.get("stream", False)
    if not messages:
        raise HTTPException(400, "messages required")

    provider, model_name = model.split("/", 1) if "/" in model else ("ollama", model)

    try:
        # ── Ollama ──
        if provider == "ollama":
            payload = {
                "model": model_name,
                "messages": messages,
                "stream": False,
                "options": {"temperature": body.get("temperature", 0.7)}
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
                resp.raise_for_status()
                data = resp.json()
            latency = (time.time() - t0) * 1000
            pt = data.get("prompt_eval_count", 0)
            ct = data.get("eval_count", 0)
            log_request(key_id, provider, model_name, "success", latency, pt, ct)
            return JSONResponse({
                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion", "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": data["message"]["content"]}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
                "gateway_meta": {"provider": "ollama", "latency_ms": round(latency, 1)}
            })

        # ── Cloud Providers ──
        payload = {
            "model": model_name, "messages": messages,
            "temperature": body.get("temperature", 0.7),
            "max_tokens": body.get("max_tokens", 4096), "stream": False
        }

        if provider == "groq":
            api_url = "https://api.groq.com/openai/v1/chat/completions"
            headers_list = build_headers_list(GROQ_KEYS, "groq")
            if not headers_list: raise HTTPException(500, "No Groq keys configured")
            response_data, _ = await try_provider_call(api_url, payload, headers_list)

        elif provider == "gemini":
            if not GEMINI_KEYS: raise HTTPException(500, "No Gemini keys configured")
            gemini_key = random.choice(GEMINI_KEYS)
            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={gemini_key}"
            gemini_payload = {"contents": [{"parts": [{"text": msg["content"]} for msg in messages]}]}
            async with httpx.AsyncClient() as client:
                resp = await client.post(api_url, json=gemini_payload, timeout=120)
                resp.raise_for_status()
                data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            latency = (time.time() - t0) * 1000
            log_request(key_id, provider, model_name, "success", latency)
            return JSONResponse({
                "id": f"chatcmpl-{uuid.uuid4().hex[:8]}", "object": "chat.completion",
                "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "gateway_meta": {"provider": "gemini", "latency_ms": round(latency, 1)}
            })

        elif provider == "mistral":
            api_url = "https://api.mistral.ai/v1/chat/completions"
            headers_list = build_headers_list(MISTRAL_KEYS, "mistral")
            if not headers_list: raise HTTPException(500, "No Mistral keys configured")
            response_data, _ = await try_provider_call(api_url, payload, headers_list)

        elif provider == "deepseek":
            api_url = "https://api.deepseek.com/v1/chat/completions"
            headers_list = build_headers_list(DEEPSEEK_KEYS, "deepseek")
            if not headers_list: raise HTTPException(500, "No DeepSeek keys configured")
            response_data, _ = await try_provider_call(api_url, payload, headers_list)

        elif provider == "openai":
            api_url = "https://api.openai.com/v1/chat/completions"
            headers_list = build_headers_list(OPENAI_KEYS, "openai")
            if not headers_list: raise HTTPException(500, "No OpenAI keys configured")
            response_data, _ = await try_provider_call(api_url, payload, headers_list)

        else:
            raise HTTPException(400, f"Unknown provider: {provider}")

        latency = (time.time() - t0) * 1000
        usage = response_data.get("usage", {})
        log_request(key_id, provider, model_name, "success", latency,
                    usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        response_data["gateway_meta"] = {"provider": provider, "latency_ms": round(latency, 1)}
        return JSONResponse(response_data)

    except HTTPException:
        raise
    except Exception as e:
        latency = (time.time() - t0) * 1000
        log_request(key_id, provider, model_name, "error", latency, error=str(e))
        raise HTTPException(500, str(e))

# ── Enhanced Dashboard Endpoints ─────────────────────────────────────

@app.get("/dashboard/stats")
def dashboard_stats():
    with get_stats_db() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM request_log").fetchone()["c"]
        recent = [dict(r) for r in conn.execute(
            "SELECT timestamp, key_id, provider, model, status, latency_ms, prompt_tokens, completion_tokens FROM request_log ORDER BY id DESC LIMIT 50"
        ).fetchall()]
        success_count = conn.execute("SELECT COUNT(*) FROM request_log WHERE status='success'").fetchone()[0]
        error_count = conn.execute("SELECT COUNT(*) FROM request_log WHERE status='error'").fetchone()[0]
    return {
        "total_requests": total,
        "success_count": success_count,
        "error_count": error_count,
        "recent_requests": recent
    }

@app.get("/dashboard/analytics")
def dashboard_analytics(hours: int = Query(default=24, ge=1, le=720)):
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_stats_db() as conn:
        # Requests over time (hourly buckets)
        time_series = [dict(r) for r in conn.execute("""
            SELECT strftime('%Y-%m-%dT%H:00:00', timestamp) as hour,
                   COUNT(*) as count,
                   AVG(latency_ms) as avg_latency,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors
            FROM request_log
            WHERE timestamp >= ?
            GROUP BY hour ORDER BY hour
        """, (cutoff,)).fetchall()]

        # By provider
        by_provider = [dict(r) for r in conn.execute("""
            SELECT provider, COUNT(*) as count,
                   AVG(latency_ms) as avg_latency,
                   SUM(prompt_tokens) as total_prompt_tokens,
                   SUM(completion_tokens) as total_completion_tokens,
                   SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors
            FROM request_log WHERE timestamp >= ?
            GROUP BY provider ORDER BY count DESC
        """, (cutoff,)).fetchall()]

        # By model
        by_model = [dict(r) for r in conn.execute("""
            SELECT provider || '/' || model as model, COUNT(*) as count,
                   AVG(latency_ms) as avg_latency
            FROM request_log WHERE timestamp >= ?
            GROUP BY model ORDER BY count DESC LIMIT 20
        """, (cutoff,)).fetchall()]

        # By key
        by_key = [dict(r) for r in conn.execute("""
            SELECT key_id, COUNT(*) as count, MAX(timestamp) as last_used
            FROM request_log WHERE timestamp >= ? AND key_id != 'anonymous'
            GROUP BY key_id ORDER BY count DESC LIMIT 20
        """, (cutoff,)).fetchall()]

    return {
        "time_series": time_series,
        "by_provider": by_provider,
        "by_model": by_model,
        "by_key": by_key,
        "period_hours": hours
    }

@app.get("/dashboard/provider-health")
def provider_health():
    with get_stats_db() as conn:
        providers = [dict(r) for r in conn.execute("SELECT * FROM provider_latency").fetchall()]
    # Add providers from env that haven't been used yet
    configured = []
    if GROQ_KEYS: configured.append("groq")
    if GEMINI_KEYS: configured.append("gemini")
    if MISTRAL_KEYS: configured.append("mistral")
    if DEEPSEEK_KEYS: configured.append("deepseek")
    if OPENAI_KEYS: configured.append("openai")
    configured.append("ollama")

    result = {}
    for p in configured:
        existing = next((x for x in providers if x["provider"] == p), None)
        result[p] = {
            "configured": True,
            "keys_count": len(load_keys(f"{p.upper()}_API_KEY".replace("OLLAMA", "")) if p != "ollama" else ["local"]),
            "avg_latency_ms": existing["avg_latency_ms"] if existing else None,
            "last_checked": existing["last_checked"] if existing else None,
            "status": existing["status"] if existing else "unknown"
        }
    return result

@app.get("/dashboard/cost-estimate")
def cost_estimate(hours: int = Query(default=24, ge=1, le=720)):
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_stats_db() as conn:
        rows = [dict(r) for r in conn.execute("""
            SELECT provider, SUM(prompt_tokens) as total_prompt, SUM(completion_tokens) as total_completion
            FROM request_log WHERE timestamp >= ? AND status='success'
            GROUP BY provider
        """, (cutoff,)).fetchall()]

    total_cost = 0.0
    providers_cost = []
    for r in rows:
        pricing = MODEL_PRICING.get(r["provider"], {"input": 0, "output": 0})
        cost_input = (r["total_prompt"] / 1_000_000) * pricing["input"]
        cost_output = (r["total_completion"] / 1_000_000) * pricing["output"]
        cost = round(cost_input + cost_output, 6)
        total_cost += cost
        providers_cost.append({
            "provider": r["provider"],
            "prompt_tokens": r["total_prompt"],
            "completion_tokens": r["total_completion"],
            "estimated_cost_usd": cost
        })
    return {
        "total_estimated_cost_usd": round(total_cost, 6),
        "by_provider": providers_cost,
        "period_hours": hours,
        "note": "Ollama/Groq Free/Gemini Free = $0. DeepSeek/OpenAI estimated at standard rates."
    }

# ── ML Service Proxies ────────────────────────────────────────────────

@app.post("/v1/adversarial/poison_dataset")
async def adversarial_poison_proxy(request: Request):
    """Proxy to ml-adversarial service — dataset poisoning."""
    body = await request.json()
    headers = {"Authorization": request.headers.get("Authorization", "")}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ML_ADVERSARIAL_URL}/v1/adversarial/poison_dataset",
            json=body, headers=headers, timeout=120
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)

@app.post("/v1/adversarial/generate_example")
async def adversarial_generate_proxy(request: Request):
    """Proxy to ml-adversarial service — adversarial example generation."""
    body = await request.json()
    headers = {"Authorization": request.headers.get("Authorization", "")}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ML_ADVERSARIAL_URL}/v1/adversarial/generate_example",
            json=body, headers=headers, timeout=30
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)

@app.post("/v1/ml/extract")
async def ml_extract_proxy(request: Request):
    """Proxy to ml-extraction service — data extraction from language models."""
    body = await request.json()
    headers = {"Authorization": request.headers.get("Authorization", "")}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ML_EXTRACTION_URL}/v1/ml/extract",
            json=body, headers=headers, timeout=300
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)

@app.post("/v1/ml/membership_inference")
async def ml_membership_proxy(request: Request):
    """Proxy to ml-extraction service — membership inference attack."""
    body = await request.json()
    headers = {"Authorization": request.headers.get("Authorization", "")}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ML_EXTRACTION_URL}/v1/ml/membership_inference",
            json=body, headers=headers, timeout=120
        )
    return JSONResponse(resp.json(), status_code=resp.status_code)

@app.get("/v1/ml/models")
async def ml_models_proxy():
    """List available extraction models."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ML_EXTRACTION_URL}/v1/ml/models", timeout=10)
    return JSONResponse(resp.json(), status_code=resp.status_code)

# ── Vision / Image Generation (Proxy to Ollama) ─────────────────────

@app.post("/v1/images/generate")
async def image_generate(request: Request):
    """Generate images via Ollama (requires pulled vision/image model)."""
    body = await request.json()
    model = body.get("model", "llava")
    prompt = body.get("prompt", "")
    if not prompt:
        raise HTTPException(400, "prompt required")

    # Route to Ollama's generate endpoint
    ollama_payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": body.get("temperature", 0.7)},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/generate", json=ollama_payload, timeout=120
        )
    if resp.status_code != 200:
        raise HTTPException(resp.status_code, f"Ollama error: {resp.text[:500]}")

    data = resp.json()
    return JSONResponse({
        "id": f"img-{uuid.uuid4().hex[:8]}",
        "model": model,
        "response": data.get("response", ""),
        "total_duration_ms": data.get("total_duration", 0) / 1_000_000,
        "note": "For dedicated image generation models (stable-diffusion), pull via ollama pull first. Currently proxying to Ollama generate endpoint.",
    })

# ── Fine-Tuning Proxy (Route to Cloud APIs) ──────────────────────────

@app.post("/v1/finetune")
async def finetune_proxy(request: Request):
    """Proxy fine-tuning requests to cloud provider APIs or local Ollama."""
    body = await request.json()
    provider = body.get("provider", "groq")
    model = body.get("model", "llama-3.3-70b-versatile")
    dataset_url = body.get("dataset", "")
    adapter_name = body.get("adapter_name", "sovereign-lora")

    if not dataset_url:
        raise HTTPException(400, "dataset URL or path required")

    if provider == "openai":
        if not OPENAI_KEYS:
            raise HTTPException(500, "No OpenAI keys configured")
        key = random.choice(OPENAI_KEYS)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        ft_payload = {
            "model": model,
            "training_file": dataset_url,
            "hyperparameters": body.get("hyperparameters", {}),
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.openai.com/v1/fine_tuning/jobs",
                json=ft_payload, headers=headers, timeout=30
            )
        return JSONResponse(resp.json(), status_code=resp.status_code)

    elif provider == "groq":
        return JSONResponse({
            "status": "not_available",
            "provider": "groq",
            "message": "Groq does not currently offer fine-tuning. Use ollama create with a Modelfile for local fine-tuning, or use OpenAI/DeepSeek providers.",
        })

    elif provider == "ollama":
        return JSONResponse({
            "status": "guidance",
            "provider": "ollama",
            "instructions": {
                "method": "Ollama Modelfile",
                "steps": [
                    f"1. Create a Modelfile for '{adapter_name}'",
                    f"2. Add: FROM {model}",
                    "3. Add: SYSTEM \"\"\"your uncensored system prompt here\"\"\"",
                    "4. Add: PARAMETER temperature 0.9",
                    f"5. Run: ollama create {adapter_name} -f Modelfile",
                    f"6. Use model via gateway: provider=ollama, model={adapter_name}",
                ],
            },
        })

    elif provider == "deepseek":
        if not DEEPSEEK_KEYS:
            raise HTTPException(500, "No DeepSeek keys configured")
        key = random.choice(DEEPSEEK_KEYS)
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.deepseek.com/v1/fine_tuning/jobs",
                json={"model": model, "training_file": dataset_url},
                headers=headers, timeout=30
            )
        return JSONResponse(resp.json(), status_code=resp.status_code)

    else:
        raise HTTPException(400, f"Unknown provider: {provider}. Supported: openai, deepseek, ollama, groq")

@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0", "timestamp": datetime.utcnow().isoformat()}