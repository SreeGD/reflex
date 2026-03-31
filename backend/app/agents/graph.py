"""LangGraph pipeline — wires all nodes into a StateGraph.

The graph takes an alarm payload and providers, runs through:
Intake → Noise Check → RCA → Action Router → Remediation → Alert
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from backend.app.agents.nodes.action_router import action_router_node
from backend.app.agents.nodes.alert import alert_node
from backend.app.agents.nodes.intake import intake_node
from backend.app.agents.nodes.noise import noise_node
from backend.app.agents.nodes.rca import rca_node
from backend.app.agents.nodes.remediation import remediation_node
from backend.app.agents.state import AgentState
from backend.app.providers.factory import Providers


def build_graph(providers: Providers, llm: Any) -> Any:
    """Build and compile the LangGraph pipeline.

    Nodes depend on provider interfaces, not implementations.
    Swap providers to switch between mock and production.
    """

    async def _intake(state: AgentState) -> AgentState:
        return await intake_node(state)

    async def _noise(state: AgentState) -> AgentState:
        return await noise_node(state, providers.knowledge)

    async def _rca(state: AgentState) -> AgentState:
        return await rca_node(state, providers.knowledge, providers.logs, llm)

    async def _action_router(state: AgentState) -> AgentState:
        return await action_router_node(state)

    async def _remediation(state: AgentState) -> AgentState:
        return await remediation_node(state, providers.actions)

    async def _alert(state: AgentState) -> AgentState:
        return await alert_node(state, providers.alerts)

    def _should_continue_after_noise(state: AgentState) -> str:
        if state.get("is_noise"):
            return "alert"  # Skip RCA, just alert as FYI
        return "rca"

    graph = StateGraph(AgentState)

    graph.add_node("intake", _intake)
    graph.add_node("noise", _noise)
    graph.add_node("rca", _rca)
    graph.add_node("action_router", _action_router)
    graph.add_node("remediation", _remediation)
    graph.add_node("alert", _alert)

    graph.set_entry_point("intake")
    graph.add_edge("intake", "noise")
    graph.add_conditional_edges("noise", _should_continue_after_noise)
    graph.add_edge("rca", "action_router")
    graph.add_edge("action_router", "remediation")
    graph.add_edge("remediation", "alert")
    graph.add_edge("alert", END)

    return graph.compile()
