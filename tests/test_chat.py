"""Tests for Phase 1: Chat engine, tools, and response."""

from __future__ import annotations

import pytest

from backend.app.chat.engine import ChatEngine, create_chat_engine
from backend.app.chat.mock_chat_llm import MockChatLLM
from backend.app.chat.response import Action, ChatResponse
from backend.app.chat.tools import get_tools, search_knowledge, set_providers
from mock.providers.knowledge import MockKnowledgeProvider


# --- ChatResponse tests ---

class TestChatResponse:
    def test_defaults(self):
        resp = ChatResponse(text="hello")
        assert resp.text == "hello"
        assert resp.structured_data is None
        assert resp.actions == []
        assert resp.severity == "info"
        assert resp.conversation_id == ""

    def test_with_all_fields(self):
        action = Action(label="Approve", action_id="approve_1", value="yes", style="primary")
        resp = ChatResponse(
            text="Found something",
            structured_data={"incidents": [{"id": "INC-001"}]},
            actions=[action],
            severity="warning",
            conversation_id="session-123",
        )
        assert resp.severity == "warning"
        assert len(resp.actions) == 1
        assert resp.actions[0].label == "Approve"


# --- Tool tests ---

class TestSearchKnowledgeTool:
    @pytest.fixture(autouse=True)
    def setup_provider(self):
        provider = MockKnowledgeProvider()
        set_providers(knowledge=provider)
        yield
        set_providers(knowledge=None)

    async def test_search_returns_results(self):
        result = await search_knowledge.ainvoke({
            "query": "database connection pool exhaustion",
        })
        assert isinstance(result, str)
        assert "RB-001" in result or "pool" in result.lower()

    async def test_search_no_results(self):
        result = await search_knowledge.ainvoke({
            "query": "zzz_nonexistent_topic_zzz",
        })
        assert "No matching knowledge" in result

    async def test_search_with_source_type_filter(self):
        result = await search_knowledge.ainvoke({
            "query": "database connection pool",
            "source_type": "runbook",
        })
        assert isinstance(result, str)
        # Should only contain runbook results
        if "No matching knowledge" not in result:
            assert "RUNBOOK" in result

    async def test_tool_in_registry(self):
        tools = get_tools()
        assert len(tools) == 10
        tool_names = {t.name for t in tools}
        assert "search_knowledge" in tool_names
        assert "query_logs" in tool_names
        assert "query_metrics" in tool_names
        assert "run_analysis" in tool_names
        assert "get_incident" in tool_names
        assert "list_incidents" in tool_names

    async def test_no_provider_returns_message(self):
        set_providers(knowledge=None)
        result = await search_knowledge.ainvoke({
            "query": "anything",
        })
        assert "not available" in result


# --- ChatEngine tests ---

class TestChatEngine:
    async def test_create_default_engine(self):
        engine = create_chat_engine()
        assert isinstance(engine, ChatEngine)

    async def test_basic_chat(self):
        engine = create_chat_engine()
        response = await engine.chat("test-session", "hello")
        assert isinstance(response, ChatResponse)
        assert len(response.text) > 0
        assert response.conversation_id == "test-session"

    async def test_knowledge_query_triggers_tool(self):
        engine = create_chat_engine()
        response = await engine.chat(
            "test-session-2",
            "What runbooks do we have for database connection pool issues?",
        )
        assert isinstance(response, ChatResponse)
        # The mock LLM should trigger search_knowledge and get real results
        assert "knowledge base" in response.text.lower() or "runbook" in response.text.lower()

    async def test_different_sessions_are_independent(self):
        engine = create_chat_engine()
        resp1 = await engine.chat("session-a", "hello")
        resp2 = await engine.chat("session-b", "What runbooks exist for pool issues?")
        # Both should succeed independently
        assert resp1.conversation_id == "session-a"
        assert resp2.conversation_id == "session-b"


# --- MockChatLLM tests ---

class TestMockChatLLM:
    def test_bind_tools_returns_new_instance(self):
        llm = MockChatLLM()
        bound = llm.bind_tools([{"name": "test_tool"}])
        assert isinstance(bound, MockChatLLM)
        assert len(bound._bound_tools) == 1
        assert len(llm._bound_tools) == 0
