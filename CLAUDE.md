# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AIOps platform: Observe → Analyze → Act. Integrates with existing monitoring tools (Prometheus, ELK, OpenTelemetry) and adds AI-powered analysis and remediation.

**Stack:** Python (FastAPI), React + TypeScript, PostgreSQL (TimescaleDB + pgvector), LangGraph, Celery + Redis

## Architecture

- **Observe:** Receive alarms via webhooks from existing monitoring tools
- **Analyze:** LangGraph 6-step pipeline — Baselining → Detection → Noise Management → Correlation → RCA → Prediction
  - LLM (via LangChain ChatModel) for RCA, correlation, noise management
  - ML models (scikit-learn/statsmodels) for baselining, detection, prediction
  - RAG over runbooks (markdown/git) and Jira tickets (pgvector) for knowledge-augmented RCA
- **Act:** Alerting (Slack/PagerDuty/email) + Remediation (Agentic AI with MCP servers)

## Build & Run

```bash
# Infrastructure
docker compose up -d

# Backend
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev

# Celery worker
cd backend
celery -A app.workers.celery_app worker --loglevel=info

# Tests
cd backend
pytest
pytest tests/test_specific.py::test_name  # single test
```

## Key Directories

- `backend/app/agents/` — LangGraph analyze pipeline (state.py defines shared state, graph.py wires nodes)
- `backend/app/knowledge/` — RAG system: runbook_loader, jira_sync, embeddings, retriever
- `backend/app/ml/` — ML models for baselining, anomaly detection, forecasting
- `backend/app/services/` — Business logic layer
- `backend/app/api/` — FastAPI routers
- `backend/app/models/` — SQLAlchemy ORM models (PostgreSQL + TimescaleDB hypertables + pgvector)

## Conventions

- Async SQLAlchemy for all database operations
- Pydantic Settings for configuration (env-based via .env)
- Alembic for database migrations
- Celery tasks for long-running operations (LLM calls, ML inference)
- pgvector VECTOR(1536) columns for RAG embeddings
- MCP servers for remediation action execution (future increments)
