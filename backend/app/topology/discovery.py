"""Topology discovery strategies — build graph from various data sources."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

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
            source="config",
            display_name=svc.display_name,
            language=type_labels.get(svc.service_type, str(svc.service_type)),
            port=svc.port,
            replicas=svc.replicas,
            namespace=svc.namespace,
            tier=_get_tier(name),
        )

    for caller, callees in DEPENDENCY_GRAPH.items():
        for callee in callees:
            graph.add_dependency(caller, callee, source="config")

    return graph


def from_traces(spans: List[Dict[str, Any]]) -> TopologyGraph:
    """Discover topology from OpenTelemetry-style trace spans."""
    graph = TopologyGraph()
    span_index: Dict[str, Dict[str, Any]] = {}

    for span in spans:
        sid = span.get("span_id", "")
        if sid:
            span_index[sid] = span
            service = span.get("service_name") or span.get("attributes", {}).get("service", "")
            if service:
                graph.add_service(service, source="traces")

    for span in spans:
        parent_id = span.get("parent_span_id")
        if not parent_id or parent_id not in span_index:
            continue

        child_service = span.get("service_name") or span.get("attributes", {}).get("service", "")
        parent_service = span_index[parent_id].get("service_name") or span_index[parent_id].get("attributes", {}).get("service", "")

        if child_service and parent_service and child_service != parent_service:
            graph.add_dependency(parent_service, child_service, source="traces")

    return graph


def from_all_sources(llm_provider: Any = None) -> TopologyGraph:
    """Run all available discovery strategies and merge results."""
    from backend.app.topology.merge import merge_topologies

    graphs = [from_config()]

    # Jira ticket mining
    try:
        from backend.app.topology.discovery_jira import from_jira_tickets
        jira_path = Path(__file__).parent.parent.parent.parent / "mock" / "data" / "jira_tickets.json"
        if jira_path.exists():
            graphs.append(from_jira_tickets(jira_path))
    except Exception:
        pass

    # K8s manifest discovery
    try:
        from backend.app.topology.discovery_k8s import from_k8s_manifests
        k8s_dir = Path(__file__).parent.parent.parent.parent / "mock" / "data" / "k8s_manifests"
        if k8s_dir.exists():
            graphs.append(from_k8s_manifests(k8s_dir))
    except Exception:
        pass

    # LLM doc parsing
    if llm_provider is not None:
        try:
            from backend.app.topology.discovery_docs import from_docs
            docs_dir = Path(__file__).parent.parent.parent.parent / "mock" / "data" / "confluence_pages"
            if docs_dir.exists():
                graphs.append(from_docs(llm_provider, docs_dir))
        except Exception:
            pass

    return merge_topologies(*graphs)


def _get_tier(service: str) -> int:
    from backend.app.agents.risk import SERVICE_TIERS
    return SERVICE_TIERS.get(service, 3)


# Module-level singleton
_default_graph = None


def get_topology() -> TopologyGraph:
    """Get the default topology graph. Uses enriched discovery if TOPOLOGY_ENRICHED=true."""
    global _default_graph
    if _default_graph is None:
        if os.environ.get("TOPOLOGY_ENRICHED", "").lower() == "true":
            _default_graph = from_all_sources()
        else:
            _default_graph = from_config()
    return _default_graph


def reset_topology() -> None:
    """Reset the singleton (for testing)."""
    global _default_graph
    _default_graph = None
