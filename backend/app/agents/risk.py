"""Dynamic risk assessment — pure Python, no LLM.

Evaluates 6 risk factors and optionally upgrades blast radius.
Risk factors can upgrade blast (low→medium→high) but never downgrade.
"""

from __future__ import annotations

from typing import List, Dict

from .models import RiskAssessment, RiskFactor

_SHOPFAST_TIERS: Dict[str, int] = {
    "payment-service": 1,
    "order-service": 1,
    "api-gateway": 1,
    "cart-service": 2,
    "catalog-service": 2,
    "inventory-service": 2,
    "notification-service": 3,
}

_HEALTHCARE_TIERS: Dict[str, int] = {
    "patient-service": 1,
    "billing-service": 1,
    "ehr-gateway": 1,
    "medication-service": 2,
    "scheduling-service": 2,
    "pharmacy-service": 2,
    "alert-service": 3,
}


def _get_service_tiers() -> Dict[str, int]:
    try:
        from mock.config import get_active_system
        if get_active_system() == "healthcare":
            return _HEALTHCARE_TIERS
    except Exception:
        pass
    return _SHOPFAST_TIERS


SERVICE_TIERS = _get_service_tiers()

BLAST_RADIUS_MAP: Dict[str, str] = {
    "restart_deployment": "low",
    "clear_cache": "low",
    "flush_queue": "low",
    "rollback_deploy": "medium",
    "scale_deployment": "medium",
    "scale_cluster": "high",
    "db_migration": "high",
    "delete_resource": "high",
}

_BLAST_ORDER = ["low", "medium", "high"]


def assess_risk(
    action: dict,
    service: str,
    context: dict,
    confidence: float,
    matching_tickets: List[dict],
) -> RiskAssessment:
    """Assess dynamic risk and compute effective blast radius."""
    action_type = action.get("action", "unknown")
    base_blast = BLAST_RADIUS_MAP.get(action_type, "high")
    tier = context.get("service_tier", SERVICE_TIERS.get(service, 3))

    factors: List[RiskFactor] = []

    # Factor 1: Service tier
    if tier == 1:
        factors.append(RiskFactor(
            name="service_tier",
            value=f"tier_{tier}",
            risk_delta=0.05,
            explanation=f"{service} is Tier 1 (revenue-critical)",
        ))
    elif tier == 2:
        factors.append(RiskFactor(
            name="service_tier",
            value=f"tier_{tier}",
            risk_delta=0.0,
            explanation=f"{service} is Tier 2",
        ))

    # Factor 2: Time of day
    hour = context.get("current_hour_utc", 12)
    if 9 <= hour <= 17:
        factors.append(RiskFactor(
            name="peak_hours",
            value="business_hours",
            risk_delta=0.05,
            explanation=f"Business hours ({hour}:00 UTC) — higher user impact",
        ))
    elif 2 <= hour <= 6:
        factors.append(RiskFactor(
            name="quiet_hours",
            value="off_peak",
            risk_delta=-0.03,
            explanation=f"Quiet hours ({hour}:00 UTC) — lower user impact",
        ))

    # Factor 3: Recent deploy
    recent_deploys = context.get("recent_deploys", [])
    service_deploys = [d for d in recent_deploys if d.get("service") == service]
    if service_deploys:
        deploy = service_deploys[0]
        minutes_ago = deploy.get("minutes_ago", 999)
        if minutes_ago < 120:
            factors.append(RiskFactor(
                name="recent_deploy",
                value=f"deployed {minutes_ago}min ago",
                risk_delta=0.08,
                explanation=f"{service} was deployed {minutes_ago} minutes ago — rollback may be more appropriate",
            ))

    # Factor 4: Change freeze
    if context.get("is_change_freeze", False):
        factors.append(RiskFactor(
            name="change_freeze",
            value="active",
            risk_delta=0.20,
            explanation="Change freeze is active — all changes require escalation",
        ))

    # Factor 5: Active incident count
    active_count = context.get("active_incident_count", 0)
    if active_count >= 3:
        factors.append(RiskFactor(
            name="active_incidents",
            value=f"{active_count} active",
            risk_delta=0.05,
            explanation=f"{active_count} incidents active — system already stressed",
        ))

    # Factor 6: Failed retry
    recent_actions = context.get("recent_action_history", [])
    failed_same = [
        a for a in recent_actions
        if a.get("action") == action_type
        and a.get("service") == service
        and a.get("status") == "failed"
    ]
    if failed_same:
        factors.append(RiskFactor(
            name="failed_retry",
            value=f"same action failed {len(failed_same)}x recently",
            risk_delta=0.15,
            explanation=f"{action_type} was attempted on {service} recently and failed — retrying may not help",
        ))

    # Factor 7: Cascade impact (topology-aware)
    try:
        from backend.app.topology.discovery import get_topology
        topo = get_topology()
        upstream = topo.get_all_upstream(service)
        upstream_t1 = [s for s in upstream if SERVICE_TIERS.get(s, 3) == 1]
        if upstream_t1:
            factors.append(RiskFactor(
                name="cascade_impact",
                value=f"{len(upstream_t1)} upstream Tier-1 services",
                risk_delta=0.07,
                explanation=f"Action on {service} cascades to Tier-1: {', '.join(upstream_t1)}",
            ))
        elif len(upstream) >= 3:
            factors.append(RiskFactor(
                name="cascade_impact",
                value=f"{len(upstream)} upstream services",
                risk_delta=0.04,
                explanation=f"Action on {service} affects {len(upstream)} upstream services",
            ))
    except Exception:
        pass  # Topology not available — skip cascade check

    # Compute effective blast radius
    total_delta = sum(f.risk_delta for f in factors)
    effective_blast = base_blast

    # Tier 1 with any positive risk → at least medium
    if tier == 1 and total_delta > 0 and effective_blast == "low":
        effective_blast = "medium"

    # Large risk delta → upgrade one level
    if total_delta > 0.10:
        current_idx = _BLAST_ORDER.index(effective_blast)
        if current_idx < len(_BLAST_ORDER) - 1:
            effective_blast = _BLAST_ORDER[current_idx + 1]

    # Change freeze forces high
    if context.get("is_change_freeze", False):
        effective_blast = "high"

    return RiskAssessment(
        base_blast_radius=base_blast,
        effective_blast_radius=effective_blast,
        risk_factors=factors,
        total_risk_adjustment=round(total_delta, 3),
        service_tier=tier,
    )
