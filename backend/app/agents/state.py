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

    # Review Agent
    action_decision: str  # "auto_execute", "human_approval", "escalate"
    blast_radius: str  # effective blast radius (after dynamic assessment)
    adjusted_confidence: float  # confidence after review adjustments
    risk_assessment: dict  # RiskAssessment serialized
    decision_brief: dict | None  # DecisionBrief (only when human needed)
    review_critique: dict | None  # RCA self-critique results
    review_adjustments: list[str]  # human-readable log of what review changed

    # Remediation
    action_taken: Optional[dict]
    action_result: Optional[dict]

    # Alert
    alert_sent: bool
