"""Impact analysis — cascade-aware blast radius and affected services."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.app.topology.graph import TopologyGraph

# User journey definitions: name -> ordered list of services in the call path
USER_JOURNEYS = {
    "checkout": ["api-gateway", "order-service", "payment-service", "inventory-service", "notification-service"],
    "browse_catalog": ["api-gateway", "catalog-service", "inventory-service"],
    "add_to_cart": ["api-gateway", "cart-service", "catalog-service"],
}


def get_affected_services(graph: TopologyGraph, service: str) -> Dict[str, List[str]]:
    """Get all services affected by an outage at the given service.

    Returns {"upstream": [...], "downstream": [...]} where upstream services
    are callers that will experience failures and downstream are dependencies.
    """
    return {
        "upstream": graph.get_all_upstream(service),
        "downstream": graph.get_all_downstream(service),
    }


def get_affected_journeys(graph: TopologyGraph, service: str) -> List[Dict[str, Any]]:
    """Determine which user journeys are affected by an outage at this service."""
    affected = []
    for journey_name, services in USER_JOURNEYS.items():
        if service in services:
            affected.append({
                "journey": journey_name,
                "services_in_path": services,
                "position": services.index(service),
                "services_after": services[services.index(service) + 1:],
            })
    return affected


def calculate_blast_radius(
    graph: TopologyGraph,
    service: str,
    action: str = "restart_deployment",
) -> Dict[str, Any]:
    """Calculate propagated blast radius considering service dependencies.

    Unlike the static BLAST_RADIUS_MAP, this considers:
    - How many upstream services depend on this one
    - Whether upstream services include Tier 1 (revenue-critical)
    - How many user journeys are affected
    """
    from backend.app.agents.risk import BLAST_RADIUS_MAP, SERVICE_TIERS

    base_blast = BLAST_RADIUS_MAP.get(action, "high")
    upstream = graph.get_all_upstream(service)
    downstream = graph.get_all_downstream(service)
    journeys = get_affected_journeys(graph, service)

    tier = SERVICE_TIERS.get(service, 3)
    upstream_tier1 = [s for s in upstream if SERVICE_TIERS.get(s, 3) == 1]
    total_affected = len(set(upstream + downstream))

    # Propagation rules
    propagated_blast = base_blast
    reasons = []

    if upstream_tier1:
        reasons.append(f"Upstream Tier-1 services affected: {', '.join(upstream_tier1)}")
        if propagated_blast == "low":
            propagated_blast = "medium"

    if total_affected >= 3:
        reasons.append(f"{total_affected} services in blast radius")
        if propagated_blast == "low":
            propagated_blast = "medium"
        elif propagated_blast == "medium" and total_affected >= 5:
            propagated_blast = "high"

    if len(journeys) >= 2:
        reasons.append(f"{len(journeys)} user journeys affected")
        if propagated_blast == "low":
            propagated_blast = "medium"

    return {
        "service": service,
        "action": action,
        "base_blast_radius": base_blast,
        "propagated_blast_radius": propagated_blast,
        "tier": tier,
        "upstream_services": upstream,
        "downstream_services": downstream,
        "upstream_tier1": upstream_tier1,
        "total_affected_services": total_affected,
        "affected_journeys": [j["journey"] for j in journeys],
        "reasons": reasons,
    }
