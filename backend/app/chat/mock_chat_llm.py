"""Mock chat LLM that supports tool calling for the ReAct agent.

The existing MockLLM only handles RCA/critique prompts. This mock
handles conversational messages and can invoke tools via LangChain's
tool-calling protocol.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Sequence, Type, Union

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

# Tool routing rules: keywords → (tool_name, args_builder)
_TOOL_ROUTES = [
    # Logs queries
    (
        ["logs", "log entries", "errors for", "error logs", "show.*logs"],
        "query_logs",
        lambda msg: {"service": _extract_service(msg), "level": "ERROR", "limit": 10},
    ),
    # Metrics queries
    (
        ["metric", "cpu", "memory usage", "latency", "error rate", "connections active", "request rate"],
        "query_metrics",
        lambda msg: {"metric": _extract_metric(msg), "service": _extract_service(msg)},
    ),
    # Run full analysis
    (
        ["analyze", "run analysis", "full analysis", "investigate", "what's happening"],
        "run_analysis",
        lambda msg: {"service": _extract_service(msg)},
    ),
    # Get specific incident
    (
        ["incident INC-", "tell me about INC-", "details.*INC-"],
        "get_incident",
        lambda msg: {"incident_id": _extract_incident_id(msg)},
    ),
    # List incidents
    (
        ["list incidents", "recent incidents", "active incidents", "all incidents"],
        "list_incidents",
        lambda _msg: {},
    ),
    # Knowledge search (broadest — keep last)
    (
        [
            "runbook", "ticket", "knowledge", "how to", "procedure", "sop",
            "jira", "confluence", "search", "find", "show me", "what do we know",
            "pool", "database", "connection", "restart", "scale", "deploy",
        ],
        "search_knowledge",
        lambda msg: {"query": msg, "limit": 5},
    ),
]


def _extract_service(msg: str) -> str:
    """Extract a service name from a message, or default."""
    import re
    # Look for common service name patterns
    match = re.search(r'(?:for|on|about|service)\s+([a-z][\w-]+(?:-service)?)', msg.lower())
    if match:
        return match.group(1)
    # Check for known service names
    for svc in ["order-service", "payment-service", "cart-service", "inventory-service", "api-gateway"]:
        if svc in msg.lower():
            return svc
    return "order-service"


def _extract_metric(msg: str) -> str:
    """Extract a metric name from a message, or default."""
    msg_lower = msg.lower()
    if "cpu" in msg_lower:
        return "process_cpu_seconds"
    if "memory" in msg_lower or "heap" in msg_lower:
        return "process_resident_memory_bytes"
    if "latency" in msg_lower or "p99" in msg_lower:
        return "http_request_duration_seconds"
    if "connection" in msg_lower or "pool" in msg_lower:
        return "db_connections_active"
    if "error" in msg_lower:
        return "http_requests_total"
    return "http_requests_total"


def _extract_incident_id(msg: str) -> str:
    """Extract an incident ID from a message."""
    import re
    match = re.search(r'(INC-[a-f0-9]+)', msg)
    return match.group(1) if match else "INC-unknown"


class MockChatLLM(BaseChatModel):
    """A mock chat model that supports tool calling for the ReAct agent.

    Routes user messages to appropriate tools based on keyword matching.
    After tool results, synthesizes a natural response.
    """

    model_name: str = "mock-chat"
    _bound_tools: List[Any] = []

    @property
    def _llm_type(self) -> str:
        return "mock-chat"

    def bind_tools(
        self,
        tools: Sequence[Union[Dict[str, Any], Type, BaseTool, Any]],
        **kwargs: Any,
    ) -> "MockChatLLM":
        """Return a copy with tools bound."""
        new = MockChatLLM(model_name=self.model_name)
        new._bound_tools = list(tools)
        return new

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        import re

        # Check if we have tool results in the messages
        has_tool_result = any(
            getattr(m, "type", "") == "tool" for m in messages
        )

        if has_tool_result:
            # Find the last tool result
            tool_content = ""
            for m in reversed(messages):
                if getattr(m, "type", "") == "tool":
                    tool_content = m.content
                    break

            if "not available" in tool_content or "not found" in tool_content:
                text = tool_content
            elif "No matching" in tool_content or "No logs" in tool_content or "No data" in tool_content:
                text = tool_content
            elif tool_content:
                text = (
                    "Here's what I found:\n\n"
                    f"{tool_content}\n\n"
                    "Let me know if you'd like more details or want to investigate further."
                )
            else:
                text = "I processed your request but didn't get any results back."

            msg = AIMessage(content=text)
            return ChatResult(generations=[ChatGeneration(message=msg)])

        # First call — decide which tool to use
        last_user_msg = ""
        for m in reversed(messages):
            if getattr(m, "type", "") == "human":
                last_user_msg = m.content
                break

        if self._bound_tools and last_user_msg:
            msg_lower = last_user_msg.lower()
            for keywords, tool_name, args_builder in _TOOL_ROUTES:
                for kw in keywords:
                    if re.search(kw, msg_lower):
                        # Check that this tool is actually bound
                        tool_names = set()
                        for t in self._bound_tools:
                            if hasattr(t, "name"):
                                tool_names.add(t.name)
                            elif isinstance(t, dict):
                                tool_names.add(t.get("name", ""))
                        if tool_name in tool_names:
                            msg = AIMessage(
                                content="",
                                tool_calls=[{
                                    "id": f"mock_{uuid.uuid4().hex[:8]}",
                                    "name": tool_name,
                                    "args": args_builder(last_user_msg),
                                }],
                            )
                            return ChatResult(generations=[ChatGeneration(message=msg)])
                        break

        # No tool needed — respond directly
        msg = AIMessage(
            content="I'm Reflex, your incident management assistant. "
            "I can help you search runbooks, query logs and metrics, "
            "run incident analysis, and manage remediations. "
            "What would you like to investigate?"
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"model_name": self.model_name}
