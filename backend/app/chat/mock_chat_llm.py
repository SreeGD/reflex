"""Mock chat LLM that supports tool calling for the ReAct agent.

The existing MockLLM only handles RCA/critique prompts. This mock
handles conversational messages and can invoke tools via LangChain's
tool-calling protocol.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Type, Union

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool


class MockChatLLM(BaseChatModel):
    """A mock chat model that supports tool calling for the ReAct agent.

    On the first call, if tools are bound and the message looks like a
    knowledge query, it emits a tool call. On subsequent calls (after
    tool results), it synthesizes a text response.
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
        # Check if we have tool results in the messages
        has_tool_result = any(
            getattr(m, "type", "") == "tool" for m in messages
        )

        if has_tool_result:
            # We already called a tool — synthesize a response from the tool output
            tool_content = ""
            for m in messages:
                if getattr(m, "type", "") == "tool":
                    tool_content = m.content

            if "No matching knowledge" in tool_content:
                text = "I couldn't find any relevant information in the knowledge base for your query."
            elif tool_content:
                text = (
                    "Here's what I found in the knowledge base:\n\n"
                    f"{tool_content}\n\n"
                    "Let me know if you'd like more details on any of these results."
                )
            else:
                text = "I processed your request but didn't get any results back."

            msg = AIMessage(content=text)
            return ChatResult(generations=[ChatGeneration(message=msg)])

        # First call — decide whether to use a tool
        last_user_msg = ""
        for m in reversed(messages):
            if getattr(m, "type", "") == "human":
                last_user_msg = m.content
                break

        # If we have tools and the message looks like a knowledge query, call the tool
        knowledge_keywords = [
            "runbook", "ticket", "incident", "knowledge", "how to",
            "procedure", "sop", "jira", "confluence", "search",
            "find", "show me", "what do we know", "pool", "database",
            "connection", "restart", "scale", "deploy", "error",
        ]
        should_search = any(kw in last_user_msg.lower() for kw in knowledge_keywords)

        if should_search and self._bound_tools:
            # Emit a tool call for search_knowledge
            msg = AIMessage(
                content="",
                tool_calls=[{
                    "id": "mock_tool_call_1",
                    "name": "search_knowledge",
                    "args": {"query": last_user_msg, "limit": 5},
                }],
            )
            return ChatResult(generations=[ChatGeneration(message=msg)])

        # No tool needed — just respond directly
        msg = AIMessage(
            content="I'm Reflex, your incident management assistant. "
            "I can help you search runbooks, past incidents, and operational knowledge. "
            "What would you like to investigate?"
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"model_name": self.model_name}
