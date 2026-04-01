"""Data models for the Review Agent — risk assessment and decision briefs."""

from __future__ import annotations

from typing import List

from dataclasses import dataclass, field, asdict


@dataclass
class RiskFactor:
    name: str  # e.g. "service_tier", "peak_hours", "recent_deploy"
    value: str  # e.g. "tier_1", "true", "deployed 45min ago"
    risk_delta: float  # how much this shifts risk (-0.1 to +0.1)
    explanation: str  # human-readable reason

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskAssessment:
    base_blast_radius: str  # from static config
    effective_blast_radius: str  # after dynamic factors (may be upgraded)
    risk_factors: List[RiskFactor]
    total_risk_adjustment: float
    service_tier: int  # 1-3

    def to_dict(self) -> dict:
        return {
            "base_blast_radius": self.base_blast_radius,
            "effective_blast_radius": self.effective_blast_radius,
            "risk_factors": [rf.to_dict() for rf in self.risk_factors],
            "total_risk_adjustment": self.total_risk_adjustment,
            "service_tier": self.service_tier,
        }


@dataclass
class DecisionBrief:
    summary: str  # one-line: what happened + proposed action
    risk_if_act: str  # what could go wrong if we execute
    risk_if_wait: str  # what could go wrong if we don't
    evidence_for: List[str]  # supports this action
    evidence_against: List[str]  # contra-indicators
    recommendation: str  # "approve" or "deny" with reasoning
    estimated_ttr_minutes: int  # from historical tickets
    alternatives: List[dict] = field(default_factory=list)  # fallback actions

    def to_dict(self) -> dict:
        return asdict(self)
