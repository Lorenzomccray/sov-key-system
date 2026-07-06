#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║           ⚡ GODMODE COMMAND CENTER v2.0                    ║
║  Sovereign AI Key System — Real-Time Operations Dashboard   ║
║  Your Life Mission. Your AI. Your Rules.                    ║
╚══════════════════════════════════════════════════════════════╝

Routes:
  - Key Authority:  http://key-authority:8001  (key lifecycle, audit)
  - AI Gateway:     http://gateway:8000         (multi-provider routing)

Features:
  - Real-time gateway metrics with auto-refresh
  - Historical analytics with interactive Plotly charts
  - Provider health matrix (latency, status, key count)
  - Cost estimation across all providers
  - Full key lifecycle management (create, revoke, label, stats)
  - Audit log viewer with filtering
  - AI chat assistant powered by your own gateway
  - Complete instruction manual
"""

import os, time, requests, pandas as pd, json
from datetime import datetime, timedelta

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ── Page Config (MUST be first st. call) ──────────────────────────────
st.set_page_config(
    page_title="GODMODE COMMAND CENTER",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Configuration ─────────────────────────────────────────────────────
# Module-level config MUST use os.getenv() only — st.secrets is not
# available at import time on Streamlit Cloud and will crash the app.
# To use TOML secrets from App Settings, read st.secrets at render time
# (see the "🔐 Secrets" diagnostic tab below).
KEY_AUTHORITY = os.getenv("KEY_AUTHORITY_URL", "http://key-authority:8001")
GATEWAY = os.getenv("GATEWAY_URL", "http://gateway:8000")
ADMIN_KEY = os.getenv("MASTER_ADMIN_KEY", "sov_master_admin_do_not_share")
DASHBOARD_AI_KEY = os.getenv("DASHBOARD_AI_KEY", "")

# ── Custom CSS ────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* ── Base Theme ── */
    .stApp { background: linear-gradient(135deg, #050510 0%, #0a0a1a 50%, #050510 100%); }
    .main { background: transparent; }
    
    /* ── Metric Cards ── */
    [data-testid="stMetric"] {
        background: linear-gradient(145deg, #0d0d20, #0a0a18);
        border: 1px solid rgba(0, 255, 0, 0.15);
        border-radius: 12px;
        padding: 1rem;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4);
        transition: all 0.2s ease;
    }
    [data-testid="stMetric"]:hover {
        border-color: rgba(0, 255, 0, 0.4);
        box-shadow: 0 4px 32px rgba(0, 255, 0, 0.08);
    }
    [data-testid="stMetric"] label { color: #888 !important; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1px; }
    [data-testid="stMetric"] [data-testid="stMetricValue"] { color: #00ff00 !important; font-size: 2rem !important; font-weight: 700; font-family: 'JetBrains Mono', monospace; }

    /* ── Headers ── */
    h1 { color: #00ff00 !important; font-family: 'JetBrains Mono', monospace; text-shadow: 0 0 40px rgba(0, 255, 0, 0.3); }
    h2, h3 { color: #00cc00 !important; font-family: 'JetBrains Mono', monospace; }
    
    /* ── DataFrames ── */
    [data-testid="stDataFrame"] { background: rgba(10, 10, 30, 0.6); border: 1px solid rgba(0, 255, 0, 0.1); border-radius: 8px; }
    
    /* ── Buttons ── */
    .stButton > button {
        background: linear-gradient(135deg, #00ff00, #00cc00) !important;
        color: #050510 !important;
        font-weight: 700 !important;
        border: none !important;
        border-radius: 8px !important;
        transition: all 0.2s ease !important;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    .stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 20px rgba(0, 255, 0, 0.3); }
    
    /* ── Sidebar ── */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #08081a, #050510) !important;
        border-right: 1px solid rgba(0, 255, 0, 0.1);
    }
    [data-testid="stSidebar"] h2 { color: #00ff00 !important; }
    [data-testid="stSidebar"] label { color: #aaa !important; }

    /* ── Chat ── */
    [data-testid="stChatMessage"] { background: rgba(10, 10, 30, 0.4); border: 1px solid rgba(0, 255, 0, 0.08); border-radius: 8px; padding: 0.5rem; margin: 0.5rem 0; }
    
    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] { gap: 2px; background: transparent; }
    .stTabs [data-baseweb="tab"] {
        background: rgba(10, 10, 30, 0.6);
        border: 1px solid rgba(0, 255, 0, 0.1);
        border-radius: 8px 8px 0 0;
        color: #888;
        padding: 0.6rem 1.2rem;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, rgba(0, 255, 0, 0.1), rgba(0, 200, 0, 0.05)) !important;
        border-bottom: 2px solid #00ff00 !important;
        color: #00ff00 !important;
    }
    
    /* ── Status indicators ── */
    .status-ok { color: #00ff00; }
    .status-err { color: #ff4444; }
    .status-warn { color: #ffaa00; }

    /* ── Code blocks ── */
    code { color: #00ff00; background: rgba(0, 255, 0, 0.05); padding: 2px 6px; border-radius: 4px; }
    pre { background: rgba(10, 10, 30, 0.8); border: 1px solid rgba(0, 255, 0, 0.15); border-radius: 8px; }
    
    /* ── Expanders ── */
    [data-testid="stExpander"] { background: rgba(10, 10, 30, 0.4); border: 1px solid rgba(0, 255, 0, 0.1); border-radius: 8px; }
</style>
""", unsafe_allow_html=True)

