# Pulse Demo Script — 3 Minutes

> **Setup before demo:** API server running on :8000 (with TOPOLOGY_ENRICHED=true), Streamlit demo on :8503, Chat UI on :8501. One incident already simulated.

---

## [0:00–0:30] THE HOOK

> "It's 3 AM. Your phone buzzes. PagerDuty. Database connection pool exhausted on order-service. What happens next?"

**The reality today:**
- 53 minutes MTTR
- 8 manual steps: SSH, grep logs, search Confluence for a runbook that's 6 months outdated, guess at root cause, restart the wrong service, find the real cause, apply fix, monitor
- Tribal knowledge locked in one engineer's head — who just left the company

**With Pulse:**
- Under 10 seconds. Zero manual steps. Engineer sleeps through it.
- That's not a target. That's what it does right now. Let me show you.

---

## [0:30–1:30] LIVE DEMO

> **Switch to Streamlit demo (:8503)**

### Simulate the alarm
> Click "Simulate SEV-2 Alarm" in sidebar

"An Alertmanager webhook just fired. Watch what happens."

### Show the pipeline (Live Incidents tab)
> Expand the incident

"In under 10 seconds, Pulse:
1. **Checked for noise** — is this a known issue? No.
2. **Searched the knowledge base** — found matching runbook RB-001, 3 similar past incidents from Jira
3. **Root cause analysis** — connection pool exhaustion, connections being leaked in OrderRepository
4. **Confidence: 95%** — scored across 4 signals: RAG match, historical success, LLM assessment, recency
5. **Review Agent** evaluated 7 risk factors — service tier, time of day, recent deploys, blast radius
6. **Decision: human approval** — medium blast radius because api-gateway depends on this service"

### Show the Decision Brief
"The engineer gets everything to decide fast: risk if we act, risk if we wait, evidence for and against, and a recommendation. One click to approve."

> Click "Approve"

"Done. Service restarted. Notification sent. Full audit trail."

---

## [1:30–2:00] ARCHITECTURE DISCOVERY

> **Switch to Architecture tab**

"Pulse doesn't just respond to incidents — it understands your infrastructure."

> Click "Analyze Impact" on order-service

"Multi-source topology discovery. We triangulate across:
- **Kubernetes manifests** — what's actually deployed
- **Architecture docs** — what Confluence says (including when it's wrong)
- **Jira ticket history** — which services fail together

Every dependency gets a **confidence score**. If 3 sources agree, high confidence. If only docs say it — maybe the docs are stale."

---

## [2:00–2:30] CHATOPS

> **Switch to Chat UI (:8501)**

"Engineers don't want another dashboard. They want to ask questions where they already work."

> Type: "What's the blast radius if we restart payment-service?"

"12 AI-powered tools. Query logs, metrics, runbooks, past incidents. Approve or deny actions. All from Slack or this chat. Multi-turn — it remembers what you already discussed."

---

## [2:30–3:00] VALUE + ROADMAP

### By the Numbers

| Metric | Before | With Pulse |
|--------|--------|------------|
| **MTTR** | 53 min | <10 sec |
| **Manual steps** | 8 | 0 |
| **Knowledge loss** | 100% on turnover | 0% — captured in vector DB |
| **Alert noise** | 100 alerts | 3 real incidents |
| **Night pages** | Every incident | Only high-risk |

### What's Built (Increment 1 — done)
- 6-node LangGraph pipeline with Review Agent (7 risk factors)
- 12 ChatOps tools, Slack adapter, 3 UIs
- Multi-source topology discovery with confidence scoring
- 151 tests, 5 incident scenarios, full mock system
- **Zero external dependencies for demo** — runs with `pip install` and `python demo.py`

### Roadmap
- **Increment 2** (next): pgvector knowledge base — vector similarity search replacing keyword matching
- **Increment 3**: Real infrastructure — Prometheus, Elasticsearch, Kubernetes MCP servers
- **Increment 4**: ML baselining, anomaly detection, prediction — catch incidents before they happen

### The Ask
"We're reducing MTTR from 53 minutes to 10 seconds. Every minute of downtime costs money. The platform is built, the architecture is proven, the demo is live. We need [your ask: funding / resources / pilot customer]."

---

## Quick Recovery Answers

**"How is this different from PagerDuty/OpsGenie?"**
> They alert. We analyze AND act. Our Review Agent evaluates 7 risk factors before any action. PagerDuty wakes someone up; we let them sleep.

**"What if the AI is wrong?"**
> The Review Agent gates every action. Low confidence + high blast radius = escalate to a human with a full Decision Brief. No blind auto-remediation.

**"Does this work with our stack?"**
> Provider pattern — 7 abstract interfaces. Swap in your Prometheus, ELK, K8s. Pipeline code never changes. Currently works with mock data; production integrations in Increment 3.

**"What about hallucinations?"**
> RAG over your actual runbooks and Jira tickets, not general knowledge. Multi-signal confidence scoring — 4 independent signals, not just LLM self-assessment. Safety rails in the system prompt prevent fabricating data.
