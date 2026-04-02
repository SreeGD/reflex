"""Tests for webhook endpoint, incident store, and scenario matching."""

from __future__ import annotations

import time

import pytest

from backend.app.incidents import IncidentStore, incident_store
from backend.app.api.webhook import _match_scenario, _get_scenario_map


# --- IncidentStore tests ---

class TestIncidentStore:
    def setup_method(self):
        self.store = IncidentStore()

    def test_put_and_get(self):
        self.store.put("INC-001", {"service": "order-service"}, source="webhook")
        result = self.store.get("INC-001")
        assert result is not None
        assert result["service"] == "order-service"
        assert result["_source"] == "webhook"
        assert "_stored_at" in result

    def test_get_not_found(self):
        assert self.store.get("INC-nonexistent") is None

    def test_list_all(self):
        self.store.put("INC-001", {"service": "a"})
        self.store.put("INC-002", {"service": "b"})
        all_inc = self.store.list_all()
        assert len(all_inc) == 2
        assert "INC-001" in all_inc
        assert "INC-002" in all_inc

    def test_list_since(self):
        t_before = time.time()
        self.store.put("INC-001", {"service": "a"})
        t_after = time.time()
        self.store.put("INC-002", {"service": "b"})

        recent = self.store.list_since(t_after - 0.001)
        assert len(recent) >= 1

        old = self.store.list_since(time.time() + 100)
        assert len(old) == 0

    def test_count(self):
        assert self.store.count() == 0
        self.store.put("INC-001", {"service": "a"})
        assert self.store.count() == 1

    def test_clear(self):
        self.store.put("INC-001", {"service": "a"})
        self.store.clear()
        assert self.store.count() == 0

    def test_to_summary_list(self):
        self.store.put("INC-001", {
            "incident_id": "INC-001",
            "service": "order-service",
            "is_noise": False,
            "root_cause": "Pool exhausted",
            "confidence": 0.92,
            "action_decision": "auto_execute",
            "blast_radius": "low",
            "alarm": {"labels": {"severity": "critical"}},
        }, source="webhook")

        summaries = self.store.to_summary_list()
        assert len(summaries) == 1
        s = summaries[0]
        assert s["incident_id"] == "INC-001"
        assert s["service"] == "order-service"
        assert s["severity"] == "critical"
        assert s["source"] == "webhook"
        assert s["confidence"] == 0.92

    def test_severity_extracted_from_alarm(self):
        self.store.put("INC-001", {
            "alarm": {"labels": {"severity": "warning"}},
        })
        result = self.store.get("INC-001")
        assert result["_severity_label"] == "warning"


# --- Scenario matching tests ---

class TestScenarioMatcher:
    def test_match_db_pool_exhaustion(self):
        alarm = {
            "labels": {"alertname": "DBConnectionPoolExhausted", "service": "order-service"},
        }
        assert _match_scenario(alarm) == "db_pool_exhaustion"

    def test_match_payment_timeout(self):
        alarm = {
            "labels": {"alertname": "PaymentGatewayTimeout", "service": "payment-service"},
        }
        assert _match_scenario(alarm) == "payment_timeout_cascade"

    def test_match_by_alertname_only(self):
        alarm = {
            "labels": {"alertname": "HighHeapUsage", "service": "some-other-service"},
        }
        result = _match_scenario(alarm)
        assert result == "memory_leak"

    def test_unknown_falls_back_to_default(self):
        alarm = {
            "labels": {"alertname": "UnknownAlert", "service": "unknown-service"},
        }
        assert _match_scenario(alarm) == "db_pool_exhaustion"

    def test_scenario_map_populated(self):
        scenario_map = _get_scenario_map()
        assert len(scenario_map) > 0


# --- Webhook pipeline integration test ---

class TestWebhookPipeline:
    @pytest.fixture(autouse=True)
    def reset_store(self):
        incident_store.clear()
        yield
        incident_store.clear()

    async def test_run_pipeline(self):
        from backend.app.api.webhook import _run_pipeline

        alarm = {
            "status": "firing",
            "labels": {
                "alertname": "DBConnectionPoolExhausted",
                "service": "order-service",
                "severity": "critical",
            },
            "annotations": {"summary": "Pool exhausted"},
        }

        state = await _run_pipeline(alarm)
        assert "incident_id" in state
        assert state.get("service") == "order-service"
        assert "root_cause" in state
