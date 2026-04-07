#!/usr/bin/env python3
"""Reflex Chat — Streamlit UI adapter.

Usage:
    streamlit run streamlit_chat.py
    streamlit run streamlit_chat.py -- --local   # run engine directly
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from urllib.request import Request, urlopen

import streamlit as st

# --- Configuration ---

st.set_page_config(
    page_title="Reflex Chat",
    page_icon="🔧",
    layout="centered",
)

LOCAL_MODE = "--local" in sys.argv
BASE_URL = "http://localhost:8000"

# --- Session state ---

if "session_id" not in st.session_state:
    st.session_state.session_id = f"streamlit-{uuid.uuid4().hex[:8]}"
if "messages" not in st.session_state:
    st.session_state.messages = []
if "engine" not in st.session_state:
    st.session_state.engine = None


def get_engine():
    """Lazily initialize the local chat engine."""
    if st.session_state.engine is None:
        from backend.app.chat.engine import create_chat_engine
        st.session_state.engine = create_chat_engine()
    return st.session_state.engine


def _run_async(coro):
    """Run an async coroutine safely, handling existing event loops."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=120)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


def chat_local(message: str) -> dict:
    """Send a message directly to the engine."""
    engine = get_engine()

    async def _do():
        response = await engine.chat(
            st.session_state.session_id,
            message,
            user_id="streamlit",
        )
        return {
            "text": response.text,
            "structured_data": response.structured_data,
            "actions": [{"label": a.label, "action_id": a.action_id} for a in response.actions],
            "severity": response.severity,
        }

    return _run_async(_do())


def chat_remote(message: str) -> dict:
    """Send a message via the API."""
    payload = json.dumps({
        "session_id": st.session_state.session_id,
        "message": message,
        "user_id": "streamlit",
    }).encode()
    req = Request(
        f"{BASE_URL}/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = urlopen(req, timeout=120)
    return json.loads(resp.read())


# --- Severity colors ---

SEVERITY_COLORS = {
    "info": "",
    "warning": "🟡",
    "critical": "🔴",
}


# --- UI ---

import os as _os
_CHAT_SYSTEM = _os.environ.get("MOCK_SYSTEM", "shopfast")
_current_sys = st.session_state.get("chat_system", _CHAT_SYSTEM)
_CHAT_TITLE = "🏥 MedFlow Chat" if _current_sys == "healthcare" else "🔧 Pulse Chat"

st.title(_CHAT_TITLE)
st.caption(
    f"AI-powered incident management assistant | "
    f"Session: `{st.session_state.session_id}` | "
    f"Mode: {'local' if LOCAL_MODE else 'remote'} | "
    f"System: {_current_sys}"
)

# Display message history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        severity = msg.get("severity", "info")
        prefix = SEVERITY_COLORS.get(severity, "")
        if prefix:
            st.markdown(f"{prefix} **[{severity.upper()}]**")
        st.markdown(msg["content"])

        structured = msg.get("structured_data")
        if structured:
            with st.expander("Structured Data"):
                st.json(structured)

def _send_and_display(prompt: str):
    """Send a message to the chat engine and display the response."""
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                if LOCAL_MODE:
                    data = chat_local(prompt)
                else:
                    data = chat_remote(prompt)

                response_text = data.get("text", "No response")
                severity = data.get("severity", "info")
                structured = data.get("structured_data")
                actions = data.get("actions", [])

                prefix = SEVERITY_COLORS.get(severity, "")
                if prefix:
                    st.markdown(f"{prefix} **[{severity.upper()}]**")
                st.markdown(response_text)

                if structured:
                    with st.expander("Structured Data"):
                        st.json(structured)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_text,
                    "severity": severity,
                    "structured_data": structured,
                    "actions": actions,
                    "id": str(len(st.session_state.messages)),
                })

            except Exception as e:
                st.error(f"Error: {e}")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"Error: {e}",
                    "severity": "critical",
                })


# Check for pending message (from sidebar buttons) — last message is user with no response
_has_pending = (
    st.session_state.messages
    and st.session_state.messages[-1]["role"] == "user"
)

if _has_pending:
    _send_and_display(st.session_state.messages[-1]["content"])

