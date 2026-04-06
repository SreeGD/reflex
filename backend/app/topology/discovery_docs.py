"""LLM-powered architecture doc parsing — extract topology from markdown docs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.app.topology.graph import TopologyGraph

_EXTRACTION_PROMPT = """Analyze the following architecture documentation and extract structured topology information.

Return a JSON object with these fields:
- "services": list of objects with "name", "tech_stack", "team", "port", "replicas"
- "dependencies": list of objects with "from", "to", "type" (sync or async), "protocol"
- "infrastructure": list of objects with "name", "type", "details"

Only include information explicitly stated in the document. Do not infer or guess.

Document:
---
{content}
---

Return ONLY valid JSON, no other text."""

# Pre-built extraction results for mock mode (matches ARCH-001/002/003 content)
_MOCK_EXTRACTIONS = {
    "ARCH-001": {
        "services": [
            {"name": "api-gateway", "tech_stack": "Node.js/Express", "team": "Platform", "port": 8080, "replicas": 3},
            {"name": "catalog-service", "tech_stack": "Go/Gin", "team": "Catalog", "port": 8081, "replicas": 3},
            {"name": "cart-service", "tech_stack": "Java/Spring Boot", "team": "Commerce", "port": 8082, "replicas": 2},
            {"name": "order-service", "tech_stack": "Python/FastAPI", "team": "Commerce", "port": 8083, "replicas": 4},
            {"name": "payment-service", "tech_stack": "Java/Spring Boot", "team": "Payments", "port": 8084, "replicas": 2},
            {"name": "inventory-service", "tech_stack": "Go/Gin", "team": "Supply Chain", "port": 8086, "replicas": 2},
            {"name": "notification-service", "tech_stack": "Python/FastAPI", "team": "Platform", "port": 8085, "replicas": 2},
        ],
        "dependencies": [
            {"from": "api-gateway", "to": "catalog-service", "type": "sync", "protocol": "REST"},
            {"from": "api-gateway", "to": "cart-service", "type": "sync", "protocol": "REST"},
            {"from": "api-gateway", "to": "order-service", "type": "sync", "protocol": "REST"},
            {"from": "order-service", "to": "payment-service", "type": "sync", "protocol": "REST"},
            {"from": "order-service", "to": "inventory-service", "type": "sync", "protocol": "REST"},
            {"from": "catalog-service", "to": "inventory-service", "type": "sync", "protocol": "REST"},
            {"from": "cart-service", "to": "catalog-service", "type": "sync", "protocol": "REST"},
            {"from": "order-service", "to": "notification-service", "type": "async", "protocol": "RabbitMQ"},
            {"from": "payment-service", "to": "order-service", "type": "async", "protocol": "RabbitMQ"},
            {"from": "inventory-service", "to": "catalog-service", "type": "async", "protocol": "RabbitMQ"},
        ],
        "infrastructure": [
            {"name": "shopfast-db", "type": "postgresql", "details": "RDS PostgreSQL 15.4, db.r6g.xlarge, Multi-AZ"},
            {"name": "redis", "type": "redis", "details": "ElastiCache Redis 7.0, r6g.large"},
            {"name": "rabbitmq", "type": "message_broker", "details": "Amazon MQ RabbitMQ 3.12, mq.m5.large"},
            {"name": "opensearch", "type": "search", "details": "OpenSearch 8.11, 3x m5.large.search"},
        ],
    },
    "ARCH-002": {
        "services": [
            {"name": "order-service", "tech_stack": "Python/FastAPI", "db_schema": "orders", "db_pool_max": 20},
            {"name": "payment-service", "tech_stack": "Java/Spring Boot", "db_schema": "payments", "db_pool_max": 15},
            {"name": "inventory-service", "tech_stack": "Go/Gin", "db_schema": "inventory", "db_pool_max": 15},
            {"name": "catalog-service", "tech_stack": "Go/Gin", "db_schema": "catalog", "db_pool_max": 10},
            {"name": "notification-service", "tech_stack": "Python/FastAPI", "db_schema": "notifications", "db_pool_max": 5},
        ],
        "dependencies": [
            {"from": "order-service", "to": "shopfast-db", "type": "sync", "protocol": "postgresql"},
            {"from": "payment-service", "to": "shopfast-db", "type": "sync", "protocol": "postgresql"},
            {"from": "inventory-service", "to": "shopfast-db", "type": "sync", "protocol": "postgresql"},
            {"from": "catalog-service", "to": "shopfast-db", "type": "sync", "protocol": "postgresql"},
            {"from": "notification-service", "to": "shopfast-db", "type": "sync", "protocol": "postgresql"},
            {"from": "cart-service", "to": "redis", "type": "sync", "protocol": "redis"},
            {"from": "catalog-service", "to": "redis", "type": "sync", "protocol": "redis"},
        ],
        "infrastructure": [],
    },
    "ARCH-003": {
        "services": [],
        "dependencies": [],
        "infrastructure": [
            {"name": "prometheus", "type": "metrics", "details": "15s scrape interval, 30d retention, Thanos sidecar"},
            {"name": "grafana", "type": "dashboards", "details": "7 dashboards: overview, per-service, infra, business"},
            {"name": "elasticsearch", "type": "logs", "details": "Fluentd DaemonSet, 14d hot, 90d warm"},
            {"name": "jaeger", "type": "tracing", "details": "OTEL collector, 10% head sampling, 100% errors"},
        ],
    },
}


def from_docs(llm_provider: Any, data_dir: Path) -> TopologyGraph:
    """Parse architecture docs using LLM to extract topology."""
    graph = TopologyGraph()

    for doc_file in sorted(data_dir.glob("ARCH-*.md")):
        content = doc_file.read_text()
        doc_id = doc_file.stem.split("-", 2)[:2]
        doc_key = "-".join(doc_id)  # e.g., "ARCH-001"

        extraction = _extract_topology(llm_provider, content, doc_key)
        if extraction:
            _populate_graph(graph, extraction)

    return graph


def _extract_topology(llm_provider: Any, content: str, doc_key: str) -> Optional[Dict[str, Any]]:
    """Extract topology from a document using LLM or mock."""
    # Check if this is a mock LLM (has pre-built responses)
    if doc_key in _MOCK_EXTRACTIONS:
        # Use mock if the LLM is MockLLM or MockChatLLM
        llm_type = type(llm_provider).__name__ if llm_provider else ""
        if "Mock" in llm_type or llm_provider is None:
            return _MOCK_EXTRACTIONS[doc_key]

    # Real LLM extraction
    try:
        from langchain_core.messages import HumanMessage
        prompt = _EXTRACTION_PROMPT.format(content=content[:4000])
        response = llm_provider.invoke([HumanMessage(content=prompt)])
        return json.loads(response.content)
    except Exception:
        # Fallback to mock if available
        return _MOCK_EXTRACTIONS.get(doc_key)


def _populate_graph(graph: TopologyGraph, extraction: Dict[str, Any]) -> None:
    """Add extracted data to the topology graph."""
    for svc in extraction.get("services", []):
        name = svc.get("name", "")
        if not name:
            continue
        meta = {k: v for k, v in svc.items() if k != "name"}
        graph.add_service(name, source="docs", **meta)

    for dep in extraction.get("dependencies", []):
        caller = dep.get("from", "")
        callee = dep.get("to", "")
        if caller and callee:
            dep_type = dep.get("type", "sync")
            protocol = dep.get("protocol", "unknown")
            graph.add_dependency(caller, callee, source="docs", dep_type=dep_type, protocol=protocol)

    for infra in extraction.get("infrastructure", []):
        name = infra.get("name", "")
        if name:
            graph.add_service(
                name, source="docs",
                node_type="infrastructure",
                infra_type=infra.get("type", ""),
                details=infra.get("details", ""),
            )
