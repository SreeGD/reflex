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
# Routes ordered from most specific to least specific.
# Multi-word patterns are checked first to avoid false matches.
_TOOL_ROUTES = [
    # --- Tier 2: Actions (most specific, check first) ---
    (
        ["approve.*inc-", "approve the action", "approve action"],
        "approve_action",
        lambda msg: {"incident_id": _extract_incident_id(msg), "user_id": "chat_user"},
    ),
    (
        ["deny.*inc-", "deny the action", "deny action", "reject"],
        "deny_action",
        lambda msg: {"incident_id": _extract_incident_id(msg), "reason": msg, "user_id": "chat_user"},
    ),
    (
        ["escalate.*inc-", "escalate to", "escalate the"],
        "escalate",
        lambda msg: {"incident_id": _extract_incident_id(msg), "reason": msg, "user_id": "chat_user"},
    ),
    (
        ["restart.*service", "scale.*service", "execute remediation", "rollback.*service"],
        "execute_remediation",
        lambda msg: {
            "service": _extract_service(msg),
            "action_type": "restart" if "restart" in msg.lower() else "scale" if "scale" in msg.lower() else "rollback",
            "namespace": _extract_namespace(msg),
            "user_id": "chat_user",
        },
    ),
    # --- Tier 1: Specific queries (multi-word patterns first) ---
    # List incidents (must come before get_incident to avoid "list" + "incident" mismatch)
    (
        ["list incidents", "list all incidents", "recent incidents", "active incidents", "all incidents", "show incidents"],
        "list_incidents",
        lambda _msg: {},
    ),
    # Get specific incident
    (
        ["inc-[a-f0-9]", "tell me about inc", "details.*inc", "about incident"],
        "get_incident",
        lambda msg: {"incident_id": _extract_incident_id(msg)},
    ),
    # Run full analysis
    (
        ["run analysis", "full analysis", "analyze.*service", "investigate.*service", "what's happening"],
        "run_analysis",
        lambda msg: {"service": _extract_service(msg)},
    ),
    # Logs queries
    (
        ["error logs", "log entries", "show.*logs", "logs for", "recent logs"],
        "query_logs",
        lambda msg: {"service": _extract_service(msg), "level": "ERROR", "limit": 10},
    ),
    # Metrics queries
    (
        ["metric", "cpu usage", "memory usage", "latency", "error rate", "connections.active", "request rate", "db_connections"],
        "query_metrics",
        lambda msg: {"metric": _extract_metric(msg), "service": _extract_service(msg)},
    ),
    # Knowledge search (broadest — always last)
    (
        [
            "runbook", "ticket", "knowledge", "how to", "procedure", "sop",
            "jira", "confluence", "what do we know", "past incident",
            "pool exhaustion", "database pool", "connection pool",
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
    match = re.search(r'(INC-[a-fA-F0-9]+)', msg)
    return match.group(1) if match else "INC-unknown"


def _extract_namespace(msg: str) -> str:
    """Extract a Kubernetes namespace from a message."""
    import re
    match = re.search(r'(?:namespace|ns)\s+([a-z][\w-]+)', msg.lower())
    if match:
        return match.group(1)
    if "prod" in msg.lower():
        return "shopfast-prod"
    return "default"


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

        # Find the last user message and check if a tool result came AFTER it.
        # In multi-turn conversations with checkpointing, old tool results
        # from previous turns will be present — we only care about the current turn.
        last_user_idx = -1
        last_tool_idx = -1
        for i, m in enumerate(messages):
            msg_type = getattr(m, "type", "")
            if msg_type == "human":
                last_user_idx = i
            elif msg_type == "tool":
                last_tool_idx = i

        # A tool result is "fresh" only if it came after the last user message
        fresh_tool_result = last_tool_idx > last_user_idx and last_user_idx >= 0

        if fresh_tool_result:
            # We just called a tool for this turn — synthesize a response
            tool_content = messages[last_tool_idx].content

            if "not available" in tool_content or "not found" in tool_content:
                text = tool_content
            elif "No matching" in tool_content or "No logs" in tool_content or "No data" in tool_content or "No incidents" in tool_content:
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

        # No fresh tool result — route the latest user message to a tool
        last_user_msg = ""
        if last_user_idx >= 0:
            last_user_msg = messages[last_user_idx].content

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
