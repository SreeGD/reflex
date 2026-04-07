"""Chat engine — LangGraph ReAct agent for conversational incident management.

The chat agent is a separate graph from the Reflex analysis pipeline.
It wraps the pipeline and providers as tools, maintaining its own
conversation state via LangGraph's MessagesState.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langgraph.prebuilt import create_react_agent

from backend.app.chat.logging import ConversationLogger
from backend.app.chat.prompts import compose_prompt, get_default_context
from backend.app.chat.response import ChatResponse
from backend.app.chat.tools import get_tools, set_providers


class ChatEngine:
    """Conversational AI engine backed by a LangGraph ReAct agent."""

    def __init__(
        self,
        llm: Any,
        knowledge_provider: Any = None,
        logs_provider: Any = None,
        metrics_provider: Any = None,
        actions_provider: Any = None,
        alerts_provider: Any = None,
        pipeline_graph: Any = None,
        checkpointer: Any = None,
        system_prompt: Optional[str] = None,
        logger: Optional[ConversationLogger] = None,
    ) -> None:
        self._logger = logger

        # Inject providers into the tools module
        set_providers(
            knowledge=knowledge_provider,
            logs=logs_provider,
            metrics=metrics_provider,
            actions=actions_provider,
            alerts=alerts_provider,
            pipeline_graph=pipeline_graph,
        )

        # Use layered prompt system if no explicit prompt provided
        if system_prompt is None:
            context = get_default_context()
            system_prompt = compose_prompt(context=context)

        self._system_prompt = system_prompt
        self._checkpointer = checkpointer
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
        if self._logger:
            self._logger.log_inbound(session_id, user_id, message)

        config = {"configurable": {"thread_id": session_id}}
        error_msg = None

        try:
            result = await self._agent.ainvoke(
                {"messages": [("user", message)]},
                config=config,
            )
        except Exception as e:
            error_msg = str(e)
            if self._logger:
                self._logger.log_outbound(
                    session_id, user_id, "", error=error_msg,
                )
            return ChatResponse(
                text=f"An error occurred: {error_msg}",
                conversation_id=session_id,
                severity="critical",
            )

        # Extract the final AI message and tool calls from the result
        messages = result.get("messages", [])
        ai_text = ""
        tool_calls_log = []
        for msg in messages:
            if hasattr(msg, "type") and msg.type == "ai":
                if msg.content:
                    ai_text = msg.content
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls_log.append({
                            "name": tc.get("name", ""),
                            "args": {k: str(v)[:100] for k, v in tc.get("args", {}).items()},
                        })

        response_text = ai_text or "I wasn't able to generate a response."

        if self._logger:
            self._logger.log_outbound(
                session_id, user_id, response_text,
                tool_calls=tool_calls_log,
            )

        return ChatResponse(
            text=response_text,
            conversation_id=session_id,
        )

    async def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Retrieve conversation history for a session.

        Returns list of {"role": "user"|"assistant", "content": "..."} dicts.
        """
        if self._checkpointer is None:
            return []

        config = {"configurable": {"thread_id": session_id}}
        state = await self._agent.aget_state(config)

        if not state or not state.values:
            return []

        messages = state.values.get("messages", [])
        history = []
        for msg in messages:
            msg_type = getattr(msg, "type", "")
            content = getattr(msg, "content", "")
            if msg_type == "human" and content:
                history.append({"role": "user", "content": content})
            elif msg_type == "ai" and content:
                history.append({"role": "assistant", "content": content})

        return history


def create_chat_engine(
    llm_provider: Any = None,
    knowledge_provider: Any = None,
    logs_provider: Any = None,
    metrics_provider: Any = None,
    actions_provider: Any = None,
    alerts_provider: Any = None,
    scenario_name: Optional[str] = None,
    checkpointer: Any = None,
    system_prompt: Optional[str] = None,
) -> ChatEngine:
    """Factory function to create a ChatEngine with sensible defaults.

    Args:
        llm_provider: An LLMProvider instance. Auto-detected from environment if None.
        knowledge_provider: A KnowledgeProvider instance. Uses mock if None.
        logs_provider: A LogsProvider instance. Uses mock if None.
        metrics_provider: A MetricsProvider instance. Uses mock if None.
        actions_provider: An ActionsProvider instance. Uses mock if None.
        alerts_provider: An AlertsProvider instance. Uses mock if None.
        scenario_name: Mock scenario to load for pipeline + providers. Defaults to db_pool_exhaustion.
        checkpointer: LangGraph checkpointer for state persistence. Uses MemorySaver if None.
        system_prompt: Override the layered prompt system with a custom prompt.
    """
    from langgraph.checkpoint.memory import MemorySaver

    if llm_provider is None:
        from backend.app.providers.llm import create_llm_provider
        llm_provider = create_llm_provider()

    llm = llm_provider.get_model("chat")

    # Build mock providers if not provided
    from backend.app.providers.factory import create_providers
    import importlib

    if scenario_name is None:
        from mock.config import get_active_scenarios
        scenarios, _ = get_active_scenarios()
        scenario_name = next(iter(scenarios.keys()))
    mod = importlib.import_module(f"mock.scenarios.{scenario_name}")
    scenario = mod.create_scenario()
    mock_providers = create_providers(mode="mock", scenario=scenario)

    if knowledge_provider is None:
        knowledge_provider = mock_providers.knowledge
    if logs_provider is None:
        logs_provider = mock_providers.logs
    if metrics_provider is None:
        metrics_provider = mock_providers.metrics
    if actions_provider is None:
        actions_provider = mock_providers.actions
    if alerts_provider is None:
        alerts_provider = mock_providers.alerts

    # Build pipeline graph for run_analysis tool
    pipeline_graph = None
    try:
        from backend.app.agents.graph import build_graph
        pipeline_llm = llm_provider.get_model("rca")
        pipeline_graph = build_graph(mock_providers, pipeline_llm)
    except Exception:
        pass  # Pipeline not available — run_analysis tool will report this

    # Default to MemorySaver for in-process persistence
    if checkpointer is None:
        checkpointer = MemorySaver()

    # Create conversation logger
    import os
    log_path = os.environ.get("CHAT_LOG_PATH", "logs/chat.jsonl")
    logger = ConversationLogger(log_path=log_path)

    return ChatEngine(
        llm=llm,
        knowledge_provider=knowledge_provider,
        logs_provider=logs_provider,
        metrics_provider=metrics_provider,
        actions_provider=actions_provider,
        alerts_provider=alerts_provider,
        pipeline_graph=pipeline_graph,
        checkpointer=checkpointer,
        system_prompt=system_prompt,
        logger=logger,
    )
