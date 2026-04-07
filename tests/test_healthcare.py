"""Tests for healthcare EHR mock system (MOCK_SYSTEM=healthcare)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def healthcare_mode():
    """Set MOCK_SYSTEM=healthcare for all tests in this file."""
    with patch.dict(os.environ, {"MOCK_SYSTEM": "healthcare"}):
        # Reset cached singletons
        from backend.app.topology.discovery import reset_topology
        reset_topology()
        yield
        reset_topology()


class TestHealthcareConfig:
    def test_active_system(self):
        from mock.config import get_active_system
        assert get_active_system() == "healthcare"

    def test_services(self):
        from mock.config import get_active_config
        services, deps = get_active_config()
        assert "patient-service" in services
        assert "ehr-gateway" in services
        assert "billing-service" in services
        assert len(services) == 7

    def test_dependency_graph(self):
        from mock.config import get_active_config
        _, deps = get_active_config()
        assert "billing-service" in deps["patient-service"]
        assert "pharmacy-service" in deps["patient-service"]
        assert "medication-service" in deps["ehr-gateway"]

    def test_scenarios(self):
        from mock.config import get_active_scenarios
        scenarios, labels = get_active_scenarios()
        assert "ehr_db_pool_exhaustion" in scenarios
        assert len(scenarios) == 5


class TestHealthcareScenarios:
    def test_load_ehr_scenario(self):
        import importlib
        mod = importlib.import_module("mock.scenarios.ehr_db_pool_exhaustion")
        s = mod.create_scenario()
        assert s.get_affected_service() == "patient-service"
        assert "EHR" in s.get_alert_payload()["labels"]["alertname"]
        assert s.get_alert_payload()["labels"]["namespace"] == "medflow-prod"

    def test_load_all_scenarios(self):
        import importlib
        from mock.config import get_active_scenarios
        scenarios, _ = get_active_scenarios()
        for name, module_path in scenarios.items():
            mod = importlib.import_module(module_path)
            s = mod.create_scenario()
            assert s.get_affected_service() is not None
            assert s.get_alert_payload() is not None
            assert s.get_blast_radius() in ("low", "medium", "high")


class TestHealthcareKnowledge:
    def test_knowledge_provider_loads_healthcare(self):
        from mock.providers.knowledge import MockKnowledgeProvider
        provider = MockKnowledgeProvider()
        # Should find healthcare runbooks
        assert len(provider._runbooks) > 0

    async def test_search_ehr_runbook(self):
        from mock.providers.knowledge import MockKnowledgeProvider
        provider = MockKnowledgeProvider()
        results = await provider.search_similar("EHR connection pool patient records")
        assert len(results) > 0


class TestHealthcareTopology:
    def test_topology_has_healthcare_services(self):
        from backend.app.topology.discovery import from_config
        graph = from_config()
        services = graph.list_services()
        assert "patient-service" in services
        assert "ehr-gateway" in services
        assert "order-service" not in services

    def test_impact_analysis(self):
        from backend.app.topology.discovery import from_config
        from backend.app.topology.impact import get_affected_services
        graph = from_config()
        affected = get_affected_services(graph, "pharmacy-service")
        assert "patient-service" in affected["upstream"] or "medication-service" in affected["upstream"]
