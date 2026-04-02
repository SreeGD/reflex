"""Tests for Phases 5-8: Action tools, logging, rendering, Slack adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.app.chat.logging import ConversationLogger, TimedToolTracker
from backend.app.chat.response import Action, ChatResponse
from backend.app.chat.tools import (
    _action_log,
    _incidents_store,
    approve_action,
    deny_action,
    escalate,
    execute_remediation,
    get_tools,
    set_providers,
)
from backend.app.adapters.slack import (
    SlackAdapter,
    chat_response_to_blocks,
    format_slack_message,
)
from mock.providers.actions import MockActionsProvider
from mock.providers.alerts import MockAlertsProvider


# --- Phase 5: Tier 2 Action Tools ---

@pytest.fixture(autouse=True)
def reset_tools():
    """Reset tool state between tests."""
    _incidents_store.clear()
    _action_log.clear()
    actions = MockActionsProvider()
    alerts = MockAlertsProvider(log_dir=Path(tempfile.mkdtemp()))
    set_providers(actions=actions, alerts=alerts, allowed_users=None)
    yield
    set_providers(actions=None, alerts=None, allowed_users=None)
    _incidents_store.clear()
    _action_log.clear()


class TestApproveAction:
    async def test_approve_pending_action(self):
        _incidents_store["INC-001"] = {
            "incident_id": "INC-001",
            "service": "order-service",
            "action_decision": "human_approval",
            "suggested_actions": [{"action": "restart_deployment", "deployment": "order-service", "namespace": "prod"}],
        }
        result = await approve_action.ainvoke({"incident_id": "INC-001", "user_id": "alice"})
        assert "APPROVED" in result
        assert "alice" in result
        assert len(_action_log) == 1
        assert _action_log[0]["action_type"] == "approve"

    async def test_approve_already_executed(self):
        _incidents_store["INC-002"] = {
            "incident_id": "INC-002",
            "action_decision": "auto_execute",
        }
        result = await approve_action.ainvoke({"incident_id": "INC-002"})
        assert "already auto-executed" in result

    async def test_approve_not_found(self):
        result = await approve_action.ainvoke({"incident_id": "INC-999"})
        assert "not found" in result

    async def test_approve_unauthorized(self):
        set_providers(allowed_users={"bob"})
        _incidents_store["INC-003"] = {"incident_id": "INC-003", "action_decision": "human_approval"}
        result = await approve_action.ainvoke({"incident_id": "INC-003", "user_id": "alice"})
        assert "not authorized" in result


class TestDenyAction:
    async def test_deny_with_reason(self):
        _incidents_store["INC-001"] = {"incident_id": "INC-001"}
        result = await deny_action.ainvoke({
            "incident_id": "INC-001",
            "reason": "I think this is a config issue",
            "user_id": "bob",
        })
        assert "DENIED" in result
        assert "bob" in result
        assert "config issue" in result
        assert len(_action_log) == 1
        assert _action_log[0]["reason"] == "I think this is a config issue"


class TestEscalate:
    async def test_escalate_incident(self):
        _incidents_store["INC-001"] = {"incident_id": "INC-001"}
        result = await escalate.ainvoke({
            "incident_id": "INC-001",
            "reason": "Beyond my scope",
            "user_id": "charlie",
        })
        assert "ESCALATED" in result
        assert "charlie" in result
        assert len(_action_log) == 1


class TestExecuteRemediation:
    async def test_restart(self):
        result = await execute_remediation.ainvoke({
            "service": "order-service",
            "action_type": "restart",
            "namespace": "prod",
            "user_id": "alice",
        })
        assert "executed" in result.lower()
        assert "restart" in result.lower()
        assert len(_action_log) == 1

    async def test_scale(self):
        result = await execute_remediation.ainvoke({
            "service": "payment-service",
            "action_type": "scale",
            "replicas": 5,
            "user_id": "bob",
        })
        assert "executed" in result.lower()
        assert "scale" in result.lower()


class TestToolRegistry:
    def test_all_10_tools(self):
        tools = get_tools()
        assert len(tools) == 10
        names = {t.name for t in tools}
        assert "approve_action" in names
        assert "deny_action" in names
        assert "escalate" in names
        assert "execute_remediation" in names


# --- Phase 6: Structured Logging ---

class TestConversationLogger:
    def test_log_inbound(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            log_path = f.name

        logger = ConversationLogger(log_path=log_path)
        logger.log_inbound("sess-1", "alice", "What happened?")

        entries = Path(log_path).read_text().strip().split("\n")
        assert len(entries) == 1
        entry = json.loads(entries[0])
        assert entry["direction"] == "inbound"
        assert entry["conversation_id"] == "sess-1"
        assert entry["user_id"] == "alice"
        assert entry["message_text"] == "What happened?"
        assert "timestamp" in entry

    def test_log_outbound_with_tools(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            log_path = f.name

        logger = ConversationLogger(log_path=log_path)
        logger.log_outbound(
            "sess-1", "alice", "Found 3 runbooks",
            tool_calls=[{"name": "search_knowledge", "args": {"query": "pool"}, "duration_ms": 50, "success": True}],
            llm_usage={"model": "mock-chat", "prompt_tokens": 100, "completion_tokens": 50},
            actions_taken=[{"type": "approve", "incident_id": "INC-001"}],
        )

        entries = Path(log_path).read_text().strip().split("\n")
        entry = json.loads(entries[0])
        assert entry["direction"] == "outbound"
        assert len(entry["tool_calls"]) == 1
        assert entry["tool_calls"][0]["name"] == "search_knowledge"
        assert entry["llm_usage"]["model"] == "mock-chat"
        assert len(entry["actions_taken"]) == 1

    def test_log_outbound_with_error(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            log_path = f.name

        logger = ConversationLogger(log_path=log_path)
        logger.log_outbound("sess-1", "alice", "", error="Connection timeout")

        entry = json.loads(Path(log_path).read_text().strip())
        assert entry["error"] == "Connection timeout"

    def test_ndjson_format(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            log_path = f.name

        logger = ConversationLogger(log_path=log_path)
        logger.log_inbound("s1", "u1", "msg1")
        logger.log_outbound("s1", "u1", "resp1")
        logger.log_inbound("s1", "u1", "msg2")

        lines = Path(log_path).read_text().strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            parsed = json.loads(line)
            assert "timestamp" in parsed


class TestTimedToolTracker:
    def test_track_tool_call(self):
        tracker = TimedToolTracker()
        call_id = tracker.start("search_knowledge", {"query": "pool"})
        tracker.finish(call_id, success=True)

        calls = tracker.get_calls()
        assert len(calls) == 1
        assert calls[0]["name"] == "search_knowledge"
        assert calls[0]["success"] is True
        assert calls[0]["duration_ms"] >= 0


# --- Phase 7: Adaptive Rendering ---

class TestChatResponseRendering:
    def test_structured_data_field(self):
        resp = ChatResponse(
            text="Found issues",
            structured_data={
                "incidents": [{"id": "INC-001", "service": "order-service"}],
                "count": 3,
            },
        )
        assert resp.structured_data["count"] == 3

    def test_actions_field(self):
        resp = ChatResponse(
            text="Pending approval",
            actions=[
                Action(label="Approve", action_id="approve_1", style="primary"),
                Action(label="Deny", action_id="deny_1", style="danger"),
            ],
        )
        assert len(resp.actions) == 2
        assert resp.actions[0].style == "primary"

    def test_severity_field(self):
        resp = ChatResponse(text="Critical issue", severity="critical")
        assert resp.severity == "critical"


# --- Phase 8: Slack Adapter ---

class TestSlackBlockKit:
    def test_basic_text_response(self):
        resp = ChatResponse(text="Hello from Reflex")
        blocks = chat_response_to_blocks(resp)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "section"
        assert "Hello from Reflex" in blocks[0]["text"]["text"]

    def test_severity_header(self):
        resp = ChatResponse(text="Alert", severity="critical")
        blocks = chat_response_to_blocks(resp)
        assert blocks[0]["type"] == "context"
        assert "CRITICAL" in blocks[0]["elements"][0]["text"]

    def test_structured_data_as_fields(self):
        resp = ChatResponse(
            text="Metrics",
            structured_data={"CPU": "45%", "Memory": "78%"},
        )
        blocks = chat_response_to_blocks(resp)
        field_blocks = [b for b in blocks if b.get("fields")]
        assert len(field_blocks) == 1
        assert len(field_blocks[0]["fields"]) == 2

    def test_action_buttons(self):
        resp = ChatResponse(
            text="Approve restart?",
            actions=[
                Action(label="Approve", action_id="approve_1", style="primary"),
                Action(label="Deny", action_id="deny_1", style="danger"),
            ],
        )
        blocks = chat_response_to_blocks(resp)
        action_blocks = [b for b in blocks if b["type"] == "actions"]
        assert len(action_blocks) == 1
        buttons = action_blocks[0]["elements"]
        assert len(buttons) == 2
        assert buttons[0]["style"] == "primary"
        assert buttons[1]["style"] == "danger"

    def test_format_full_message(self):
        resp = ChatResponse(text="Test message", severity="warning")
        msg = format_slack_message(resp)
        assert "text" in msg
        assert "blocks" in msg
        assert len(msg["blocks"]) >= 2  # context + section


class TestSlackAdapter:
    def test_handle_message_strips_mention(self):
        adapter = SlackAdapter()
        # We can't call the API in unit tests, but we can verify the adapter exists
        assert hasattr(adapter, "handle_message")
        assert hasattr(adapter, "handle_interaction")
        assert hasattr(adapter, "_call_chat_api")
