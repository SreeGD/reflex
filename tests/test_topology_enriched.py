"""Tests for multi-source topology discovery, merge, and confidence scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.topology.graph import TopologyGraph, SOURCE_WEIGHTS
from backend.app.topology.merge import merge_topologies


# --- Source tracking tests ---

class TestSourceTracking:
    def test_add_service_with_source(self):
        g = TopologyGraph()
        g.add_service("A", source="config")
        assert "config" in g.get_node_sources("A")

    def test_add_service_multiple_sources(self):
        g = TopologyGraph()
        g.add_service("A", source="config")
        g.add_service("A", source="k8s")
        sources = g.get_node_sources("A")
        assert "config" in sources
        assert "k8s" in sources

    def test_add_dependency_with_source(self):
        g = TopologyGraph()
        g.add_service("A", source="config")
        g.add_service("B", source="config")
        g.add_dependency("A", "B", source="config")
        assert "config" in g.get_edge_sources("A", "B")

    def test_edge_multiple_sources(self):
        g = TopologyGraph()
        g.add_service("A")
        g.add_service("B")
        g.add_dependency("A", "B", source="config")
        g.add_dependency("A", "B", source="k8s")
        g.add_dependency("A", "B", source="jira")
        sources = g.get_edge_sources("A", "B")
        assert len(sources) == 3

    def test_to_dict_includes_sources(self):
        g = TopologyGraph()
        g.add_service("A", source="config")
        g.add_service("B", source="k8s")
        g.add_dependency("A", "B", source="config")
        data = g.to_dict()
        assert data["nodes"][0]["sources"] == ["config"]
        edge = data["edges"][0]
        assert "discovered_by" in edge
        assert "confidence" in edge


# --- Confidence scoring tests ---

class TestConfidenceScoring:
    def test_single_source_confidence(self):
        g = TopologyGraph()
        g.add_service("A")
        g.add_service("B")
        g.add_dependency("A", "B", source="config")
        conf = g.get_edge_confidence("A", "B")
        assert 0 < conf <= 1.0

    def test_multiple_sources_higher_confidence(self):
        g = TopologyGraph()
        g.add_service("A")
        g.add_service("B")
        g.add_dependency("A", "B", source="config")
        conf1 = g.get_edge_confidence("A", "B")

        g.add_dependency("A", "B", source="k8s")
        g.add_dependency("A", "B", source="traces")
        conf3 = g.get_edge_confidence("A", "B")
        assert conf3 > conf1

    def test_no_sources_zero_confidence(self):
        g = TopologyGraph()
        assert g.get_edge_confidence("X", "Y") == 0.0

    def test_config_weighted_higher_than_jira(self):
        g1 = TopologyGraph()
        g1.add_service("A")
        g1.add_service("B")
        g1.add_dependency("A", "B", source="config")
        conf_config = g1.get_edge_confidence("A", "B")

        g2 = TopologyGraph()
        g2.add_service("A")
        g2.add_service("B")
        g2.add_dependency("A", "B", source="jira")
        conf_jira = g2.get_edge_confidence("A", "B")

        assert conf_config > conf_jira


# --- Merge tests ---

class TestMerge:
    def test_merge_adds_new_nodes(self):
        g1 = TopologyGraph()
        g1.add_service("A", source="config")

        g2 = TopologyGraph()
        g2.add_service("B", source="k8s")

        g1.merge(g2)
        assert "A" in g1.list_services()
        assert "B" in g1.list_services()

    def test_merge_accumulates_sources(self):
        g1 = TopologyGraph()
        g1.add_service("A", source="config")

        g2 = TopologyGraph()
        g2.add_service("A", source="k8s")

        g1.merge(g2)
        sources = g1.get_node_sources("A")
        assert "config" in sources
        assert "k8s" in sources

    def test_merge_deduplicates_edges(self):
        g1 = TopologyGraph()
        g1.add_service("A")
        g1.add_service("B")
        g1.add_dependency("A", "B", source="config")

        g2 = TopologyGraph()
        g2.add_service("A")
        g2.add_service("B")
        g2.add_dependency("A", "B", source="k8s")

        g1.merge(g2)
        # Should still be one edge, but with two sources
        data = g1.to_dict()
        edges_ab = [e for e in data["edges"] if e["source"] == "A" and e["target"] == "B"]
        assert len(edges_ab) == 1
        assert len(edges_ab[0]["discovered_by"]) == 2

    def test_merge_topologies_function(self):
        g1 = TopologyGraph()
        g1.add_service("A", source="config")

        g2 = TopologyGraph()
        g2.add_service("B", source="jira")

        merged = merge_topologies(g1, g2)
        assert "A" in merged.list_services()
        assert "B" in merged.list_services()

    def test_merge_empty(self):
        result = merge_topologies()
        assert result.list_services() == []


# --- Source stats tests ---

class TestSourceStats:
    def test_stats(self):
        g = TopologyGraph()
        g.add_service("A", source="config")
        g.add_service("B", source="config")
        g.add_service("B", source="k8s")
        g.add_dependency("A", "B", source="config")
        g.add_dependency("A", "B", source="k8s")

        stats = g.get_source_stats()
        assert stats["config"]["nodes"] == 2
        assert stats["config"]["edges"] == 1
        assert stats["k8s"]["nodes"] == 1
        assert stats["k8s"]["edges"] == 1


# --- Jira discovery tests ---

class TestJiraDiscovery:
    def test_from_jira_tickets(self):
        from backend.app.topology.discovery_jira import from_jira_tickets
        tickets_path = Path(__file__).parent.parent / "mock" / "data" / "jira_tickets.json"
        if not tickets_path.exists():
            pytest.skip("jira_tickets.json not found")

        graph = from_jira_tickets(tickets_path)
        services = graph.list_services()
        assert len(services) > 0
        # Should find at least the major services
        assert any("order" in s for s in services)

    def test_discovers_dependencies(self):
        from backend.app.topology.discovery_jira import from_jira_tickets
        tickets_path = Path(__file__).parent.parent / "mock" / "data" / "jira_tickets.json"
        if not tickets_path.exists():
            pytest.skip("jira_tickets.json not found")

        graph = from_jira_tickets(tickets_path)
        data = graph.to_dict()
        # Should have discovered some edges
        assert len(data["edges"]) > 0
        # All edges should be tagged with "jira" source
        for edge in data["edges"]:
            assert "jira" in edge["discovered_by"]


# --- K8s discovery tests ---

class TestK8sDiscovery:
    def test_from_k8s_manifests(self):
        from backend.app.topology.discovery_k8s import from_k8s_manifests
        k8s_dir = Path(__file__).parent.parent / "mock" / "data" / "k8s_manifests"
        if not k8s_dir.exists():
            pytest.skip("k8s_manifests not found")

        graph = from_k8s_manifests(k8s_dir)
        services = graph.list_services()
        # Should find all 7 application services
        app_services = [s for s in services if s.endswith("-service") or s == "api-gateway"]
        assert len(app_services) == 7

    def test_discovers_dependencies_from_env(self):
        from backend.app.topology.discovery_k8s import from_k8s_manifests
        k8s_dir = Path(__file__).parent.parent / "mock" / "data" / "k8s_manifests"
        if not k8s_dir.exists():
            pytest.skip("k8s_manifests not found")

        graph = from_k8s_manifests(k8s_dir)
        # order-service should depend on payment-service (from PAYMENT_SERVICE_URL env)
        downstream = graph.get_downstream("order-service", depth=1)
        assert "payment-service" in downstream

    def test_discovers_infrastructure(self):
        from backend.app.topology.discovery_k8s import from_k8s_manifests
        k8s_dir = Path(__file__).parent.parent / "mock" / "data" / "k8s_manifests"
        if not k8s_dir.exists():
            pytest.skip("k8s_manifests not found")

        graph = from_k8s_manifests(k8s_dir)
        services = graph.list_services()
        # Should discover infrastructure nodes from connection strings
        infra = [s for s in services if graph.get_service(s).get("node_type") == "infrastructure"]
        assert len(infra) > 0

    def test_extracts_replicas_and_ports(self):
        from backend.app.topology.discovery_k8s import from_k8s_manifests
        k8s_dir = Path(__file__).parent.parent / "mock" / "data" / "k8s_manifests"
        if not k8s_dir.exists():
            pytest.skip("k8s_manifests not found")

        graph = from_k8s_manifests(k8s_dir)
        info = graph.get_service("order-service")
        assert info is not None
        assert info["port"] == 8083
        assert info["replicas"] == 3


# --- Docs discovery tests ---

class TestDocsDiscovery:
    def test_from_docs_mock(self):
        from backend.app.topology.discovery_docs import from_docs

        class FakeLLM:
            pass

        docs_dir = Path(__file__).parent.parent / "mock" / "data" / "confluence_pages"
        if not docs_dir.exists():
            pytest.skip("confluence_pages not found")

        # MockLLM-like class name triggers mock extraction
        class MockLLM:
            pass

        graph = from_docs(MockLLM(), docs_dir)
        services = graph.list_services()
        assert "api-gateway" in services
        assert "order-service" in services

    def test_discovers_async_dependencies(self):
        from backend.app.topology.discovery_docs import from_docs

        class MockLLM:
            pass

        docs_dir = Path(__file__).parent.parent / "mock" / "data" / "confluence_pages"
        if not docs_dir.exists():
            pytest.skip("confluence_pages not found")

        graph = from_docs(MockLLM(), docs_dir)
        data = graph.to_dict()
        # Should find async RabbitMQ dependencies from ARCH-001
        async_edges = [e for e in data["edges"]
                       if graph._edge_metadata.get((e["source"], e["target"]), {}).get("dep_type") == "async"]
        assert len(async_edges) > 0

    def test_discovers_infrastructure_from_docs(self):
        from backend.app.topology.discovery_docs import from_docs

        class MockLLM:
            pass

        docs_dir = Path(__file__).parent.parent / "mock" / "data" / "confluence_pages"
        if not docs_dir.exists():
            pytest.skip("confluence_pages not found")

        graph = from_docs(MockLLM(), docs_dir)
        # Should discover infrastructure from ARCH-001
        services = graph.list_services()
        assert "rabbitmq" in services or "shopfast-db" in services


# --- Full merge integration test ---

class TestFullMerge:
    def test_from_all_sources(self):
        from backend.app.topology.discovery import from_all_sources
        graph = from_all_sources()
        data = graph.to_dict()

        # Should have all 7 app services at minimum
        app_services = [n for n in data["nodes"]
                        if n["name"].endswith("-service") or n["name"] == "api-gateway"]
        assert len(app_services) >= 7

        # Edges should have confidence scores
        for edge in data["edges"]:
            assert "confidence" in edge
            assert edge["confidence"] > 0

        # Some edges should have multiple sources
        multi_source = [e for e in data["edges"] if len(e["discovered_by"]) > 1]
        assert len(multi_source) > 0, "Expected some edges corroborated by multiple sources"

    def test_source_stats(self):
        from backend.app.topology.discovery import from_all_sources
        graph = from_all_sources()
        stats = graph.get_source_stats()
        assert "config" in stats
        assert stats["config"]["nodes"] > 0