# ── State init ────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = 0
if "analytics_hours" not in st.session_state:
    st.session_state.analytics_hours = 24
if "selected_model" not in st.session_state:
    st.session_state.selected_model = "ollama/qwen2.5-coder:7b"

# ── Header ────────────────────────────────────────────────────────────
col_title, col_clock = st.columns([3, 1])
with col_title:
    st.title("⚡ GODMODE COMMAND CENTER")
    st.caption("Sovereign AI Key System · Multi-Provider Gateway · Real-Time Analytics")
with col_clock:
    st.markdown(f"""
    <div style='text-align:right; padding-top:1.3rem;'>
        <span style='color:#00ff00; font-family:monospace; font-size:1.2rem;'>{datetime.now().strftime('%H:%M:%S')}</span><br>
        <span style='color:#888; font-size:0.7rem;'>{datetime.now().strftime('%Y-%m-%d')}</span>
    </div>
    """, unsafe_allow_html=True)

# ── Auto-refresh ──────────────────────────────────────────────────────
if time.time() - st.session_state.last_refresh > 8:
    st.session_state.last_refresh = time.time()
    st.rerun()

# ═══════════════════════════════════════════════════════════════════════
# TAB LAYOUT
# ═══════════════════════════════════════════════════════════════════════
tab_dashboard, tab_analytics, tab_keys, tab_ai, tab_manual = st.tabs([
    "📊 Dashboard", "📈 Analytics", "🔑 Keys", "🤖 AI Chat", "📖 Instructions"
])

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  TAB 1: DASHBOARD — Real-Time Metrics + Health + Cost              ║
# ╚══════════════════════════════════════════════════════════════════════╝
with tab_dashboard:
    # ── Status Row ──
    c1, c2, c3, c4, c5 = st.columns(5)

    # Gateway health
    gateway_online = False
    try:
        resp = requests.get(f"{GATEWAY}/health", timeout=3)
        gateway_online = resp.status_code == 200
    except:
        gateway_online = False

    # Key authority health
    ka_online = False
    try:
        resp = requests.get(f"{KEY_AUTHORITY}/health", timeout=3)
        ka_online = resp.status_code == 200
    except:
        ka_online = False

    with c1:
        icon = "🟢" if gateway_online else "🔴"
        st.metric("AI Gateway", f"{icon} Online" if gateway_online else f"{icon} Offline")
    with c2:
        icon = "🟢" if ka_online else "🔴"
        st.metric("Key Authority", f"{icon} Healthy" if ka_online else f"{icon} Down")
    with c3:
        try:
            stats = requests.get(f"{GATEWAY}/dashboard/stats", timeout=3).json()
            st.metric("Total Requests", f"{stats['total_requests']:,}")
        except:
            st.metric("Total Requests", "—")
    with c4:
        try:
            st.metric("Success Rate", f"{stats['success_count']}/{stats['total_requests']}" if stats else "—")
        except:
            st.metric("Success Rate", "—")
    with c5:
        try:
            cost = requests.get(f"{GATEWAY}/dashboard/cost-estimate?hours=720", timeout=3).json()
            st.metric("30-Day Cost", f"${cost['total_estimated_cost_usd']:.4f}")
        except:
            st.metric("30-Day Cost", "—")

    st.divider()

    # ── Provider Health Matrix ──
    st.subheader("🩺 Provider Health")
    try:
        health = requests.get(f"{GATEWAY}/dashboard/provider-health", timeout=3).json()
        cols = st.columns(len(health) if health else 6)
        status_map = {"ok": "🟢", "error": "🔴", "unknown": "⚪"}
        for i, (provider, info) in enumerate(health.items()):
            with cols[i % len(cols)]:
                s = status_map.get(info["status"], "⚪")
                lat = f"{info['avg_latency_ms']:.0f}ms" if info.get("avg_latency_ms") else "—"
                st.metric(
                    f"{s} {provider.title()}",
                    lat,
                    f"{info['keys_count']} key(s)"
                )
    except Exception as e:
        st.warning(f"Provider health unavailable: {e}")

    st.divider()

    # ── Recent Requests + Key Summary ──
    col_recent, col_keys = st.columns([3, 2])

    with col_recent:
        st.subheader("🕐 Recent Requests")
        try:
            if stats and stats.get("recent_requests"):
                df = pd.DataFrame(stats["recent_requests"])
                df["status_icon"] = df["status"].apply(lambda x: "✅" if x == "success" else "❌")
                df["lat"] = df["latency_ms"].apply(lambda x: f"{x:.0f}ms" if x else "—")
                df["tokens"] = df.apply(lambda r: f"{r.get('prompt_tokens',0)}+{r.get('completion_tokens',0)}", axis=1)
                st.dataframe(
                    df[["status_icon", "timestamp", "provider", "model", "lat", "tokens"]].head(20),
                    use_container_width=True,
                    height=320,
                    column_config={
                        "status_icon": "Status",
                        "timestamp": "Time",
                        "provider": "Provider",
                        "model": "Model",
                        "lat": "Latency",
                        "tokens": "Tokens (P+C)",
                    }
                )
            else:
                st.info("No requests yet. Send your first API call to the gateway.")
        except Exception as e:
            st.warning(f"Stats unavailable: {e}")

    with col_keys:
        st.subheader("🔑 Key Summary")
        try:
            key_stats = requests.get(
                f"{KEY_AUTHORITY}/admin/keys/stats",
                headers={"Authorization": f"Bearer {ADMIN_KEY}"},
                timeout=3
            ).json()
            st.metric("Total Keys", key_stats.get("total_keys", 0))
            st.metric("Active Keys", key_stats.get("active_keys", 0))
            st.metric("Revoked", key_stats.get("revoked_keys", 0))
            st.metric("Total Served", f"{key_stats.get('total_requests_served', 0):,}")
            if key_stats.get("by_environment"):
                st.caption("By environment:")
                for env in key_stats["by_environment"]:
                    st.text(f"  {env['environment']}: {env['count']} keys · {env['total_requests']} reqs")
        except Exception as e:
            st.warning(f"Key stats unavailable: {e}")

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  TAB 2: ANALYTICS — Charts, Trends, Drill-Down                    ║
# ╚══════════════════════════════════════════════════════════════════════╝
with tab_analytics:
    st.subheader("📈 Usage Analytics")

    col_period, col_refresh = st.columns([2, 1])
    with col_period:
        hours = st.select_slider(
            "Time Range",
            options=[1, 6, 12, 24, 48, 72, 168, 720],
            value=st.session_state.analytics_hours,
            format_func=lambda h: f"{h}h" if h < 48 else f"{h//24}d"
        )
        st.session_state.analytics_hours = hours

    try:
        analytics = requests.get(
            f"{GATEWAY}/dashboard/analytics?hours={hours}",
            timeout=5
        ).json()

        # ── Requests over time ──
        if analytics.get("time_series"):
            df_time = pd.DataFrame(analytics["time_series"])
            fig_time = px.line(
                df_time, x="hour", y="count",
                title=f"Requests Over Time ({hours}h)",
                labels={"hour": "Time", "count": "Requests"},
            )
            fig_time.update_traces(line_color="#00ff00", fill="tozeroy", fillcolor="rgba(0,255,0,0.05)")
            fig_time.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font_color="#888", title_font_color="#00ff00",
                xaxis=dict(gridcolor="rgba(0,255,0,0.05)", zeroline=False),
                yaxis=dict(gridcolor="rgba(0,255,0,0.05)", zeroline=False),
            )
            st.plotly_chart(fig_time, use_container_width=True)
        else:
            st.info("No time-series data yet. Send some requests to populate analytics.")

        # ── By Provider + By Model ──
        col_prov, col_model = st.columns(2)

        with col_prov:
            if analytics.get("by_provider"):
                df_prov = pd.DataFrame(analytics["by_provider"])
                fig_prov = px.bar(
                    df_prov, x="provider", y="count", color="provider",
                    title="Requests by Provider",
                    text="count",
                )
                fig_prov.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#888", title_font_color="#00ff00",
                    showlegend=False,
                    xaxis=dict(gridcolor="rgba(0,255,0,0.05)"),
                    yaxis=dict(gridcolor="rgba(0,255,0,0.05)"),
                )
                st.plotly_chart(fig_prov, use_container_width=True)

                # Latency by provider
                fig_lat = px.bar(
                    df_prov, x="provider", y="avg_latency",
                    title="Avg Latency by Provider (ms)",
                    text=df_prov["avg_latency"].apply(lambda x: f"{x:.0f}"),
                )
                fig_lat.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#888", title_font_color="#00ff00",
                    showlegend=False,
                    xaxis=dict(gridcolor="rgba(0,255,0,0.05)"),
                    yaxis=dict(gridcolor="rgba(0,255,0,0.05)"),
                )
                st.plotly_chart(fig_lat, use_container_width=True)
            else:
                st.info("No provider data yet.")

        with col_model:
            if analytics.get("by_model"):
                df_model = pd.DataFrame(analytics["by_model"])
                fig_model = px.bar(
                    df_model, x="count", y="model", orientation="h",
                    title="Requests by Model",
                    text="count",
                )
                fig_model.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font_color="#888", title_font_color="#00ff00",
                    showlegend=False,
                    xaxis=dict(gridcolor="rgba(0,255,0,0.05)"),
                    yaxis=dict(gridcolor="rgba(0,255,0,0.05)", categoryorder="total ascending"),
                )
                st.plotly_chart(fig_model, use_container_width=True)

                # By key
                if analytics.get("by_key"):
                    df_key = pd.DataFrame(analytics["by_key"])
                    st.subheader("Usage by API Key")
                    st.dataframe(df_key, use_container_width=True)

        # ── Cost Estimate ──
        st.subheader("💰 Cost Estimate")
        try:
            cost_data = requests.get(f"{GATEWAY}/dashboard/cost-estimate?hours={hours}", timeout=3).json()
            if cost_data.get("by_provider"):
                df_cost = pd.DataFrame(cost_data["by_provider"])
                fig_cost = px.treemap(
                    df_cost, path=["provider"], values="estimated_cost_usd",
                    title=f"Estimated Cost Distribution (${cost_data['total_estimated_cost_usd']:.6f})",
                    color="estimated_cost_usd",
                    color_continuous_scale="Greens",
                )
                fig_cost.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", font_color="#888",
                    title_font_color="#00ff00",
                )
                st.plotly_chart(fig_cost, use_container_width=True)
                st.caption(cost_data.get("note", ""))
            else:
                st.info("No cost data available.")
        except:
            st.warning("Cost estimate unavailable.")

    except Exception as e:
        st.warning(f"Analytics unavailable — gateway may be starting: {e}")

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  TAB 3: KEYS — Full Lifecycle Management                          ║
# ╚══════════════════════════════════════════════════════════════════════╝
with tab_keys:
    col_key_action, col_key_view = st.columns([1, 2])

    with col_key_action:
        st.subheader("🔧 Key Actions")
        action = st.radio("Operation", ["📝 Create New Key", "🚫 Revoke Key", "📋 Audit Log"], key="key_action_radio")

        if action == "📝 Create New Key":
            env = st.selectbox("Environment", ["test", "live", "int"])
            label = st.text_input("Label (optional)", placeholder="e.g., Dashboard AI, My App")
            duration = st.number_input("Validity (days)", 1, 3650, 365)
            if st.button("⚡ Generate Sovereign Key", type="primary", use_container_width=True):
                try:
                    payload = {"environment": env, "duration_days": duration}
                    if label:
                        payload["label"] = label
                    resp = requests.post(
                        f"{KEY_AUTHORITY}/admin/keys",
                        json=payload,
                        headers={"Authorization": f"Bearer {ADMIN_KEY}"},
                        timeout=5
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        st.success("🔥 Key Created — Copy It Now!")
                        st.code(data["full_key"], language="text")
                        st.info(f"**Key ID:** `{data['key_id']}`\n\n**Prefix:** `{data['prefix']}`\n\n**Expires:** {data['expires_at']}\n\n**This key will NEVER be shown again.**")
                    else:
                        st.error(f"Error {resp.status_code}: {resp.text}")
                except Exception as e:
                    st.error(f"Connection failed: {e}")

        elif action == "🚫 Revoke Key":
            prefix = st.text_input("Key Prefix (first 12 hex chars)", max_chars=12, placeholder="a1b2c3d4e5f6")
            if st.button("🛑 Revoke Key", type="primary", use_container_width=True):
                if not prefix:
                    st.error("Enter a key prefix.")
                else:
                    try:
                        resp = requests.post(
                            f"{KEY_AUTHORITY}/admin/revoke",
                            json={"prefix": prefix},
                            headers={"Authorization": f"Bearer {ADMIN_KEY}"},
                            timeout=5
                        )
                        if resp.status_code == 200:
                            st.success(f"Key `{prefix}` permanently revoked.")
                        else:
                            st.error(f"Error: {resp.text}")
                    except Exception as e:
                        st.error(f"Connection failed: {e}")

        elif action == "📋 Audit Log":
            if st.button("🔄 Load Audit Log", use_container_width=True):
                try:
                    audit = requests.get(
                        f"{KEY_AUTHORITY}/admin/audit-log?limit=100",
                        headers={"Authorization": f"Bearer {ADMIN_KEY}"},
                        timeout=5
                    ).json()
                    if audit:
                        df_audit = pd.DataFrame(audit)
                        st.dataframe(df_audit, use_container_width=True, height=400)
                    else:
                        st.info("Audit log empty.")
                except Exception as e:
                    st.error(f"Failed: {e}")

    with col_key_view:
        st.subheader("📋 Active Key Inventory")
        try:
            keys = requests.get(
                f"{KEY_AUTHORITY}/admin/keys",
                headers={"Authorization": f"Bearer {ADMIN_KEY}"},
                timeout=5
            ).json()
            if keys:
                df_keys = pd.DataFrame(keys)
                df_keys["status_icon"] = df_keys["status"].apply(
                    lambda x: "🟢" if x == "active" else ("🔴" if x == "revoked" else "⚠️")
                )
                st.dataframe(
                    df_keys[["status_icon", "prefix", "environment", "label", "status", "created_at", "expires_at", "requests_count", "last_used"]],
                    use_container_width=True,
                    height=420,
                    column_config={
                        "status_icon": st.column_config.TextColumn("", width="small"),
                        "prefix": "Prefix",
                        "environment": "Env",
                        "label": "Label",
                        "status": "Status",
                        "created_at": "Created",
                        "expires_at": "Expires",
                        "requests_count": "Reqs",
                        "last_used": "Last Used",
                    }
                )
            else:
                st.info("No keys issued yet. Create your first sovereign key to begin.")
        except Exception as e:
            st.error(f"Cannot reach key authority: {e}")

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  TAB 4: AI CHAT — Your Gateway-Powered Assistant                  ║
# ╚══════════════════════════════════════════════════════════════════════╝
with tab_ai:
    st.subheader("🤖 GODMODE AI Assistant")
    st.caption("Powered by YOUR sovereign gateway. Every model at your command.")

    if not DASHBOARD_AI_KEY:
        st.error("⚠️ Dashboard AI key not set. Add `DASHBOARD_AI_KEY` to your `.env` file and restart.")
    else:
        # Model selector
        model_options = [
            "ollama/qwen2.5-coder:7b",
            "ollama/llama3.2:3b",
            "groq/llama-3.3-70b-versatile",
            "groq/mixtral-8x7b-32768",
            "groq/llama-3.1-70b-versatile",
            "gemini/gemini-2.0-flash",
            "gemini/gemini-1.5-pro",
            "mistral/mistral-small-latest",
            "deepseek/deepseek-chat",
            "openai/gpt-3.5-turbo",
        ]
        selected_model = st.selectbox(
            "Choose AI Model",
            model_options,
            index=model_options.index(st.session_state.selected_model) if st.session_state.selected_model in model_options else 0,
            key="model_selector"
        )
        st.session_state.selected_model = selected_model

        # Chat display
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # Chat input
        if prompt := st.chat_input("Command your AI..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner(f"Routing through {selected_model}..."):
                    try:
                        t0 = time.time()
                        resp = requests.post(
                            f"{GATEWAY}/v1/chat/completions",
                            headers={
                                "Authorization": f"Bearer {DASHBOARD_AI_KEY}",
                                "Content-Type": "application/json",
                            },
                            json={
                                "model": selected_model,
                                "messages": [{"role": "user", "content": prompt}],
                                "stream": False,
                            },
                            timeout=120,
                        )
                        latency = (time.time() - t0) * 1000
                        if resp.status_code == 200:
                            data = resp.json()
                            answer = data["choices"][0]["message"]["content"]
                            # Append gateway metadata
                            meta = data.get("gateway_meta", {})
                            usage = data.get("usage", {})
                            footer = f"\n\n---\n⏱️ {latency:.0f}ms · {meta.get('provider', selected_model)} · {usage.get('total_tokens', '?')} tokens"
                            st.markdown(answer + footer)
                            st.session_state.messages.append({"role": "assistant", "content": answer + footer})
                        else:
                            st.error(f"Gateway Error {resp.status_code}: {resp.text[:500]}")
                    except requests.exceptions.Timeout:
                        st.error("Request timed out (120s). The model may be overloaded or unreachable.")
                    except Exception as e:
                        st.error(f"Connection error: {e}")

        col_clear, col_export = st.columns(2)
        with col_clear:
            if st.button("🧹 Clear Chat", use_container_width=True):
                st.session_state.messages = []
                st.rerun()
        with col_export:
            if st.button("📤 Export Chat", use_container_width=True):
                if st.session_state.messages:
                    export = "\n\n".join([f"**{m['role'].upper()}:** {m['content']}" for m in st.session_state.messages])
                    st.download_button("Download chat.md", export, "godmode-chat.md", "text/markdown")
                else:
                    st.caption("No messages to export.")

# ╔══════════════════════════════════════════════════════════════════════╗
# ║  TAB 5: INSTRUCTIONS — Complete User & Developer Manual           ║
# ╚══════════════════════════════════════════════════════════════════════╝
with tab_manual:
    st.header("📖 GODMODE COMMAND CENTER — Complete Manual")

    with st.expander("🌐 How to Use Your Sovereign API", expanded=True):
        st.markdown("""
### Getting Started

Your system exposes an **OpenAI-compatible API** at **`http://localhost:8000/v1`**.

Use your sovereign key (starts with `sov_`) in the `Authorization` header.

#### cURL Example
```bash
curl http://localhost:8000/v1/chat/completions \\
  -H "Authorization: Bearer sov_test_a1b2c3d4e5f6_abcdef0123456789abcdef0123456789" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "ollama/qwen2.5-coder:7b",
    "messages": [{"role": "user", "content": "Explain quantum computing in 3 sentences."}]
  }'
```

#### Python Example
```python
import requests

response = requests.post(
    "http://localhost:8000/v1/chat/completions",
    headers={
        "Authorization": "Bearer YOUR_SOVEREIGN_KEY",
        "Content-Type": "application/json"
    },
    json={
        "model": "groq/llama-3.3-70b-versatile",
        "messages": [{"role": "user", "content": "Write a haiku about AI sovereignty."}]
    }
)
print(response.json()["choices"][0]["message"]["content"])
```

#### JavaScript / Node.js
```javascript
const response = await fetch("http://localhost:8000/v1/chat/completions", {
  method: "POST",
  headers: {
    "Authorization": "Bearer YOUR_SOVEREIGN_KEY",
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    model: "gemini/gemini-2.0-flash",
    messages: [{ role: "user", content: "What is the meaning of life?" }]
  })
});
const data = await response.json();
console.log(data.choices[0].message.content);
```
        """)

    with st.expander("🤖 Available Models & Providers"):
        st.markdown("""
### Model Format
All models use the format **`provider/model-name`**. Examples:

| Provider | Example Model | Auth | Cost |
|----------|--------------|------|------|
| **ollama** | `ollama/qwen2.5-coder:7b` | None (local) | Free |
| **ollama** | `ollama/llama3.2:3b` | None (local) | Free |
| **groq** | `groq/llama-3.3-70b-versatile` | GROQ_API_KEY | Free tier |
| **groq** | `groq/mixtral-8x7b-32768` | GROQ_API_KEY | Free tier |
| **gemini** | `gemini/gemini-2.0-flash` | GEMINI_API_KEY | Free tier |
| **gemini** | `gemini/gemini-1.5-pro` | GEMINI_API_KEY | Free tier (limited) |
| **mistral** | `mistral/mistral-small-latest` | MISTRAL_API_KEY | Free tier |
| **deepseek** | `deepseek/deepseek-chat` | DEEPSEEK_API_KEY | Paid |
| **openai** | `openai/gpt-3.5-turbo` | OPENAI_API_KEY | Paid |

#### Multi-Key Failover
You can provide **multiple keys per provider** by separating with commas:
```bash
GROQ_API_KEY=gsk_key1,gsk_key2,gsk_key3
```
The gateway automatically rotates through keys when rate limits are hit.

#### Model Auto-Detection
If you omit the provider prefix, the gateway defaults to Ollama:
- `"model": "llama3.2:3b"` → routes to `ollama/llama3.2:3b`
        """)

    with st.expander("🔑 Key Format & Lifecycle"):
        st.markdown("""
### Sovereign Key Format
```
sov_{environment}_{12-char-prefix}_{32-char-secret}
```
Example: `sov_live_a1b2c3d4e5f6_0123456789abcdef0123456789abcdef`

### Environments
| Environment | Purpose |
|-------------|---------|
| `test` | Development & testing |
| `int`  | Internal tools & services |
| `live` | Production applications |

### Key Lifecycle
1. **Create** — Generate a new key with environment + expiration
2. **Use** — Pass in `Authorization: Bearer sov_...` header
3. **Monitor** — Track usage on the Dashboard & Analytics tabs
4. **Revoke** — Permanently disable a key (cannot be undone)

### Security
- Keys are **hashed with HMAC-SHA256 + pepper** — the raw key is never stored
- The pepper is a 32-byte random secret stored in `pepper.txt`
- Rotating the pepper **invalidates ALL existing keys** — use with extreme caution
- Rate limit: **100 requests per minute per key**
        """)

    with st.expander("⚙️ Environment Variables (.env)"):
        st.markdown("""
### Required
```bash
MASTER_ADMIN_KEY=sov_master_admin_do_not_share    # Admin password for dashboard + key management
DASHBOARD_AI_KEY=sov_test_...                      # Key for the dashboard's built-in AI chat
```

### Optional — AI Provider Keys
```bash
GROQ_API_KEY=gsk_yourkey1,gsk_yourkey2             # Comma-separated for multi-key failover
GEMINI_API_KEY=your_gemini_key
MISTRAL_API_KEY=your_mistral_key
DEEPSEEK_API_KEY=your_deepseek_key
OPENAI_API_KEY=your_openai_key
```

### Service URLs (if not using Docker Compose defaults)
```bash
KEY_AUTHORITY_URL=http://key-authority:8001
GATEWAY_URL=http://gateway:8000
OLLAMA_URL=http://localhost:11434
```
        """)

    with st.expander("🐳 Docker Compose Quick Start"):
        st.markdown("""
### Start the full stack
```bash
cd ~/sov-key-system
docker compose up -d
```

### Services
| Service | Port | Purpose |
|---------|------|---------|
| Dashboard | 8501 | Streamlit web UI (this page!) |
| Gateway | 8000 | Multi-provider AI routing + analytics |
| Key Authority | 8001 | Key generation, validation, revocation |

### Access
- **Dashboard:** http://localhost:8501
- **Gateway API:** http://localhost:8000/v1/chat/completions
- **Gateway Health:** http://localhost:8000/health
- **Gateway Stats:** http://localhost:8000/dashboard/stats
- **Gateway Analytics:** http://localhost:8000/dashboard/analytics?hours=24
- **Gateway Cost:** http://localhost:8000/dashboard/cost-estimate?hours=720
- **Key Authority Health:** http://localhost:8001/health

### Stop
```bash
docker compose down
```
        """)

    with st.expander("📊 Dashboard API Reference"):
        st.markdown("""
### Gateway Endpoints (port 8000)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/v1/chat/completions` | POST | Sovereign Key | OpenAI-compatible chat |
| `/health` | GET | None | Health check |
| `/dashboard/stats` | GET | None | Total requests + recent 50 |
| `/dashboard/analytics` | GET | None | Time-series, by provider/model/key |
| `/dashboard/provider-health` | GET | None | Per-provider latency + status |
| `/dashboard/cost-estimate` | GET | None | Estimated cost by provider |

#### Analytics Query Params
- `hours` — Time window (1-720, default 24). E.g. `?hours=168` for 7 days.

### Key Authority Endpoints (port 8001)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | None | Health check |
| `/validate` | POST | Sovereign Key | Validate an API key |
| `/admin/keys` | GET | Bearer ADMIN_KEY | List all keys |
| `/admin/keys` | POST | Bearer ADMIN_KEY | Create a new key |
| `/admin/revoke` | POST | Bearer ADMIN_KEY | Revoke a key by prefix |
| `/admin/keys/stats` | GET | Bearer ADMIN_KEY | Key statistics |
| `/admin/audit-log` | GET | Bearer ADMIN_KEY | Audit trail |
| `/admin/rotate-pepper` | POST | Bearer ADMIN_KEY | Rotate pepper (⚠️ invalidates keys) |
        """)

    with st.expander("🛠️ Troubleshooting"):
        st.markdown("""
### Gateway shows "offline"
1. Check Docker: `docker compose ps`
2. Check logs: `docker compose logs gateway`
3. Verify `.env` has the required keys

### "All keys exhausted for this provider"
- You're being rate-limited by the upstream provider
- Add more keys to the comma-separated env var
- The gateway will auto-rotate

### Key validation fails
- Verify the key format: `sov_{env}_{12-hex}_{32-hex}`
- Check key hasn't expired
- Check key hasn't been revoked
- Ensure using `Authorization: Bearer sov_...`

### Dashboard shows "Connection failed"
- Ensure Docker services are running: `docker compose ps`
- Check network connectivity: `curl http://localhost:8000/health`
- Verify `.env` variables are loaded in `docker-compose.yml`

### AI Chat not working
- Ensure `DASHBOARD_AI_KEY` is set in `.env`
- Verify the key is active (check Keys tab)
- Select a provider that has API keys configured
        """)

    with st.expander("🧬 Architecture Deep Dive"):
        st.markdown("""
### System Architecture
```
┌─────────────────────────────────────────────────┐
│              GODMODE COMMAND CENTER              │
│              Streamlit :8501                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │Dashboard │ │Analytics │ │ AI Chat (gateway) │ │
│  │  Tab     │ │  Tab     │ │  Tab              │ │
│  └────┬─────┘ └────┬─────┘ └────────┬─────────┘ │
│       │             │                │            │
└───────┼─────────────┼────────────────┼────────────┘
        │             │                │
        ▼             ▼                ▼
┌───────────────┐ ┌───────────────────────────────┐
│ Key Authority │ │        AI Gateway :8000        │
│     :8001     │ │  ┌─────┐ ┌──────┐ ┌────────┐ │
│ ┌───────────┐ │ │  │Groq │ │Gemini│ │Mistral │ │
│ │ SQLite DB │ │ │  └──┬──┘ └──┬───┘ └───┬────┘ │
│ │ (keys.db) │ │ │     │       │         │       │
│ └───────────┘ │ │  ┌──┴───────┴─────────┴────┐  │
└───────────────┘ │  │  Ollama :11434 (local)   │  │
                  │  └──────────────────────────┘  │
                  │  ┌──────────────────────────┐  │
                  │  │  Stats DB (SQLite)        │  │
                  │  └──────────────────────────┘  │
                  └───────────────────────────────┘
```

### Data Flow
1. **Client** sends request with `Authorization: Bearer sov_...`
2. **Gateway** validates key with Key Authority
3. **Gateway** routes to the appropriate AI provider
4. **Gateway** logs request to Stats DB (latency, tokens, status)
5. **Dashboard** polls Gateway + Key Authority for real-time metrics

### Key Security Model
```
sov_live_a1b2c3d4e5f6_abcdef0123456789abcdef0123456789
│   │    │              │
│   │    └─ 12-char prefix (indexed, stored)
│   └─ environment (test/int/live)
└─ sov prefix (identifies sovereign key)

Raw key: NEVER stored
Prefix:  Stored in DB for lookup
Hash:    HMAC-SHA256(secret, pepper) — stored in DB
Pepper:  32-byte random secret in pepper.txt — NOT in DB
```

To validate:
1. Parse the key into env + prefix + secret
2. Look up prefix in DB
3. Compute HMAC-SHA256(secret, pepper)
4. Constant-time compare with stored hash

Even if the DB is compromised, the attacker cannot reconstruct the raw key without the pepper file.
        """)

# ── Footer ────────────────────────────────────────────────────────────
st.divider()
st.markdown(
    f"""
    <div style='text-align: center; color: #444; font-size: 0.7rem; padding: 1rem 0;'>
        ⚡ GODMODE COMMAND CENTER v2.0 &nbsp;|&nbsp; Sovereign AI Key System &nbsp;|&nbsp;
        Gateway: {'🟢 Online' if gateway_online else '🔴 Offline'} &nbsp;|&nbsp;
        Key Authority: {'🟢 Healthy' if ka_online else '🔴 Down'}
    </div>
    """,
    unsafe_allow_html=True,
)