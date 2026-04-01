# Reflex

Intelligent operations platform that moves from manual ops to automated incident response through three pillars: **Observe → Analyze → Act**.

## Vision

**Current state:** Alarms fire → Sev 2 Jira tickets created → on-call engineer searches runbooks → manual remediation. Heavy reliance on tribal knowledge.

**Target state:** Alarms fire → AI analyzes with full context (runbooks, past incidents, correlated signals) → suggests or auto-executes remediation.

## Quick Start — Run Locally

The MVP demo runs end-to-end with mock data. No infrastructure, no API keys, no Docker required.

### Prerequisites

- Python 3.9+
- pip (or uv)

### Setup

```bash
git clone https://github.com/SreeGD/reflex.git && cd reflex

# Option A: using pip
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Option B: using uv
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Run the CLI Demo

```bash
python demo.py --list                              # list 5 incident scenarios
python demo.py --mock-llm                          # run default scenario (no API key needed)
python demo.py --scenario all --mock-llm           # run all 5 scenarios
python demo.py --scenario payment_timeout_cascade --mock-llm  # run a specific scenario
python demo.py                                     # run with real Claude (needs ANTHROPIC_API_KEY)
```

To use a real LLM instead of mock responses:
```bash
export ANTHROPIC_API_KEY=sk-ant-...
python demo.py
```

### Run the Streamlit Visual Demo

```bash
pip install streamlit plotly
streamlit run streamlit_demo.py
```

Opens at http://localhost:8501 with three tabs:
- **Pipeline Demo** — Select a scenario, run the full Observe → Analyze → Act pipeline with metrics charts
- **RAG Explorer** — Free-text search over runbooks, Jira tickets, and Confluence docs
- **Knowledge Base Browser** — Browse all indexed knowledge

### What the Demo Shows

An alarm fires → the AI pipeline:
1. **Checks for noise** — is this a known issue or false alarm?
2. **Searches knowledge base** — finds matching runbook, similar past incidents, architecture docs
3. **Produces root cause analysis** — natural language explanation with evidence
4. **Decides action** — auto-execute (high confidence + low risk) or request human approval
5. **Executes remediation** — restarts the service, sends notification

Before: 33 min, 8 manual steps, engineer woken at 3 AM.
After: <10 sec, fully automated, engineer sleeps.

### 5 Incident Scenarios

| Scenario | Service | What Happens | Decision |
|----------|---------|-------------|----------|
| DB Pool Exhaustion | order-service | Connection pool saturates → 500 errors | Auto-execute restart |
| Payment Timeout Cascade | payment-service | External gateway slow → cascading timeouts | Human approval (medium blast) |
| JVM Memory Leak | payment-service | Heap drifts over hours → GC pauses | Human approval (lower confidence) |
| Redis Connection Storm | cart-service | Redis pool spikes to max → cart failures | Auto-execute restart |
| Slow Query Cascade | inventory-service | Missing index → cascades to 3 upstream services | Human approval (lower confidence) |

## Architecture

### High-Level Flow

```mermaid
graph LR
    A[Alarm Webhook] --> B[OBSERVE]
    B --> C[ANALYZE]
    C --> R[REVIEW]
    R --> D[ACT]

    subgraph OBSERVE
        B1[Prometheus] --> B
        B2[ELK Stack] --> B
        B3[OpenTelemetry] --> B
    end

    subgraph ANALYZE
        C1[Noise Filter] --> C2[RCA + RAG]
        C2 --> C3[Confidence Score]
    end

    subgraph REVIEW
        R1[Runbook Validation] --> R2[Dynamic Risk<br/>6 factors]
        R2 --> R3[Self-Critique<br/>LLM optional]
        R3 --> R4{Decision}
    end

    subgraph ACT
        R4 -->|High conf + Low blast| D2[Auto-Execute]
        R4 -->|Medium risk| D3[Human Approval<br/>with Decision Brief]
        R4 -->|High risk / Low conf| D4[Escalate]
    end

    D2 --> E[Kubernetes MCP]
    D3 --> F[Slack Approval]
    D4 --> G[PagerDuty]
