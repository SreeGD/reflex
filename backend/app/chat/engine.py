"""Chat engine — LangGraph ReAct agent for conversational incident management.

The chat agent is a separate graph from the Reflex analysis pipeline.
It wraps the pipeline and providers as tools, maintaining its own
conversation state via LangGraph's MessagesState.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langgraph.prebuilt import create_react_agent

from backend.app.chat.response import ChatResponse
from backend.app.chat.tools import get_tools, set_providers

# Default system prompt (Phase 2 will replace with layered markdown files)
_DEFAULT_SYSTEM_PROMPT = (
    "You are Reflex, an AI-powered incident management assistant. "
    "You help on-call engineers investigate and resolve incidents by "
    "querying logs, metrics, runbooks, and past incidents.\n\n"
    "When an engineer asks a question, use your tools to find relevant "
    "information before answering. Be concise, direct, and actionable. "
    "Always cite your sources (runbook IDs, ticket keys, etc).\n\n"
    "If you don't have enough information to answer confidently, say so "
    "and suggest what the engineer should investigate next."
)


class ChatEngine:
    """Conversational AI engine backed by a LangGraph ReAct agent."""

    def __init__(
        self,
        llm: Any,
        knowledge_provider: Any = None,
        checkpointer: Any = None,
        system_prompt: Optional[str] = None,
    ) -> None:
        # Inject providers into the tools module
        set_providers(knowledge=knowledge_provider)

        self._system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        tools = get_tools()

        self._agent = create_react_agent(
            model=llm,
            tools=tools,
            prompt=self._system_prompt,
            checkpointer=checkpointer,
        )

    async def chat(
        self,
        session_id: str,
        message: str,
        user_id: str = "anonymous",
    ) -> ChatResponse:
        """Process a user message and return a structured response.

        Args:
            session_id: Conversation thread ID (maps to Slack thread_ts).
            message: The user's message text.
            user_id: Identity of the user (for audit logging).

        Returns:
            ChatResponse with the agent's reply.
        """
        config = {"configurable": {"thread_id": session_id}}

        result = await self._agent.ainvoke(
            {"messages": [("user", message)]},
            config=config,
        )

        # Extract the final AI message from the result
        messages = result.get("messages", [])
        ai_text = ""
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "ai" and msg.content:
                ai_text = msg.content
                break

        return ChatResponse(
            text=ai_text or "I wasn't able to generate a response.",
            conversation_id=session_id,
        )


def create_chat_engine(
    llm: Any = None,
    knowledge_provider: Any = None,
    checkpointer: Any = None,
    system_prompt: Optional[str] = None,
) -> ChatEngine:
    """Factory function to create a ChatEngine with sensible defaults.

    Uses MockLLM and MockKnowledgeProvider if no arguments are provided.
    """
    if llm is None:
        from backend.app.chat.mock_chat_llm import MockChatLLM
        llm = MockChatLLM()

    if knowledge_provider is None:
        from mock.providers.knowledge import MockKnowledgeProvider
        knowledge_provider = MockKnowledgeProvider()

    return ChatEngine(
        llm=llm,
        knowledge_provider=knowledge_provider,
        checkpointer=checkpointer,
        system_prompt=system_prompt,
    )
