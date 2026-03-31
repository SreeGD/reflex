# AIOps Platform

Intelligent operations platform that moves from manual ops to automated AIOps through three pillars: **Observe → Analyze → Act**.

## Vision

**Current state:** Alarms fire → Sev 2 Jira tickets created → on-call engineer searches runbooks → manual remediation. Heavy reliance on tribal knowledge.

**Target state:** Alarms fire → AI analyzes with full context (runbooks, past incidents, correlated signals) → suggests or auto-executes remediation.

## Three Pillars

### 1. Observe (Integrate with existing tools)
- **Metrics** — Prometheus
- **Logs** — Fluentd / ELK Stack
- **Traces** — OpenTelemetry

### 2. Analyze (The Brain)
Six-step intelligence pipeline powered by LangGraph:

1. **Baselining** — Define normal behavior (ML)
2. **Detection** — Find anomalies against baselines (ML)
3. **Noise Management** — Filter false alarms, reduce alert fatigue (LLM)
4. **Correlation** — Correlate across metrics, logs, and traces (LLM)
5. **RCA** — Root cause analysis with natural language output (LLM + RAG over runbooks/Jira)
6. **Prediction** — Forecast issues from historical patterns (ML)

Two model types:
- **LLM** — Runbooks, Jira ticket history, tribal knowledge → RCA, correlation, noise management
- **ML** — Historical metrics/failure data → baselining, detection, prediction

### 3. Act (Alerting + Remediation)
- **Alerting** — Deduplicated, correlated alerts with RCA context and runbook steps attached
- **Remediation** — Agentic AI with MCP servers → auto-execute low-risk actions, human approval for high-risk

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, FastAPI |
| Frontend | React, TypeScript |
| Database | PostgreSQL (TimescaleDB + pgvector) |
| Agent Orchestration | LangGraph |
| Task Queue | Celery + Redis |
| Embeddings | pgvector (RAG over runbooks and Jira tickets) |
| Remediation | MCP (Model Context Protocol) servers |

## Incremental Roadmap

### Increment 1 (MVP) — Two parallel tracks
- **Track A: RAG Knowledge Assistant** — Ingest runbooks (markdown/git) and historical Jira tickets → when an alarm arrives, retrieve relevant runbook + similar past tickets → suggest remediation steps
- **Track B: Noise Reduction + Correlation** — Classify alarms as real vs noise, correlate related alarms into single incidents, reduce Sev 2 ticket volume

### Increment 2 — Smarter Analysis
- ML-based baselining and anomaly detection (beyond static thresholds)
- Prediction and forecasting from historical data

### Increment 3 — Automated Remediation
- MCP server integration for executing runbook steps
- Semi-automated: auto-execute low-risk, approval for high-risk
- Full audit trail

### Increment 4 — Full AIOps Loop
- Closed-loop: detect → analyze → remediate → verify fix → update knowledge base
- Self-improving: successful remediations feed back into runbooks and models

## Project Structure

```
aiops/
├── docker-compose.yml
├── backend/
│   ├── pyproject.toml
│   ├── alembic/                 # Database migrations
│   └── app/
│       ├── main.py              # FastAPI app
│       ├── config.py            # Pydantic Settings
│       ├── database.py          # SQLAlchemy async engine
│       ├── models/              # ORM models
│       ├── schemas/             # Pydantic request/response
│       ├── api/                 # FastAPI routers
│       ├── agents/              # LangGraph analyze pipeline
│       ├── knowledge/           # Runbook loader, Jira sync, RAG retriever
│       ├── ml/                  # ML models (baselining, detection, forecasting)
│       ├── services/            # Business logic
│       └── workers/             # Celery tasks
├── frontend/
│   └── src/
│       ├── pages/               # Dashboard, Assistant, Incidents, Runbooks
│       ├── components/
│       └── api/
└── shared/
    └── openapi.yaml
```

## Getting Started

### Prerequisites
- Docker and Docker Compose
- Python 3.12+
- Node.js 20+

### Run locally
```bash
# Start infrastructure (PostgreSQL/TimescaleDB, Redis)
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
```

### Run tests
```bash
cd backend
pytest
```

## Architecture Details

See [architecture plan](.claude/plans/wild-wobbling-melody.md) for detailed data models, API endpoints, LangGraph pipeline design, and event flow diagrams.