```

### Three Pillars

#### 1. Observe (Integrate with existing tools)
- **Metrics** — Prometheus
- **Logs** — Fluentd / ELK Stack
- **Traces** — OpenTelemetry

#### 2. Analyze (The Brain)
Six-step intelligence pipeline powered by LangGraph:

1. **Baselining** — Define normal behavior (ML)
2. **Detection** — Find anomalies against baselines (ML)
3. **Noise Management** — Filter false alarms, reduce alert fatigue (LLM)
4. **Correlation** — Correlate across metrics, logs, and traces (LLM)
5. **RCA** — Root cause analysis with natural language output (LLM + RAG over runbooks/Jira)
6. **Prediction** — Forecast issues from historical patterns (ML)

#### 3. Act (Alerting + Remediation)
- **Alerting** — Deduplicated, correlated alerts with RCA context and runbook steps attached
- **Remediation** — Confidence-based routing: auto-execute low-risk actions, human approval for high-risk

### Provider Pattern

All external data access goes through abstract interfaces. Mock implementations for demo, real implementations (MCP-backed) swap in independently post-funding.

```mermaid
graph LR
    subgraph Pipeline Nodes
        N1[RCA Node]
        N2[Noise Node]
        N5[Review Node]
        N3[Remediation Node]
        N4[Alert Node]
    end

    subgraph Interfaces
        P1[MetricsProvider]
        P2[LogsProvider]
        P3[KnowledgeProvider]
        P4[ActionsProvider]
        P5[AlertsProvider]
        P6[ContextProvider]
    end

    N1 --> P1 & P2 & P3
    N2 --> P3
    N5 --> P6
    N3 --> P4
    N4 --> P5

    subgraph "Mock (Demo)"
        M1[MockMetrics<br/><i>Generators</i>]
        M2[MockLogs<br/><i>Templates</i>]
        M3[MockKnowledge<br/><i>Keyword search</i>]
        M4[MockActions<br/><i>Log + simulate</i>]
        M5[MockAlerts<br/><i>Terminal output</i>]
        M6[MockContext<br/><i>Scenario config</i>]
    end

    subgraph "Production (Post-Funding)"
        R1[Prometheus MCP]
        R2[Elasticsearch MCP]
        R3[pgvector + MCP]
        R4[Kubernetes MCP]
        R5[Slack + PagerDuty MCP]
        R6[K8s + Incident DB]
    end

    P1 -.-> M1
    P2 -.-> M2
    P3 -.-> M3
    P4 -.-> M4
    P5 -.-> M5
    P6 -.-> M6

    P1 -.-> R1
    P2 -.-> R2
    P3 -.-> R3
    P4 -.-> R4
    P5 -.-> R5
    P6 -.-> R6

    style M1 fill:#69DB7C,color:#000
    style M2 fill:#69DB7C,color:#000
    style M3 fill:#69DB7C,color:#000
    style M4 fill:#69DB7C,color:#000
    style M5 fill:#69DB7C,color:#000
    style M6 fill:#69DB7C,color:#000
    style R1 fill:#4DABF7,color:#fff
    style R2 fill:#4DABF7,color:#fff
    style R3 fill:#4DABF7,color:#fff
    style R4 fill:#4DABF7,color:#fff
    style R5 fill:#4DABF7,color:#fff
    style R6 fill:#4DABF7,color:#fff
```

6 providers: `MetricsProvider`, `LogsProvider`, `KnowledgeProvider`, `ActionsProvider`, `AlertsProvider`, `ContextProvider`. Each independently replaceable — pipeline code never changes.

### LangGraph Pipeline

```mermaid
graph TD
    A[Intake<br/><i>Parse alarm, assign ID</i>] --> B[Noise Check<br/><i>Known issue? Maintenance?</i>]
    B -->|Not noise| C[RCA<br/><i>LLM + RAG over knowledge base</i>]
    B -->|Noise detected| G[Alert<br/><i>FYI notification</i>]
    C --> R[Review Agent<br/><i>Validate + Risk + Critique</i>]

    R --> R1[Step 1: Runbook Validation<br/><i>Does action match runbook?</i>]
    R1 --> R2[Step 2: Dynamic Risk<br/><i>6 factors: tier, time, deploy...</i>]
    R2 --> R3[Step 3: Self-Critique<br/><i>LLM reviews RCA - optional</i>]
    R3 --> R4{Step 4: Decision}

    R4 -->|conf ≥ 0.90 + low blast| E[Remediation<br/><i>Auto-execute</i>]
    R4 -->|medium risk| F[Human Approval<br/><i>+ Decision Brief</i>]
    R4 -->|high risk / low conf| H[Escalation<br/><i>PagerDuty</i>]
    E --> G
    F --> G
    H --> G

    style A fill:#4DABF7,color:#fff
    style B fill:#FFA94D,color:#fff
    style C fill:#FFA94D,color:#fff
    style R fill:#339AF0,color:#fff
    style R1 fill:#339AF0,color:#fff
    style R2 fill:#339AF0,color:#fff
    style R3 fill:#339AF0,color:#fff
    style R4 fill:#339AF0,color:#fff
    style E fill:#40C057,color:#fff
    style F fill:#FFA94D,color:#fff
    style H fill:#FF6B6B,color:#fff
    style G fill:#BE4BDB,color:#fff
