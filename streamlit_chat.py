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

st.title("🔧 Reflex Chat")
st.caption(
    f"AI-powered incident management assistant | "
    f"Session: `{st.session_state.session_id}` | "
    f"Mode: {'local' if LOCAL_MODE else 'remote'}"
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

# Chat input
if prompt := st.chat_input("Ask Reflex about an incident..."):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get response
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

# Sidebar
with st.sidebar:
    st.header("Session")
    if st.button("New Session"):
        st.session_state.session_id = f"streamlit-{uuid.uuid4().hex[:8]}"
        st.session_state.messages = []
        st.session_state.engine = None
        st.rerun()

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
