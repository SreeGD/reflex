"""Multi-signal confidence scoring.

Composite score from objective signals (RAG match, pattern match, recency,
historical success) plus LLM self-assessment. Objective signals dominate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ConfidenceSignals:
    rag_match_score: float  # best keyword/cosine score from knowledge search (0-1)
    pattern_match: bool  # exact match to known incident pattern?
    recency_days: int | None  # days since similar incident resolved
    historical_success_rate: float  # success rate of this remediation (0-1)
    llm_assessment: float  # LLM self-assessed confidence (0-1)


def compute_confidence(signals: ConfidenceSignals) -> float:
    """Weighted composite score. Objective signals dominate."""
    # Exact pattern match with recent success = high confidence
    if signals.pattern_match and signals.recency_days is not None and signals.recency_days < 90:
        if signals.historical_success_rate > 0.8:
            return 0.95

    weights = {
        "rag_match": 0.30,
        "historical": 0.30,
        "llm": 0.20,
        "recency": 0.20,
    }

    recency_score = max(0, 1 - (signals.recency_days or 365) / 365)

    score = (
        weights["rag_match"] * min(1.0, signals.rag_match_score)
        + weights["historical"] * signals.historical_success_rate
        + weights["llm"] * signals.llm_assessment
        + weights["recency"] * recency_score
    )
    return round(min(1.0, score), 3)