```

### RAG Flow (Knowledge Retrieval)

```mermaid
graph TD
    A[Alert Context<br/><i>service + alertname + description</i>] --> B[Knowledge Search]

    subgraph Knowledge Base
        KB1[Runbooks<br/><i>8 markdown files</i>]
        KB2[Jira Tickets<br/><i>15 historical incidents</i>]
        KB3[Confluence Docs<br/><i>8 architecture + SOP pages</i>]
        KB4[Codebase<br/><i>service repos</i>]
    end

    B --> KB1 & KB2 & KB3 & KB4
    KB1 --> C[Ranked Results<br/><i>by relevance score</i>]
    KB2 --> C
    KB3 --> C
    KB4 --> C

    C --> D[Fetch Full Content<br/><i>runbook text, ticket details</i>]
    D --> E[Fetch Error Logs<br/><i>recent ERROR entries</i>]
    E --> F[Assemble LLM Context<br/><i>alert + runbook + tickets + logs</i>]
    F --> G[LLM Analysis<br/><i>ROOT_CAUSE + REMEDIATION + CONFIDENCE</i>]
    G --> H[Multi-Signal Scoring<br/><i>composite confidence</i>]

    style F fill:#FFA94D,color:#fff
    style G fill:#BE4BDB,color:#fff
    style H fill:#40C057,color:#fff