# Chat input
if prompt := st.chat_input("Ask Reflex about an incident..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    _send_and_display(prompt)

# Sidebar
with st.sidebar:
    # System selector
    _sys_options = {"ShopFast E-Commerce": "shopfast", "MedFlow Healthcare": "healthcare"}
    if "chat_system" not in st.session_state:
        st.session_state.chat_system = _CHAT_SYSTEM
    _sel_label = st.selectbox(
        "Demo System",
        list(_sys_options.keys()),
        index=list(_sys_options.values()).index(st.session_state.chat_system)
        if st.session_state.chat_system in _sys_options.values() else 0,
        key="system_selector",
    )
    _sel_system = _sys_options[_sel_label]
    if _sel_system != st.session_state.chat_system:
        st.session_state.chat_system = _sel_system
        st.session_state.messages = []
        st.session_state.engine = None
        st.rerun()

    st.divider()
    st.header("Session")
    if st.button("New Session"):
        st.session_state.session_id = f"streamlit-{uuid.uuid4().hex[:8]}"
        st.session_state.messages = []
        st.session_state.engine = None
        st.rerun()

    st.divider()
    st.header("Active Incidents")
    try:
        _inc_resp = urlopen(f"{BASE_URL}/incidents", timeout=3)
        _incidents = json.loads(_inc_resp.read())
    except Exception:
        _incidents = []

    if _incidents:
        for _inc in _incidents[:5]:
            _iid = _inc.get("incident_id", "?")
            _svc = _inc.get("service", "?")
            _decision = _inc.get("action_decision", "")
            _actioned = _inc.get("actioned_by", "")
            _sev = {"critical": "🔴", "warning": "🟡"}.get(_inc.get("severity", ""), "⚪")

            # Status display
            if _actioned:
                _status = {"approved": "✅", "denied": "❌", "escalated": "🔴"}.get(_decision, "⚪")
                st.markdown(f"{_status} **{_iid}**: {_svc} — {_decision}")
            else:
                if st.button(f"{_sev} {_iid}: {_svc}", key=f"inc_{_iid}"):
                    st.session_state.messages.append({
                        "role": "user",
                        "content": f"Tell me about incident {_iid}",
                    })
                    st.rerun()

                # Action buttons for pending incidents
                if _decision == "human_approval" and not _actioned:
                    _c1, _c2, _c3 = st.columns(3)
                    if _c1.button("✅", key=f"sa_{_iid}", help="Approve"):
                        try:
                            _p = json.dumps({"user_id": "chat-user"}).encode()
                            _r = Request(f"{BASE_URL}/incidents/{_iid}/approve", data=_p, headers={"Content-Type": "application/json"})
                            _resp = urlopen(_r, timeout=30)
                            st.success("Approved")
                            st.rerun()
                        except Exception as _e:
                            st.error(str(_e))
                    if _c2.button("❌", key=f"sd_{_iid}", help="Deny"):
                        try:
                            _p = json.dumps({"user_id": "chat-user", "reason": "Denied via chat"}).encode()
                            _r = Request(f"{BASE_URL}/incidents/{_iid}/deny", data=_p, headers={"Content-Type": "application/json"})
                            _resp = urlopen(_r, timeout=30)
                            st.warning("Denied")
                            st.rerun()
                        except Exception as _e:
                            st.error(str(_e))
                    if _c3.button("🔴", key=f"se_{_iid}", help="Escalate"):
                        try:
                            _p = json.dumps({"user_id": "chat-user", "reason": "Escalated via chat"}).encode()
                            _r = Request(f"{BASE_URL}/incidents/{_iid}/escalate", data=_p, headers={"Content-Type": "application/json"})
                            _resp = urlopen(_r, timeout=30)
                            st.info("Escalated")
                            st.rerun()
                        except Exception as _e:
                            st.error(str(_e))
    else:
        st.caption("No incidents yet")

    st.divider()
    st.header("Quick Actions")
    quick_actions = [
        "What runbooks exist for database pool issues?",
        "Show me error logs for order-service",
        "List all incidents",
        "Run analysis on order-service",
    ]
    for qa in quick_actions:
        if st.button(qa, key=f"qa_{qa[:20]}"):
            st.session_state.messages.append({"role": "user", "content": qa})
            st.rerun()
