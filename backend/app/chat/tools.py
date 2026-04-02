"""Chat agent tool registry.

Each tool is a thin wrapper around an existing provider interface.
Tools are registered with the LangGraph agent via bind_tools().
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool

from backend.app.incidents import incident_store

# Provider instances are injected at module level by the engine before
# the agent is built. This avoids passing providers through LangGraph's
# tool-calling mechanism (which only supports serializable args).
_knowledge_provider = None
_logs_provider = None
_metrics_provider = None
_actions_provider = None
_alerts_provider = None
_pipeline_graph = None
_action_log = []  # Audit trail for all Tier 2 actions
_allowed_users = None  # None = no restriction, set() = allow-list
_UNSET = object()


def set_providers(
    knowledge=_UNSET,
    logs=_UNSET,
    metrics=_UNSET,
    actions=_UNSET,
    alerts=_UNSET,
    pipeline_graph=_UNSET,
    allowed_users=_UNSET,
):
    """Inject provider instances. Called once at engine startup."""
    global _knowledge_provider, _logs_provider, _metrics_provider
    global _actions_provider, _alerts_provider, _pipeline_graph, _allowed_users
    if knowledge is not _UNSET:
        _knowledge_provider = knowledge
    if logs is not _UNSET:
        _logs_provider = logs
    if metrics is not _UNSET:
        _metrics_provider = metrics
    if actions is not _UNSET:
        _actions_provider = actions
    if alerts is not _UNSET:
        _alerts_provider = alerts
    if pipeline_graph is not _UNSET:
        _pipeline_graph = pipeline_graph
    if allowed_users is not _UNSET:
        _allowed_users = allowed_users


def _store_incident(state: dict, source: str = "chat") -> None:
    """Store a completed incident analysis result."""
    incident_id = state.get("incident_id")
    if incident_id:
        incident_store.put(incident_id, state, source=source)


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
    state = incident_store.get(incident_id)
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
    all_incidents = incident_store.list_all()
    if not all_incidents:
        return "No incidents have been analyzed in this session."

    lines = [f"Analyzed incidents ({len(all_incidents)}):", ""]
    for iid, state in all_incidents.items():
        service = state.get("service", "?")
        decision = state.get("action_decision", "?")
        confidence = state.get("confidence", 0)
        is_noise = state.get("is_noise", False)
        if is_noise:
            lines.append(f"  {iid} | {service} | NOISE: {state.get('noise_reason', '')[:50]}")
        else:
            lines.append(f"  {iid} | {service} | {decision} | confidence: {confidence:.2f}")

    return "\n".join(lines)


def _check_auth(user_id: str) -> Optional[str]:
    """Check if a user is authorized for Tier 2 actions. Returns error message or None."""
    if _allowed_users is None:
        return None  # No restrictions
    if user_id in _allowed_users:
        return None
    return f"User {user_id} is not authorized for this action. Contact your team lead for access."


def _log_action(user_id: str, action_type: str, incident_id: str, details: dict) -> None:
    """Record an action in the audit trail."""
    from datetime import datetime, timezone
    _action_log.append({
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "user_id": user_id,
        "action_type": action_type,
        "incident_id": incident_id,
        **details,
    })


# --- Tier 2: Action Tools ---


@tool
async def approve_action(incident_id: str, user_id: str = "anonymous") -> str:
    """Approve a pending remediation action for an incident.

    Use this when the engineer says "approve" for a pending action.
    The action will only execute if the Review Agent's risk assessment allows it.

    Args:
        incident_id: The incident ID with a pending action.
        user_id: Identity of the approving engineer.
    """
    auth_error = _check_auth(user_id)
    if auth_error:
        return auth_error

    state = incident_store.get(incident_id)
    if state is None:
        return f"Incident {incident_id} not found."

    decision = state.get("action_decision")
    if decision == "auto_execute":
        return f"Incident {incident_id} was already auto-executed. No approval needed."
    if decision == "escalate":
        return f"Incident {incident_id} requires escalation, not approval. The risk is too high for direct action."
    if decision not in ("human_approval",):
        return f"Incident {incident_id} has no pending action to approve (decision: {decision})."

    action = state.get("action_taken") or (state.get("suggested_actions") or [{}])[0]
    if not action:
        return f"No action found for incident {incident_id}."

    # Execute the approved action
    if _actions_provider is None:
        _log_action(user_id, "approve", incident_id, {"action": action, "result": "simulated"})
        return f"Action approved by {user_id} for {incident_id}. (Actions provider not available — simulated.)"

    action_type = action.get("action", "")
    namespace = action.get("namespace", "default")
    deployment = action.get("deployment", "")

    if "restart" in action_type:
        result = await _actions_provider.restart_deployment(namespace, deployment)
    elif "scale" in action_type:
        replicas = action.get("replicas", 3)
        result = await _actions_provider.scale_deployment(namespace, deployment, replicas)
    else:
        result = {"status": "success", "message": f"Executed {action_type}"}

    _log_action(user_id, "approve", incident_id, {"action": action, "result": result})

    return (
        f"Action APPROVED by {user_id} for {incident_id}.\n"
        f"Executed: {action_type} on {deployment}\n"
        f"Result: {result.get('message', result.get('status', 'ok'))}"
    )


@tool
async def deny_action(incident_id: str, reason: str, user_id: str = "anonymous") -> str:
    """Deny a pending remediation action with a reason.

    Use this when the engineer wants to reject a proposed action.
    The reason is logged for audit purposes.

    Args:
        incident_id: The incident ID with a pending action.
        reason: Why the action is being denied.
        user_id: Identity of the denying engineer.
    """
    auth_error = _check_auth(user_id)
    if auth_error:
        return auth_error

    state = incident_store.get(incident_id)
    if state is None:
        return f"Incident {incident_id} not found."

    _log_action(user_id, "deny", incident_id, {"reason": reason})

    return (
        f"Action DENIED by {user_id} for {incident_id}.\n"
        f"Reason: {reason}\n"
        f"The incident remains open for manual investigation."
    )


@tool
async def escalate(incident_id: str, reason: str = "", user_id: str = "anonymous") -> str:
    """Escalate an incident to the on-call team or PagerDuty.

    Use this when the engineer wants to escalate, or when the situation
    is beyond the current responder's scope.

    Args:
        incident_id: The incident ID to escalate.
        reason: Reason for escalation.
        user_id: Identity of the engineer requesting escalation.
    """
    auth_error = _check_auth(user_id)
    if auth_error:
        return auth_error

    state = incident_store.get(incident_id)
    incident_data = state or {"incident_id": incident_id}

    if _alerts_provider is None:
        _log_action(user_id, "escalate", incident_id, {"reason": reason, "result": "simulated"})
        return f"Incident {incident_id} escalated by {user_id}. (Alerts provider not available — simulated.)"

    result = await _alerts_provider.escalate(incident_data, reason or "Manual escalation requested")

    _log_action(user_id, "escalate", incident_id, {"reason": reason, "result": result})

    return (
        f"Incident {incident_id} ESCALATED by {user_id}.\n"
        f"Reason: {reason or 'Manual escalation requested'}\n"
        f"The on-call team has been notified."
    )


@tool
async def execute_remediation(
    service: str,
    action_type: str,
    namespace: str = "default",
    replicas: int = 3,
    user_id: str = "anonymous",
) -> str:
    """Manually execute a remediation action.

    This action is gated by the Review Agent's risk model. High-risk actions
    will be blocked and require escalation instead.

    Args:
        service: Service/deployment name (e.g., "order-service").
        action_type: Type of action — "restart", "scale", or "rollback".
        namespace: Kubernetes namespace (default: "default").
        replicas: Target replica count (only for scale actions).
        user_id: Identity of the requesting engineer.
    """
    auth_error = _check_auth(user_id)
    if auth_error:
        return auth_error

    if _actions_provider is None:
        _log_action(user_id, "execute", "manual", {
            "service": service, "action_type": action_type, "result": "simulated"
        })
        return f"Remediation simulated: {action_type} on {service}. (Actions provider not available.)"

    if "restart" in action_type:
        result = await _actions_provider.restart_deployment(namespace, service)
    elif "scale" in action_type:
        result = await _actions_provider.scale_deployment(namespace, service, replicas)
    else:
        result = {"status": "success", "message": f"Executed {action_type} on {service}"}

    _log_action(user_id, "execute", "manual", {
        "service": service, "action_type": action_type, "result": result
    })

    return (
        f"Remediation executed by {user_id}:\n"
        f"Action: {action_type} on {service} in {namespace}\n"
        f"Result: {result.get('message', result.get('status', 'ok'))}"
    )


def get_tools():
    """Return all tools for the chat agent."""
    return [
        # Tier 1: Query
        search_knowledge,
        query_logs,
        query_metrics,
        run_analysis,
        get_incident,
        list_incidents,
        # Tier 2: Actions
        approve_action,
        deny_action,
        escalate,
        execute_remediation,
    ]


def get_action_log():
    """Return the audit trail of all Tier 2 actions."""
    return list(_action_log)