```

### Review Agent

The Review Agent sits between RCA and Remediation. It validates the recommended action, assesses dynamic risk, optionally critiques the RCA, and generates a Decision Brief when humans need to approve.

```mermaid
graph TD
    subgraph "Review Agent — 5 Steps"
        S1["Step 1: Runbook Validation
        Does the action match the runbook?
        Mismatch → -0.05 confidence"]

        S2["Step 2: Dynamic Risk Assessment
        6 factors evaluated:
        • Service tier (Tier 1 = +0.05)
        • Time of day (peak = +0.05)
        • Recent deploy (<2h = +0.08)
        • Change freeze (= force escalate)
        • Active incidents (≥3 = +0.05)
        • Failed retry (= +0.15)"]

        S3["Step 3: RCA Self-Critique (LLM)
        Only when confidence 0.70–0.93
        • Is confidence justified?
        • Alternative root causes?
        • Symptom vs root cause?"]

        S4{"Step 4: Decision
        Uses adjusted confidence
        + effective blast radius"}

        S5["Step 5: Decision Brief
        Summary, risks, evidence,
        contra-indicators, alternatives,
        recommendation, estimated TTR"]

        S1 --> S2 --> S3 --> S4
        S4 -->|human needed| S5
    end

    style S1 fill:#339AF0,color:#fff
    style S2 fill:#339AF0,color:#fff
    style S3 fill:#BE4BDB,color:#fff
    style S4 fill:#339AF0,color:#fff
    style S5 fill:#FFA94D,color:#fff
```

**Dynamic risk can upgrade blast radius** (low → medium → high) but never downgrade:
- Tier 1 service with any positive risk → at least "medium"
- Total risk delta > 0.10 → upgrade one level
- Change freeze → force "high" (escalation)

**Decision Brief** gives humans everything to decide fast:

| Field | Purpose |
|-------|---------|
| Summary | One-line: what happened + proposed action |
| Risk if act | What could go wrong if we execute |
| Risk if wait | What gets worse if we don't |
| Evidence for | Runbook, past incidents supporting action |
| Contra-indicators | Risk factors, critique findings, mismatches |
| Recommendation | Approve/deny with reasoning |
| Estimated TTR | From historical ticket resolution times |
| Alternatives | Rollback, investigate further, etc. |

### Multi-Signal Confidence Scoring

The RCA node produces a composite confidence score from 4 signals (not just LLM self-assessment). The Review Agent may then adjust it further based on critique and risk factors.

| Signal | Weight | Source |
|--------|--------|--------|
| RAG match quality | 30% | Keyword/cosine similarity from knowledge search |
| Historical success rate | 30% | Past remediation outcomes for this pattern |
| LLM assessment | 20% | LLM self-assessed confidence |
| Recency | 20% | Days since similar incident was resolved |

Decision matrix (after review adjustments):

```mermaid
quadrantChart
    title Confidence × Blast Radius Decision Matrix
    x-axis Low Blast Radius --> High Blast Radius
    y-axis Low Confidence --> High Confidence
    quadrant-1 Human Approval
    quadrant-2 Auto-Execute
    quadrant-3 Human Approval
    quadrant-4 Escalate
```

### MCP Integration (Production)

For production, MCP servers provide uniform data access:

| Server | Purpose | Status |
|--------|---------|--------|
| Atlassian MCP | Jira + Confluence queries | Custom build needed |
| GitHub MCP | Codebase context | Off-the-shelf |
| Prometheus MCP | Live metrics | Off-the-shelf |
| Elasticsearch MCP | Log search | Off-the-shelf |
| Kubernetes MCP | Pod restart, scaling | Off-the-shelf |
| Slack MCP | Alerts + approval buttons | Off-the-shelf |
| PagerDuty MCP | Escalation | Custom build needed |

Batch ingestion (Confluence, Jira, GitHub → pgvector) uses direct API clients, not MCP.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, FastAPI |
| Frontend | React, TypeScript |
| Database | PostgreSQL (TimescaleDB + pgvector) |
| Agent Orchestration | LangGraph |
| Task Queue | arq (async, Redis-backed) |
| Embeddings | pgvector (RAG over runbooks and Jira tickets) |
| Remediation | MCP (Model Context Protocol) servers |

## Project Structure

```
reflex/
├── demo.py                          # CLI demo entry point
├── streamlit_demo.py                # Visual demo (Streamlit)
├── pyproject.toml
├── backend/
│   └── app/
│       ├── providers/               # Abstract interfaces (the replaceable seam)
│       │   ├── base.py              # 6 Protocol definitions
│       │   └── factory.py           # create_providers(mode="mock"|"production")
│       └── agents/
│           ├── state.py             # LangGraph AgentState
│           ├── graph.py             # StateGraph wiring
│           ├── scoring.py           # Multi-signal confidence scoring
│           ├── risk.py              # Dynamic risk assessment (6 factors)
│           ├── models.py            # RiskFactor, RiskAssessment, DecisionBrief
│           └── nodes/
│               ├── intake.py        # Parse alarm, assign incident ID
│               ├── noise.py         # Filter known issues
│               ├── rca.py           # LLM + RAG root cause analysis
│               ├── review.py        # Review Agent (validate, risk, critique, decide)
│               ├── remediation.py   # Execute via ActionsProvider
│               └── alert.py         # Notify via AlertsProvider
├── mock/
│   ├── config.py                    # ShopFast service definitions (7 microservices)
│   ├── generators/                  # Metrics, logs, trace generators
│   ├── providers/                   # Mock implementations of all 6 providers
│   │   ├── metrics.py               # MockMetricsProvider (generators)
│   │   ├── logs.py                  # MockLogsProvider (templates)
│   │   ├── knowledge.py             # MockKnowledgeProvider (keyword search)
│   │   ├── actions.py               # MockActionsProvider (log + simulate)
│   │   ├── alerts.py                # MockAlertsProvider (terminal + file)
│   │   ├── context.py               # MockContextProvider (scenario config)
│   │   └── mock_llm.py              # MockLLM (pre-built RCA + critique responses)
│   ├── scenarios/                   # 5 incident scenarios
│   └── data/
│       ├── runbooks/                # 8 markdown runbooks
│       ├── jira_tickets.json        # 15 historical incident tickets
│       └── confluence_pages/        # 8 architecture + SOP docs
└── shared/
    └── openapi.yaml
```

## Mock System: ShopFast E-Commerce

The demo uses a fictional 7-microservice e-commerce platform:

```mermaid
graph TD
    U[User] --> GW[api-gateway<br/><i>Python/FastAPI</i>]

    GW --> CAT[catalog-service<br/><i>Go</i>]
    GW --> CART[cart-service<br/><i>Node.js/Redis</i>]
    GW --> ORD[order-service<br/><i>Python/FastAPI</i>]

    CAT --> INV[inventory-service<br/><i>Go/PostgreSQL</i>]
    CART --> CAT
    ORD --> PAY[payment-service<br/><i>Java/Spring Boot</i>]
    ORD --> INV
    ORD --> NOTIF[notification-service<br/><i>Python/FastAPI</i>]
    PAY --> EXT[External Payment Gateway]

    style GW fill:#4DABF7,color:#fff
    style CAT fill:#69DB7C,color:#000
    style CART fill:#FFA94D,color:#000
    style ORD fill:#4DABF7,color:#fff
    style PAY fill:#FF6B6B,color:#fff
    style INV fill:#69DB7C,color:#000
    style NOTIF fill:#4DABF7,color:#fff
    style EXT fill:#888,color:#fff
```

Knowledge base: 8 runbooks with real kubectl/SQL commands, 15 Jira tickets with full resolution timelines, 8 Confluence pages covering architecture, SOPs, and postmortems.

## Incremental Roadmap

```mermaid
gantt
    title Reflex Incremental Roadmap
    dateFormat YYYY-MM-DD
    axisFormat %b

    section Increment 1
    MVP Demo (mock providers, LangGraph pipeline)       :done,    i1, 2026-03-01, 2026-03-31

    section Increment 2
    pgvector knowledge base + real embeddings           :active,  i2, 2026-04-01, 2026-05-15
    Direct API ingestion (Confluence, Jira, GitHub)     :         i2b, 2026-04-15, 2026-05-15

    section Increment 3
    MCP servers (Prometheus, ES, K8s, Slack)             :         i3, 2026-05-15, 2026-07-01
    Human approval flow (LangGraph interrupt)            :         i3b, 2026-06-01, 2026-07-01

    section Increment 4
    ML baselining + anomaly detection                    :         i4, 2026-07-01, 2026-08-15
    Closed-loop: verify fix → update knowledge base      :         i4b, 2026-07-15, 2026-08-15
```

### Increment 1 — MVP Demo (current)
- Provider pattern with mock implementations
- LangGraph pipeline (Intake → Noise → RCA → Action Router → Remediation → Alert)
- 5 incident scenarios with mock data generators
- CLI + Streamlit demos

### Increment 2 — Real Knowledge Base
- PostgreSQL + pgvector for embeddings
- Direct API ingestion: Confluence, Jira, GitHub, runbooks → chunk → embed → pgvector
- Replace MockKnowledgeProvider with PgVectorKnowledgeProvider

### Increment 3 — Real Observability + Remediation
- MCP servers: Prometheus, Elasticsearch, Kubernetes, Slack
- Custom MCP: Atlassian, PagerDuty
- Replace remaining mock providers with MCP-backed providers
- Human approval flow (Slack buttons + LangGraph interrupt)

### Increment 4 — ML + Full Pipeline
- ML baselining and anomaly detection
- Cross-service correlation
- Prediction / forecasting
- Closed-loop: verify fix → feed back into knowledge base

## Use Cases

1. **Intelligent Alert Triage** — Filter noise, correlate 100 alerts into 3 real incidents
2. **Automated Root Cause Analysis** — RCA in seconds via RAG over runbooks, Jira, Confluence, codebase
3. **Self-Healing Infrastructure** — Auto-remediate known low-risk patterns via Kubernetes MCP
4. **Knowledge Capture & Retention** — Institutional knowledge survives team turnover
5. **MTTR Reduction** — From ~30 min (manual) to <10 sec (automated)
6. **Proactive Incident Prevention** — Prediction node spots trends before they become outages
7. **On-Call Engineer Augmentation** — Full context at 3 AM: root cause, similar incidents, runbook steps
8. **Alert Fatigue Elimination** — Noise management + correlation reduces alert volume 60-80%
9. **Cross-Service Incident Correlation** — One unified incident instead of separate tickets per team
10. **Compliance & Audit Trail** — Every action logged with full evidence chain

## Architecture Details

See [architecture plan](.claude/plans/precious-jingling-stroustrup.md) for MCP integration design, async worker architecture, error handling, and observability.

See [MVP demo plan](.claude/plans/mvp-mock-data.md) for mock data design, scenario details, and provider pattern.
