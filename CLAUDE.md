# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Reflex — Observe → Analyze → Act. Integrates with existing monitoring tools (Prometheus, ELK, OpenTelemetry) and adds AI-powered analysis and remediation with a conversational ChatOps interface.

**Stack:** Python 3.9+ (FastAPI), LangGraph, LangChain, Streamlit, PostgreSQL (TimescaleDB + pgvector planned)

## Architecture

- **Observe:** Receive alarms via `POST /webhook/alertmanager` (Alertmanager-compatible)
- **Analyze:** LangGraph pipeline — Intake → Noise Check → RCA (LLM + RAG) → Review Agent (risk + critique) → Decision
- **Act:** Auto-execute, human approval (with Decision Brief), or escalate based on confidence x blast radius
- **ChatOps:** Separate LangGraph ReAct agent with 10 tools wrapping the pipeline and providers. Adapters: Streamlit chat, CLI, Slack (stub)

## Build & Run

```bash
# Install
pip install -e ".[dev]"

# API server
python -m uvicorn backend.app.main:app --reload --port 8000

# Streamlit demo (pipeline + live incidents + actions)
streamlit run streamlit_demo.py --server.port 8503

# Streamlit chat UI
streamlit run streamlit_chat.py --server.port 8501

# Chat CLI
python chat_cli.py              # remote (needs API server)
python chat_cli.py --local      # local (no server needed)

# CLI demo
python demo.py --mock-llm

# Tests
python -m pytest tests/ -v
```

## Key Directories

- `backend/app/agents/` — LangGraph analysis pipeline (state.py, graph.py, nodes/)
- `backend/app/chat/` — ChatOps engine (engine.py, tools.py, prompts/, logging.py)
- `backend/app/api/` — FastAPI routers (chat.py, webhook.py)
- `backend/app/providers/` — Abstract interfaces + LLM provider (base.py, factory.py, llm.py)
- `backend/app/incidents.py` — Shared incident store (singleton, in-memory)
- `backend/app/adapters/` — Platform adapters (slack.py)
- `mock/` — Mock providers, scenarios, data (runbooks, Jira tickets, Confluence pages)
- `tests/` — 95 tests (pytest + pytest-asyncio)

## Key API Endpoints

- `POST /webhook/alertmanager` — Receive alarms, run pipeline, store incidents
- `POST /chat` — Conversational AI (session_id, message, user_id)
- `GET /chat/{session_id}/history` — Conversation history
- `GET /incidents` — List incidents (optional `?since=` for polling)
- `GET /incidents/{id}` — Full incident details
- `POST /incidents/{id}/approve` — Approve pending action
- `POST /incidents/{id}/deny` — Deny with reason
- `POST /incidents/{id}/escalate` — Escalate to on-call
- `POST /analyze` — Run pipeline on custom alarm payload
- `POST /scenarios/{name}/run` — Run a demo scenario
- `GET /scenarios` — List available scenarios

## Conventions

- Python 3.9 compatibility — use `Optional[str]` not `str | None`, `List` not `list[]`
- Provider pattern: all external access via Protocol interfaces in `providers/base.py`
- Mock mode works without any API keys or infrastructure
- LLM provider auto-detects from env: `ANTHROPIC_API_KEY` → Anthropic, `OPENAI_API_KEY` → OpenAI, else → Mock
- Chat tools are thin wrappers around provider interfaces
- Layered prompts in `chat/prompts/*.md` — edit without code changes
- Structured NDJSON logging for all chat interactions
- pytest with `asyncio_mode = "auto"` for async tests
