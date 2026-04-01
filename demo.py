#!/usr/bin/env python3
"""Reflex Platform Demo — proof of value.

Usage:
    python demo.py                                     # default scenario
    python demo.py --scenario payment_timeout_cascade  # specific scenario
    python demo.py --scenario all                      # all scenarios
    python demo.py --list                              # list scenarios
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

SCENARIOS = {
    "db_pool_exhaustion": "mock.scenarios.db_pool_exhaustion",
    "payment_timeout_cascade": "mock.scenarios.payment_timeout_cascade",
    "memory_leak": "mock.scenarios.memory_leak",
    "redis_connection_storm": "mock.scenarios.redis_connection_storm",
    "slow_query_cascade": "mock.scenarios.slow_query_cascade",
}


def load_scenario(name: str):
    import importlib
    mod = importlib.import_module(SCENARIOS[name])
    return mod.create_scenario()


def print_header():
    console.print()
    console.print(
        Panel(
            "[bold white]Reflex Platform — Live Demo[/bold white]\n"
            "[dim]Observe → Analyze → Act[/dim]",
            border_style="bright_blue",
            padding=(1, 4),
        )
    )


def print_before_story(scenario):
    story = scenario.get_before_story()
    console.print()
    console.print("[bold yellow]━━━ BEFORE (Manual Ops) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold yellow]")
    console.print()
    for time_str, desc in story.steps:
        console.print(f"  [dim]{time_str:<10}[/dim] {desc}")
    console.print()
    console.print(f"  [dim]─────────────────────────────────────[/dim]")
    console.print(
        f"  [bold red]MTTR: {story.total_mttr_minutes} minutes[/bold red] | "
        f"Manual steps: {story.manual_steps} | Sleep lost: priceless"
    )
    console.print()


def print_stage(stage: str, category: str, message: str, elapsed: float):
    color = {"OBSERVE": "cyan", "ANALYZE": "yellow", "REVIEW": "blue", "ACT": "green", "ALERT": "magenta"}.get(
        category, "white"
    )
    console.print(f"  [bold {color}]{category}[/bold {color}]  {stage:<42} [{elapsed:.1f}s]")
    for line in message.split("\n"):
        if line.strip():
            console.print(f"  [dim]┊[/dim] {line}")
    console.print()


def print_after_summary(scenario, total_time: float, state: dict):
    story = scenario.get_before_story()
    console.print(f"  [dim]─────────────────────────────────────[/dim]")
    console.print(
        f"  [bold green]TOTAL TIME: {total_time:.1f} seconds[/bold green] | "
        f"MTTR: <1 minute | Human involvement: "
        f"{'NONE' if state.get('action_decision') == 'auto_execute' else 'APPROVAL REQUIRED'}"
    )
    console.print()
    console.print(Panel(
        f"[bold red]BEFORE:[/bold red] {story.total_mttr_minutes} min, "
        f"{story.manual_steps} manual steps, engineer woken up\n"
        f"[bold green]AFTER:[/bold green]  {total_time:.1f} sec, fully automated, engineer sleeps\n"
        f"[bold white]IMPROVEMENT: "
        f"{(1 - total_time / (story.total_mttr_minutes * 60)) * 100:.1f}% MTTR reduction[/bold white]",
        border_style="bright_green",
        padding=(1, 4),
    ))


async def run_scenario(scenario_name: str, use_mock_llm: bool = False) -> None:
    import os

    from backend.app.agents.graph import build_graph
    from backend.app.providers.factory import create_providers

    scenario = load_scenario(scenario_name)

    print_header()
    console.print(
        f"\n[bold]SCENARIO:[/bold] {scenario.get_display_name()}\n"
        f"[bold]SERVICE:[/bold]  {scenario.get_affected_service()} (ShopFast E-Commerce)\n"
    )

    print_before_story(scenario)

    console.print("[bold green]━━━ AFTER (Reflex) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold green]")
    console.print()

    providers = create_providers(mode="mock", scenario=scenario)

    # Use real LLM if API key available, otherwise mock
    if use_mock_llm or not os.environ.get("ANTHROPIC_API_KEY"):
        from mock.providers.mock_llm import MockLLM
        llm = MockLLM()
        if not use_mock_llm:
            console.print("  [dim]No ANTHROPIC_API_KEY found — using mock LLM[/dim]\n")
    else:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)

    graph = build_graph(providers, llm)

    alert = scenario.get_alert_payload()
    initial_state = {"alarm": alert}

    total_start = time.time()
    stage_start = time.time()

    # Run the pipeline
    final_state = {}
    async for event in graph.astream(initial_state):
        for node_name, node_state in event.items():
            elapsed = time.time() - stage_start
            stage_start = time.time()
            final_state.update(node_state)

            if node_name == "intake":
                desc = alert.get("annotations", {}).get("description", "Alert received")
                print_stage(
                    "Alert received",
                    "OBSERVE",
                    f"{alert['labels'].get('alertname', '')} on {node_state.get('service', '')}\n{desc}",
                    elapsed,
                )

            elif node_name == "noise":
                is_noise = node_state.get("is_noise", False)
                if is_noise:
                    print_stage("Known issue detected", "ANALYZE", node_state.get("noise_reason", ""), elapsed)
                else:
                    print_stage("Checking for noise/known issues...", "ANALYZE",
                                "Not noise — no maintenance window, no matching open ticket", elapsed)

            elif node_name == "rca":
                root_cause = node_state.get("root_cause", "")
                confidence = node_state.get("confidence", 0)
                signals = node_state.get("confidence_signals", {})
                evidence = node_state.get("evidence", [])
                tickets = node_state.get("matching_tickets", [])
                rb_id = node_state.get("matching_runbook_id", "")

                # Knowledge retrieval summary
                knowledge_msg = ""
                if rb_id:
                    knowledge_msg += f"Runbook found: {rb_id}\n"
                if tickets:
                    knowledge_msg += f"{len(tickets)} similar past incidents:\n"
                    for t in tickets[:3]:
                        knowledge_msg += f"  {t['key']}: {t.get('summary', '')[:60]}\n"

                if knowledge_msg:
                    print_stage("Searching knowledge base...", "ANALYZE", knowledge_msg.strip(), elapsed * 0.4)

                # RCA summary
                rca_msg = (
                    f"ROOT CAUSE: {root_cause}\n\n"
                    f"CONFIDENCE: {confidence:.2f}\n"
                    f"  RAG match quality:     {signals.get('rag_match_score', 0):.2f}\n"
                    f"  Pattern match:         {'Yes' if signals.get('pattern_match') else 'No'}"
                    f" ({len(tickets)} prior incidents)\n"
                    f"  Recency:               {signals.get('recency_days', 'N/A')} days\n"
                    f"  Historical success:    {signals.get('historical_success_rate', 0):.0%}"
                )
                print_stage("Root Cause Analysis", "ANALYZE", rca_msg, elapsed * 0.6)

            elif node_name == "review":
                decision = node_state.get("action_decision", "")
                action = node_state.get("action_taken", {})
                blast = node_state.get("blast_radius", "")
                adj_conf = node_state.get("adjusted_confidence", 0)
                orig_conf = final_state.get("confidence", 0)
                adjustments = node_state.get("review_adjustments", [])
                risk = node_state.get("risk_assessment", {})
                brief = node_state.get("decision_brief")

                # Review adjustments
                if adjustments:
                    adj_msg = "Review adjustments:\n" + "\n".join(f"  {a}" for a in adjustments)
                    print_stage("Review & Risk Assessment", "REVIEW", adj_msg, elapsed * 0.5)

                # Decision
                decision_display = {
                    "auto_execute": "AUTO-EXECUTE",
                    "human_approval": "HUMAN APPROVAL REQUIRED",
                    "escalate": "ESCALATE TO ON-CALL",
                }.get(decision, decision.upper())
                msg = (
                    f"Action: {action.get('action', '')}({action.get('deployment', '')})\n"
                    f"Blast radius: {blast.upper()} "
                )
                if risk.get("base_blast_radius") != blast:
                    msg += f"(upgraded from {risk.get('base_blast_radius', '?').upper()}) "
                msg += f"| Confidence: {adj_conf:.2f}"
                if abs(adj_conf - orig_conf) > 0.001:
                    msg += f" (adjusted from {orig_conf:.2f})"
                print_stage(f"Decision: {decision_display}", "ACT", msg, elapsed * 0.3)

                # Decision brief (when human needed)
                if brief:
                    brief_msg = (
                        f"BRIEF: {brief.get('summary', '')}\n"
                        f"Risk if act: {brief.get('risk_if_act', '')}\n"
                        f"Risk if wait: {brief.get('risk_if_wait', '')}"
                    )
                    contra = brief.get("evidence_against", [])
                    if contra:
                        brief_msg += f"\nContra-indicators: {'; '.join(contra[:3])}"
                    alts = brief.get("alternatives", [])
                    if alts:
                        alt_names = [a.get("action", "") for a in alts]
                        brief_msg += f"\nAlternatives: {', '.join(alt_names)}"
                    brief_msg += f"\nRecommendation: {brief.get('recommendation', '')}"
                    print_stage("Decision Brief for Human", "REVIEW", brief_msg, elapsed * 0.2)

            elif node_name == "remediation":
                result = node_state.get("action_result")
                if result and result.get("status") == "success":
                    print_stage("Executing...", "ACT", result.get("message", "Action executed"), elapsed)

            elif node_name == "alert":
                incident_id = final_state.get("incident_id", "")
                service = final_state.get("service", "")
                root_cause_short = (final_state.get("root_cause") or "")[:80]
                confidence = final_state.get("confidence", 0)
                evidence = final_state.get("evidence", [])
                msg = (
                    f'Incident {incident_id}: {root_cause_short}...\n'
                    f'Confidence: {confidence:.0%}. Evidence: {", ".join(evidence[:4])}'
                )
                print_stage("Notification sent to #incidents", "ALERT", msg, elapsed)

    total_time = time.time() - total_start
    print_after_summary(scenario, total_time, final_state)


def list_scenarios():
    table = Table(title="Available Scenarios")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Service", style="green")
    table.add_column("Blast Radius", style="yellow")

    for name in SCENARIOS:
        s = load_scenario(name)
        table.add_row(name, s.get_description(), s.get_affected_service(), s.get_blast_radius())

    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Reflex Platform Demo")
    parser.add_argument("--scenario", default="db_pool_exhaustion",
                        help="Scenario name or 'all'")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--mock-llm", action="store_true",
                        help="Use mock LLM (no API key needed)")
    args = parser.parse_args()

    if args.list:
        list_scenarios()
        return

    if args.scenario == "all":
        for name in SCENARIOS:
            try:
                asyncio.run(run_scenario(name, use_mock_llm=args.mock_llm))
            except Exception as e:
                console.print(f"[red]Error in {name}: {e}[/red]")
            console.print("\n" + "=" * 70 + "\n")
    else:
        if args.scenario not in SCENARIOS:
            console.print(f"[red]Unknown scenario: {args.scenario}[/red]")
            console.print(f"Available: {', '.join(SCENARIOS.keys())}")
            sys.exit(1)
        asyncio.run(run_scenario(args.scenario, use_mock_llm=args.mock_llm))


if __name__ == "__main__":
    main()
