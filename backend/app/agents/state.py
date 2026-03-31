"""LangGraph AgentState — shared state flowing through all pipeline nodes."""

from typing import List, Optional, TypedDict


class AgentState(TypedDict, total=False):
    # Input — set by intake node
    alarm: dict  # normalized alert payload
    incident_id: str
    service: str

    # Noise management
    is_noise: bool
    noise_reason: Optional[str]

    # Knowledge retrieval
    matching_runbook: Optional[str]  # runbook content
    matching_runbook_id: Optional[str]
    matching_tickets: List[dict]
    matching_docs: List[dict]

    # Logs context
    recent_error_logs: List[dict]

    # RCA
    root_cause: Optional[str]
    confidence: float
    confidence_signals: dict
    evidence: List[str]
    suggested_actions: List[dict]

    # Action routing
    action_decision: str  # "auto_execute", "human_approval", "escalate"
    blast_radius: str

    # Remediation
    action_taken: Optional[dict]
    action_result: Optional[dict]

    # Alert
    alert_sent: bool
