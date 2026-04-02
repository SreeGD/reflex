"""Topology discovery strategies — build graph from various data sources."""

from __future__ import annotations

from typing import Any, Dict, List

from backend.app.topology.graph import TopologyGraph


def from_config() -> TopologyGraph:
    """Build topology from mock/config.py SERVICES and DEPENDENCY_GRAPH."""
    from mock.config import DEPENDENCY_GRAPH, SERVICES, ServiceType

    graph = TopologyGraph()

    type_labels = {
        ServiceType.PYTHON_FASTAPI: "Python/FastAPI",
        ServiceType.GO: "Go",
        ServiceType.NODEJS: "Node.js",
        ServiceType.JAVA_SPRING: "Java/Spring Boot",
    }

    for name, svc in SERVICES.items():
        graph.add_service(
            name,
            display_name=svc.display_name,
            language=type_labels.get(svc.service_type, str(svc.service_type)),
            port=svc.port,
            replicas=svc.replicas,
            namespace=svc.namespace,
            tier=_get_tier(name),
        )

    for caller, callees in DEPENDENCY_GRAPH.items():
        for callee in callees:
            graph.add_dependency(caller, callee)

    return graph


def from_traces(spans: List[Dict[str, Any]]) -> TopologyGraph:
    """Discover topology from OpenTelemetry-style trace spans.

    Extracts service-to-service edges from parent-child span relationships.
    Each span should have: service_name, parent_span_id, span_id.
    """
    graph = TopologyGraph()
    span_index: Dict[str, Dict[str, Any]] = {}

    # Index spans by span_id
    for span in spans:
        sid = span.get("span_id", "")
        if sid:
            span_index[sid] = span
            service = span.get("service_name") or span.get("attributes", {}).get("service", "")
            if service:
                graph.add_service(service)

    # Extract edges from parent-child relationships
    for span in spans:
        parent_id = span.get("parent_span_id")
        if not parent_id or parent_id not in span_index:
            continue

        child_service = span.get("service_name") or span.get("attributes", {}).get("service", "")
        parent_service = span_index[parent_id].get("service_name") or span_index[parent_id].get("attributes", {}).get("service", "")

        if child_service and parent_service and child_service != parent_service:
            graph.add_dependency(parent_service, child_service)

    return graph


def _get_tier(service: str) -> int:
    """Get service tier from risk.py mapping."""
    from backend.app.agents.risk import SERVICE_TIERS
    return SERVICE_TIERS.get(service, 3)


# Module-level singleton — the default topology graph
_default_graph = None


def get_topology() -> TopologyGraph:
    """Get the default topology graph (lazily built from config)."""
    global _default_graph
    if _default_graph is None:
        _default_graph = from_config()
    return _default_graph
