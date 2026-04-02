"""Chat agent tool registry.

Each tool is a thin wrapper around an existing provider interface.
Tools are registered with the LangGraph agent via bind_tools().
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

# Provider instances are injected at module level by the engine before
# the agent is built. This avoids passing providers through LangGraph's
# tool-calling mechanism (which only supports serializable args).
_knowledge_provider = None
_logs_provider = None
_metrics_provider = None
_pipeline_graph = None
_incidents_store = {}  # In-memory incident store (replaced by DB in production)
_UNSET = object()


def set_providers(
    knowledge=_UNSET,
    logs=_UNSET,
    metrics=_UNSET,
    pipeline_graph=_UNSET,
):
    """Inject provider instances. Called once at engine startup."""
    global _knowledge_provider, _logs_provider, _metrics_provider, _pipeline_graph
    if knowledge is not _UNSET:
        _knowledge_provider = knowledge
    if logs is not _UNSET:
        _logs_provider = logs
    if metrics is not _UNSET:
        _metrics_provider = metrics
    if pipeline_graph is not _UNSET:
        _pipeline_graph = pipeline_graph


def _store_incident(state: dict) -> None:
    """Store a completed incident analysis result."""
    incident_id = state.get("incident_id")
    if incident_id:
        _incidents_store[incident_id] = state


# --- Tier 1: Query Tools ---


@tool
async def search_knowledge(
    query: str,
    source_type: Optional[str] = None,
    limit: int = 5,
) -> str:
    """Search the knowledge base for runbooks, Jira tickets, and Confluence docs.

    Use this when the user asks about incidents, runbooks, procedures,
    past tickets, or operational knowledge.

    Args:
        query: Search query describing what to find.
        source_type: Optional filter — "runbook", "jira", or "confluence".
        limit: Max results to return (default 5).
    """
    if _knowledge_provider is None:
        return "Knowledge provider not available."

    source_types = [source_type] if source_type else None
    results = await _knowledge_provider.search_similar(
        query=query, source_types=source_types, limit=limit
    )

    if not results:
        return "No matching knowledge found."

    lines = []
    for r in results:
        lines.append(
            f"[{r['source_type'].upper()}] {r['source_id']}: {r['title']} "
            f"(score: {r['score']:.2f})"
        )
        content_preview = r.get("content", "")[:200]
        if content_preview:
            lines.append(f"  {content_preview}")
        lines.append("")

    return "\n".join(lines)


@tool
async def query_logs(
    service: str,
    level: Optional[str] = None,
    message_contains: Optional[str] = None,
    limit: int = 20,
) -> str:
    """Search recent logs for a service.

    Use this when the user asks about errors, log patterns, or wants to
    see recent logs for a specific service.

    Args:
        service: Service name (e.g., "order-service", "payment-service").
        level: Log level filter — "ERROR", "WARN", "INFO", "DEBUG".
        message_contains: Text to search for in log messages.
        limit: Max log entries to return (default 20).
    """
    if _logs_provider is None:
        return "Logs provider not available."

    entries = await _logs_provider.search(
        service=service,
        level=level,
        message_contains=message_contains,
        limit=limit,
    )

    if not entries:
        return f"No logs found for {service}" + (f" with level={level}" if level else "") + "."

    lines = [f"Found {len(entries)} log entries for {service}:", ""]
    for e in entries:
        ts = e.get("timestamp", "")
        lvl = e.get("level", "?")
        msg = e.get("message", "")[:150]
        svc = e.get("service", service)
        lines.append(f"[{ts}] {lvl} {svc}: {msg}")

    return "\n".join(lines)


@tool
async def query_metrics(
    metric: str,
    service: str,
    time: Optional[str] = None,
) -> str:
    """Query a metric value for a service at a point in time.

    Use this when the user asks about performance, resource usage,
    error rates, latency, or any numeric metric.

    Args:
        metric: Metric name (e.g., "http_requests_total", "process_cpu_seconds", "db_connections_active").
        service: Service name to query metrics for.
        time: Optional timestamp (ISO 8601 or Unix). Defaults to now.
    """
    if _metrics_provider is None:
        return "Metrics provider not available."

    result = await _metrics_provider.query(
        metric=metric,
        labels={"service": service},
        time=time,
    )

    data = result.get("data", {})
    results = data.get("result", [])

    if not results:
        return f"No data found for metric '{metric}' on {service}."

    lines = [f"Metric: {metric} for {service}", ""]
    for r in results:
        labels = r.get("metric", {})
        value = r.get("value", [None, "N/A"])
        ts = value[0] if len(value) > 0 else "?"
        val = value[1] if len(value) > 1 else "N/A"
        label_str = ", ".join(f"{k}={v}" for k, v in labels.items() if k != "__name__")
        lines.append(f"  {label_str}: {val} (at {ts})")

    return "\n".join(lines)


@tool
async def run_analysis(
    service: str,
    alert_name: Optional[str] = None,
) -> str:
    """Run the full Reflex analysis pipeline for a service.

    Use this when the user wants a complete incident analysis including
    noise detection, root cause analysis, risk assessment, and remediation
    recommendation.

    Args:
        service: Service name to analyze (e.g., "order-service").
        alert_name: Optional alert name that triggered the analysis.
    """
    if _pipeline_graph is None:
        return "Analysis pipeline not available."

    alarm = {
        "labels": {
            "alertname": alert_name or "ManualAnalysis",
            "service": service,
            "severity": "warning",
        },
        "annotations": {
            "description": f"Manual analysis requested for {service}",
        },
    }

    final_state = {}
    async for event in _pipeline_graph.astream({"alarm": alarm}):
        for _node_name, node_state in event.items():
            final_state.update(node_state)

    # Store the incident for later retrieval
    _store_incident(final_state)

    # Format summary
    lines = [
        f"Analysis complete for {service}",
        f"Incident ID: {final_state.get('incident_id', 'N/A')}",
        "",
    ]

    if final_state.get("is_noise"):
        lines.append(f"NOISE DETECTED: {final_state.get('noise_reason', '')}")
        return "\n".join(lines)

    root_cause = final_state.get("root_cause", "Unknown")
    confidence = final_state.get("confidence", 0)
    decision = final_state.get("action_decision", "N/A")
    blast = final_state.get("blast_radius", "N/A")
    evidence = final_state.get("evidence", [])
    actions = final_state.get("suggested_actions", [])

    lines.extend([
        f"Root Cause: {root_cause}",
        f"Confidence: {confidence:.2f}",
        f"Blast Radius: {blast}",
        f"Decision: {decision}",
        "",
        f"Evidence: {', '.join(evidence[:5])}",
    ])

    if actions:
        lines.append("")
        lines.append("Suggested Actions:")
        for a in actions[:3]:
            lines.append(f"  - {a.get('action', '')}: {a.get('deployment', '')} in {a.get('namespace', '')}")

    brief = final_state.get("decision_brief")
    if brief:
        lines.extend([
            "",
            "Decision Brief:",
            f"  Summary: {brief.get('summary', '')}",
            f"  Risk if act: {brief.get('risk_if_act', '')}",
            f"  Risk if wait: {brief.get('risk_if_wait', '')}",
            f"  Recommendation: {brief.get('recommendation', '')}",
        ])

    return "\n".join(lines)


@tool
async def get_incident(incident_id: str) -> str:
    """Get details of a specific incident by ID.

    Use this when the user asks about a specific incident like "tell me about INC-abc123".

    Args:
        incident_id: The incident ID (e.g., "INC-a1b2c3d4").
    """
    state = _incidents_store.get(incident_id)
    if state is None:
        return f"Incident {incident_id} not found. It may not have been analyzed in this session."

    lines = [
        f"Incident: {incident_id}",
        f"Service: {state.get('service', 'N/A')}",
        f"Is Noise: {state.get('is_noise', False)}",
    ]

    if not state.get("is_noise"):
        lines.extend([
            f"Root Cause: {state.get('root_cause', 'N/A')}",
            f"Confidence: {state.get('confidence', 0):.2f}",
            f"Decision: {state.get('action_decision', 'N/A')}",
            f"Blast Radius: {state.get('blast_radius', 'N/A')}",
            f"Evidence: {', '.join(state.get('evidence', [])[:5])}",
        ])

        brief = state.get("decision_brief")
        if brief:
            lines.append(f"Brief: {brief.get('summary', '')}")

    return "\n".join(lines)


@tool
async def list_incidents() -> str:
    """List all incidents analyzed in this session.

    Use this when the user asks about recent or active incidents.
    """
    if not _incidents_store:
        return "No incidents have been analyzed in this session."

    lines = [f"Analyzed incidents ({len(_incidents_store)}):", ""]
    for iid, state in _incidents_store.items():
        service = state.get("service", "?")
        decision = state.get("action_decision", "?")
        confidence = state.get("confidence", 0)
        is_noise = state.get("is_noise", False)
        if is_noise:
            lines.append(f"  {iid} | {service} | NOISE: {state.get('noise_reason', '')[:50]}")
        else:
            lines.append(f"  {iid} | {service} | {decision} | confidence: {confidence:.2f}")

    return "\n".join(lines)


def get_tools():
    """Return all tools for the chat agent."""
    return [
        search_knowledge,
        query_logs,
        query_metrics,
        run_analysis,
        get_incident,
        list_incidents,
    ]
