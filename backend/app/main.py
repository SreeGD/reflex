"""Reflex API — FastAPI entry point."""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Reflex",
    description="Observe → Analyze → Act. AI-powered incident management.",
    version="0.1.0",
)

from backend.app.api.chat import router as chat_router
from backend.app.api.webhook import router as webhook_router

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router)
app.include_router(webhook_router)

# Available demo scenarios
SCENARIOS = {
    "db_pool_exhaustion": "mock.scenarios.db_pool_exhaustion",
    "payment_timeout_cascade": "mock.scenarios.payment_timeout_cascade",
    "memory_leak": "mock.scenarios.memory_leak",
    "redis_connection_storm": "mock.scenarios.redis_connection_storm",
    "slow_query_cascade": "mock.scenarios.slow_query_cascade",
}


def _load_scenario(name: str):
    mod = importlib.import_module(SCENARIOS[name])
    return mod.create_scenario()


def _get_llm():
    if os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)
    from mock.providers.mock_llm import MockLLM
    return MockLLM()


# --- Request / Response models ---

class AlarmRequest(BaseModel):
    alarm: Dict[str, Any]
    scenario: Optional[str] = None


class IncidentResponse(BaseModel):
    incident_id: Optional[str] = None
    service: Optional[str] = None
    is_noise: bool = False
    noise_reason: Optional[str] = None
    root_cause: Optional[str] = None
    confidence: float = 0.0
    confidence_signals: Dict[str, Any] = {}
    evidence: List[str] = []
    suggested_actions: List[Dict[str, Any]] = []
    action_decision: Optional[str] = None
    blast_radius: Optional[str] = None
    adjusted_confidence: float = 0.0
    risk_assessment: Dict[str, Any] = {}
    decision_brief: Optional[Dict[str, Any]] = None
    review_critique: Optional[Dict[str, Any]] = None
    review_adjustments: List[str] = []
    action_taken: Optional[Dict[str, Any]] = None
    action_result: Optional[Dict[str, Any]] = None
    alert_sent: bool = False


class ScenarioInfo(BaseModel):
    name: str
    display_name: str
    description: str
    service: str
    blast_radius: str


# --- Endpoints ---

@app.get("/")
async def root():
    return {"name": "Reflex", "status": "running", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/scenarios", response_model=List[ScenarioInfo])
async def list_scenarios():
    """List available demo scenarios."""
    results = []
    for name in SCENARIOS:
        s = _load_scenario(name)
        results.append(ScenarioInfo(
            name=name,
            display_name=s.get_display_name(),
            description=s.get_description(),
            service=s.get_affected_service(),
            blast_radius=s.get_blast_radius(),
        ))
    return results


@app.post("/analyze", response_model=IncidentResponse)
async def analyze_alarm(request: AlarmRequest):
    """Run the full Reflex pipeline on an alarm payload."""
    from backend.app.agents.graph import build_graph
    from backend.app.providers.factory import create_providers

    if request.scenario:
        if request.scenario not in SCENARIOS:
            raise HTTPException(404, f"Unknown scenario: {request.scenario}")
        scenario = _load_scenario(request.scenario)
        providers = create_providers(mode="mock", scenario=scenario)
        alarm = request.alarm or scenario.get_alert_payload()
    else:
        # For now, default to db_pool_exhaustion mock
        scenario = _load_scenario("db_pool_exhaustion")
        providers = create_providers(mode="mock", scenario=scenario)
        alarm = request.alarm

    llm = _get_llm()
    graph = build_graph(providers, llm)

    final_state = {}
    async for event in graph.astream({"alarm": alarm}):
        for _node_name, node_state in event.items():
            final_state.update(node_state)

    return IncidentResponse(**{
        k: v for k, v in final_state.items()
        if k in IncidentResponse.model_fields
    })


@app.post("/scenarios/{scenario_name}/run", response_model=IncidentResponse)
async def run_scenario(scenario_name: str):
    """Run a demo scenario end-to-end with its built-in alert payload."""
    if scenario_name not in SCENARIOS:
        raise HTTPException(404, f"Unknown scenario: {scenario_name}")

    from backend.app.agents.graph import build_graph
    from backend.app.providers.factory import create_providers

    scenario = _load_scenario(scenario_name)
    providers = create_providers(mode="mock", scenario=scenario)
    llm = _get_llm()
    graph = build_graph(providers, llm)

    alert = scenario.get_alert_payload()
    final_state = {}
    async for event in graph.astream({"alarm": alert}):
        for _node_name, node_state in event.items():
            final_state.update(node_state)

    return IncidentResponse(**{
        k: v for k, v in final_state.items()
        if k in IncidentResponse.model_fields
    })
