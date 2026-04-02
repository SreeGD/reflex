"""Tests for topology graph, discovery, impact analysis, and docs."""

from __future__ import annotations

import pytest

from backend.app.topology.graph import TopologyGraph
from backend.app.topology.discovery import from_config, from_traces, get_topology
from backend.app.topology.impact import (
    calculate_blast_radius,
    get_affected_journeys,
    get_affected_services,
)
from backend.app.topology.docs import generate_catalog, generate_mermaid


# --- TopologyGraph tests ---

class TestTopologyGraph:
    def setup_method(self):
        self.g = TopologyGraph()
        self.g.add_service("A", tier=1)
        self.g.add_service("B", tier=2)
        self.g.add_service("C", tier=3)
        self.g.add_dependency("A", "B")
        self.g.add_dependency("B", "C")

    def test_add_service(self):
        assert "A" in self.g.list_services()
        assert len(self.g.list_services()) == 3

    def test_get_service(self):
        info = self.g.get_service("A")
        assert info["name"] == "A"
        assert info["tier"] == 1
        assert "B" in info["downstream"]

    def test_get_downstream(self):
        assert self.g.get_downstream("A", depth=1) == ["B"]
        assert set(self.g.get_downstream("A", depth=2)) == {"B", "C"}

    def test_get_upstream(self):
        assert self.g.get_upstream("C", depth=1) == ["B"]
        assert set(self.g.get_upstream("C", depth=2)) == {"A", "B"}

    def test_get_all_downstream(self):
        assert set(self.g.get_all_downstream("A")) == {"B", "C"}

    def test_get_all_upstream(self):
        assert set(self.g.get_all_upstream("C")) == {"A", "B"}

    def test_no_dependencies(self):
        assert self.g.get_downstream("C") == []
        assert self.g.get_upstream("A") == []

    def test_set_health(self):
        self.g.set_health("B", "degraded")
        info = self.g.get_service("B")
        assert info["health"] == "degraded"

    def test_to_dict(self):
        data = self.g.to_dict()
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) == 2

    def test_service_not_found(self):
        assert self.g.get_service("Z") is None

    def test_duplicate_edge(self):
        self.g.add_dependency("A", "B")  # duplicate
        assert self.g.get_downstream("A", depth=1) == ["B"]  # still just one


# --- Discovery tests ---

class TestDiscovery:
    def test_from_config(self):
        graph = from_config()
        services = graph.list_services()
        assert "api-gateway" in services
        assert "order-service" in services
        assert len(services) == 7

        info = graph.get_service("order-service")
        assert "payment-service" in info["downstream"]
        assert info["tier"] == 1

    def test_from_traces(self):
        spans = [
            {"span_id": "s1", "parent_span_id": None, "service_name": "gateway"},
            {"span_id": "s2", "parent_span_id": "s1", "service_name": "orders"},
            {"span_id": "s3", "parent_span_id": "s2", "service_name": "payments"},
        ]
        graph = from_traces(spans)
        assert "gateway" in graph.list_services()
        assert "payments" in graph.get_downstream("gateway", depth=2)

    def test_from_traces_ignores_same_service(self):
        spans = [
            {"span_id": "s1", "parent_span_id": None, "service_name": "orders"},
            {"span_id": "s2", "parent_span_id": "s1", "service_name": "orders"},
        ]
        graph = from_traces(spans)
        assert graph.get_downstream("orders") == []

    def test_get_topology_singleton(self):
        graph = get_topology()
        assert len(graph.list_services()) == 7


# --- Impact analysis tests ---

class TestImpactAnalysis:
    def setup_method(self):
        self.graph = from_config()

    def test_affected_services_order_service(self):
        affected = get_affected_services(self.graph, "order-service")
        assert "api-gateway" in affected["upstream"]
        assert "payment-service" in affected["downstream"]

    def test_affected_services_leaf(self):
        affected = get_affected_services(self.graph, "notification-service")
        assert "order-service" in affected["upstream"]
        assert affected["downstream"] == []

    def test_affected_journeys(self):
        journeys = get_affected_journeys(self.graph, "payment-service")
        names = [j["journey"] for j in journeys]
        assert "checkout" in names

    def test_no_journeys_for_cart(self):
        journeys = get_affected_journeys(self.graph, "notification-service")
        names = [j["journey"] for j in journeys]
        assert "checkout" in names  # notification is in checkout path

    def test_blast_radius_leaf_service(self):
        result = calculate_blast_radius(self.graph, "notification-service", "restart_deployment")
        assert result["base_blast_radius"] == "low"
        # notification-service is Tier 3 with order-service upstream (Tier 1)
        assert result["propagated_blast_radius"] in ("low", "medium")

    def test_blast_radius_inventory_cascades(self):
        result = calculate_blast_radius(self.graph, "inventory-service", "restart_deployment")
        # inventory-service has multiple upstream services
        assert result["total_affected_services"] >= 2
        assert len(result["upstream_services"]) >= 2

    def test_blast_radius_payment_tier1_upstream(self):
        result = calculate_blast_radius(self.graph, "payment-service", "restart_deployment")
        # payment-service is called by order-service (Tier 1) and api-gateway (Tier 1)
        assert len(result["upstream_tier1"]) >= 1


# --- Docs generator tests ---

class TestDocsGenerator:
    def setup_method(self):
        self.graph = from_config()

    def test_generate_mermaid(self):
        mermaid = generate_mermaid(self.graph)
        assert "graph TD" in mermaid
        assert "api-gateway" in mermaid
        assert "-->" in mermaid

    def test_generate_mermaid_with_highlight(self):
        mermaid = generate_mermaid(self.graph, highlight_service="order-service")
        assert "order-service" in mermaid
        assert "stroke:#FF0000" in mermaid

    def test_generate_catalog(self):
        catalog = generate_catalog(self.graph)
        assert "# Service Catalog" in catalog
        assert "api-gateway" in catalog
        assert "Tier 1" in catalog
        assert "order-service" in catalog

    def test_catalog_has_all_services(self):
        catalog = generate_catalog(self.graph)
        for svc in ["api-gateway", "order-service", "payment-service", "cart-service",
                     "catalog-service", "inventory-service", "notification-service"]:
            assert svc in catalog


# --- Chat tools integration ---

class TestTopologyChatTools:
    async def test_show_topology_full(self):
        from backend.app.chat.tools import show_topology
        result = await show_topology.ainvoke({})
        assert "Service Topology" in result
        assert "api-gateway" in result

    async def test_show_topology_single_service(self):
        from backend.app.chat.tools import show_topology
        result = await show_topology.ainvoke({"service": "order-service"})
        assert "order-service" in result
        assert "payment-service" in result

    async def test_analyze_impact(self):
        from backend.app.chat.tools import analyze_impact
        result = await analyze_impact.ainvoke({
            "service": "payment-service",
            "action": "restart_deployment",
        })
        assert "Impact Analysis" in result
        assert "payment-service" in result
        assert "blast radius" in result.lower()

    async def test_show_topology_unknown(self):
        from backend.app.chat.tools import show_topology
        result = await show_topology.ainvoke({"service": "nonexistent"})
        assert "not found" in result
