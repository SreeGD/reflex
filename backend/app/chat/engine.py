"""Chat engine — LangGraph ReAct agent for conversational incident management.

The chat agent is a separate graph from the Reflex analysis pipeline.
It wraps the pipeline and providers as tools, maintaining its own
conversation state via LangGraph's MessagesState.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langgraph.prebuilt import create_react_agent

from backend.app.chat.prompts import compose_prompt, get_default_context
from backend.app.chat.response import ChatResponse
from backend.app.chat.tools import get_tools, set_providers


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

        # Use layered prompt system if no explicit prompt provided
        if system_prompt is None:
            context = get_default_context()
            system_prompt = compose_prompt(context=context)

        self._system_prompt = system_prompt
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
    llm_provider: Any = None,
    knowledge_provider: Any = None,
    checkpointer: Any = None,
    system_prompt: Optional[str] = None,
) -> ChatEngine:
    """Factory function to create a ChatEngine with sensible defaults.

    Args:
        llm_provider: An LLMProvider instance. Auto-detected from environment if None.
        knowledge_provider: A KnowledgeProvider instance. Uses mock if None.
        checkpointer: LangGraph checkpointer for state persistence.
        system_prompt: Override the layered prompt system with a custom prompt.
    """
    if llm_provider is None:
        from backend.app.providers.llm import create_llm_provider
        llm_provider = create_llm_provider()

    llm = llm_provider.get_model("chat")

    if knowledge_provider is None:
        from mock.providers.knowledge import MockKnowledgeProvider
        knowledge_provider = MockKnowledgeProvider()

    return ChatEngine(
        llm=llm,
        knowledge_provider=knowledge_provider,
        checkpointer=checkpointer,
        system_prompt=system_prompt,
    )
