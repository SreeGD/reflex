"""Tests for Phase 3 (Tier 1 tools) and Phase 4 (persistence + multi-turn)."""

from __future__ import annotations

import importlib

import pytest

from backend.app.chat.engine import ChatEngine, create_chat_engine
from backend.app.chat.tools import (
    get_incident,
    list_incidents,
    query_logs,
    query_metrics,
    run_analysis,
    search_knowledge,
    set_providers,
    _incidents_store,
)
from backend.app.providers.factory import create_providers


@pytest.fixture
def mock_scenario():
    """Load the db_pool_exhaustion scenario and create providers."""
    mod = importlib.import_module("mock.scenarios.db_pool_exhaustion")
    scenario = mod.create_scenario()
    return scenario


@pytest.fixture
def mock_providers(mock_scenario):
    """Create mock providers from the scenario."""
    return create_providers(mode="mock", scenario=mock_scenario)


@pytest.fixture(autouse=True)
def setup_providers(mock_providers):
    """Inject mock providers into the tools module for each test."""
    set_providers(
        knowledge=mock_providers.knowledge,
        logs=mock_providers.logs,
        metrics=mock_providers.metrics,
    )
    _incidents_store.clear()
    yield
    set_providers(knowledge=None, logs=None, metrics=None, pipeline_graph=None)
    _incidents_store.clear()


# --- query_logs tests ---

class TestQueryLogs:
    async def test_returns_log_entries(self, mock_providers):
        result = await query_logs.ainvoke({
            "service": "order-service",
            "level": "ERROR",
            "limit": 5,
        })
        assert isinstance(result, str)
        assert "order-service" in result.lower() or "log entries" in result.lower()

    async def test_unknown_service_returns_no_logs(self):
        result = await query_logs.ainvoke({
            "service": "nonexistent-service",
        })
        assert isinstance(result, str)

    async def test_no_provider(self):
        set_providers(logs=None)
        result = await query_logs.ainvoke({"service": "order-service"})
        assert "not available" in result


# --- query_metrics tests ---

class TestQueryMetrics:
    async def test_returns_metric_data(self):
        result = await query_metrics.ainvoke({
            "metric": "db_connections_active",
            "service": "order-service",
        })
        assert isinstance(result, str)
        assert "order-service" in result.lower() or "metric" in result.lower()

    async def test_no_provider(self):
        set_providers(metrics=None)
        result = await query_metrics.ainvoke({
            "metric": "cpu",
            "service": "order-service",
        })
        assert "not available" in result


# --- run_analysis tests ---

class TestRunAnalysis:
    async def test_no_pipeline(self):
        set_providers(pipeline_graph=None)
        result = await run_analysis.ainvoke({
            "service": "order-service",
        })
        assert "not available" in result

    async def test_with_pipeline(self, mock_scenario):
        from backend.app.agents.graph import build_graph
        from mock.providers.mock_llm import MockLLM

        providers = create_providers(mode="mock", scenario=mock_scenario)
        graph = build_graph(providers, MockLLM())
        set_providers(pipeline_graph=graph)

        result = await run_analysis.ainvoke({
            "service": "order-service",
            "alert_name": "DBConnectionPoolExhausted",
        })
        assert "Analysis complete" in result
        assert "INC-" in result
        # Should also store the incident
        assert len(_incidents_store) > 0


# --- get_incident / list_incidents tests ---

class TestIncidentTools:
    async def test_get_incident_not_found(self):
        result = await get_incident.ainvoke({"incident_id": "INC-nonexistent"})
        assert "not found" in result

    async def test_get_incident_found(self):
        # Manually store an incident
        _incidents_store["INC-test123"] = {
            "incident_id": "INC-test123",
            "service": "order-service",
            "is_noise": False,
            "root_cause": "Connection pool exhausted",
            "confidence": 0.92,
            "action_decision": "auto_execute",
            "blast_radius": "low",
            "evidence": ["RB-001", "OPS-1234"],
        }
        result = await get_incident.ainvoke({"incident_id": "INC-test123"})
        assert "INC-test123" in result
        assert "order-service" in result
        assert "Connection pool" in result

    async def test_list_incidents_empty(self):
        result = await list_incidents.ainvoke({})
        assert "No incidents" in result

    async def test_list_incidents_with_data(self):
        _incidents_store["INC-001"] = {
            "incident_id": "INC-001",
            "service": "order-service",
            "is_noise": False,
            "confidence": 0.92,
            "action_decision": "auto_execute",
        }
        _incidents_store["INC-002"] = {
            "incident_id": "INC-002",
            "service": "payment-service",
            "is_noise": True,
            "noise_reason": "Known open issue",
        }
        result = await list_incidents.ainvoke({})
        assert "INC-001" in result
        assert "INC-002" in result
        assert "NOISE" in result


# --- Phase 4: Multi-turn conversation + persistence ---

class TestMultiTurn:
    async def test_multi_turn_retains_context(self):
        engine = create_chat_engine()

        # First message
        resp1 = await engine.chat("multi-turn-1", "hello")
        assert resp1.conversation_id == "multi-turn-1"

        # Second message in same session
        resp2 = await engine.chat("multi-turn-1", "What runbooks exist for pool issues?")
        assert resp2.conversation_id == "multi-turn-1"
        assert len(resp2.text) > 0

    async def test_different_sessions_independent(self):
        engine = create_chat_engine()

        resp_a = await engine.chat("session-A", "hello")
        resp_b = await engine.chat("session-B", "What runbooks exist?")

        assert resp_a.conversation_id == "session-A"
        assert resp_b.conversation_id == "session-B"

    async def test_get_history(self):
        engine = create_chat_engine()

        await engine.chat("history-test", "hello")
        await engine.chat("history-test", "What runbooks exist for pool issues?")

        history = await engine.get_history("history-test")
        # Should have at least 2 user messages and 2 assistant responses
        user_msgs = [m for m in history if m["role"] == "user"]
        assistant_msgs = [m for m in history if m["role"] == "assistant"]
        assert len(user_msgs) >= 2
        assert len(assistant_msgs) >= 2

    async def test_get_history_empty_session(self):
        engine = create_chat_engine()
        history = await engine.get_history("nonexistent-session")
        assert history == []


# --- Engine integration with all tools ---

class TestEngineWithAllTools:
    async def test_logs_query(self):
        engine = create_chat_engine()
        resp = await engine.chat("logs-test", "Show me error logs for order-service")
        assert len(resp.text) > 0

    async def test_knowledge_query(self):
        engine = create_chat_engine()
        resp = await engine.chat("knowledge-test", "What runbooks do we have for database issues?")
        assert len(resp.text) > 0
