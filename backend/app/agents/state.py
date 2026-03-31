"""LangGraph AgentState — shared state flowing through all pipeline nodes."""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    # Input — set by intake node
    alarm: dict  # normalized alert payload
    incident_id: str
    service: str

    # Noise management
    is_noise: bool
    noise_reason: str | None

    # Knowledge retrieval
    matching_runbook: str | None  # runbook content
    matching_runbook_id: str | None
    matching_tickets: list[dict]
    matching_docs: list[dict]

    # Logs context
    recent_error_logs: list[dict]

    # RCA
    root_cause: str | None
    confidence: float
    confidence_signals: dict
    evidence: list[str]
    suggested_actions: list[dict]

    # Action routing
    action_decision: str  # "auto_execute", "human_approval", "escalate"
    blast_radius: str

    # Remediation
    action_taken: dict | None
    action_result: dict | None

    # Alert
    alert_sent: bool
