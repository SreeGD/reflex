"""Reflex — Visual Demo (Streamlit).

Run with: streamlit run streamlit_demo.py
"""

from __future__ import annotations

import asyncio
import time

import plotly.graph_objects as go
import streamlit as st

from mock.config import DEPENDENCY_GRAPH, SERVICES

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Reflex Platform Demo",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Scenario registry
# ---------------------------------------------------------------------------
SCENARIOS = {
    "db_pool_exhaustion": "mock.scenarios.db_pool_exhaustion",
    "payment_timeout_cascade": "mock.scenarios.payment_timeout_cascade",
    "memory_leak": "mock.scenarios.memory_leak",
    "redis_connection_storm": "mock.scenarios.redis_connection_storm",
    "slow_query_cascade": "mock.scenarios.slow_query_cascade",
}

SCENARIO_LABELS = {
    "db_pool_exhaustion": "DB Connection Pool Exhaustion",
    "payment_timeout_cascade": "Payment Gateway Timeout Cascade",
    "memory_leak": "JVM Memory Leak",
    "redis_connection_storm": "Redis Connection Storm",
    "slow_query_cascade": "Slow Query Cascade",
}


def load_scenario(name: str):
    import importlib
    mod = importlib.import_module(SCENARIOS[name])
    return mod.create_scenario()


# ---------------------------------------------------------------------------
# Helper: run async function from sync streamlit
# ---------------------------------------------------------------------------
def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Service dependency graph (Plotly)
# ---------------------------------------------------------------------------
def render_dependency_graph(affected_service: str | None = None):
    positions = {
        "api-gateway": (2, 4),
        "catalog-service": (0, 2.5),
        "cart-service": (1, 2.5),
        "order-service": (3, 2.5),
        "payment-service": (4, 1),
        "inventory-service": (1.5, 1),
        "notification-service": (3.5, 1),
    }

    edge_x, edge_y = [], []
    for src, targets in DEPENDENCY_GRAPH.items():
        sx, sy = positions[src]
        for tgt in targets:
            tx, ty = positions[tgt]
            edge_x.extend([sx, tx, None])
            edge_y.extend([sy, ty, None])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(width=1.5, color="#555"),
        hoverinfo="none",
    ))

    node_x = [positions[s][0] for s in positions]
    node_y = [positions[s][1] for s in positions]
    node_text = [SERVICES[s].display_name for s in positions]
    node_colors = [
        "#FF4B4B" if s == affected_service else "#4B8BFF"
        for s in positions
    ]

    fig.add_trace(go.Scatter(
        x=node_x, y=node_y, mode="markers+text",
        marker=dict(size=35, color=node_colors, line=dict(width=2, color="white")),
        text=node_text,
        textposition="bottom center",
        textfont=dict(size=11),
        hoverinfo="text",
    ))

    fig.update_layout(
        showlegend=False,
        margin=dict(l=10, r=10, t=10, b=10),
        height=280,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ---------------------------------------------------------------------------
# Metrics chart (Plotly)
# ---------------------------------------------------------------------------
def render_metrics_chart(scenario):
    gen = scenario.metrics_generator
    service = scenario.get_affected_service()
    now = time.time()

    # Generate 30 min of data: 15 min normal + 15 min anomaly
    start = now - 900
    end = now + 900
    step = 15

    timestamps = []
    error_rates = []
    latencies = []
    pool_values = []

    t = start
    while t <= end:
        samples = gen.generate_instant(t)
        ts_label = t - now  # relative to incident

        # Find metrics for affected service
        err = next(
            (s.value for s in samples
             if s.name == "http_errors_total" and s.labels.get("service") == service),
            0,
        )
        lat = next(
            (s.value * 1000 for s in samples
             if s.name == "http_request_duration_seconds"
             and s.labels.get("service") == service
             and s.labels.get("quantile") == "0.99"),
            0,
        )
        pool = next(
            (s.value for s in samples
             if s.name in ("db_connection_pool_active", "redis_connection_pool_active")
             and s.labels.get("service") == service),
            None,
        )

        timestamps.append(ts_label / 60)  # minutes
        error_rates.append(err)
        latencies.append(lat)
        if pool is not None:
            pool_values.append(pool)
        t += step

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=timestamps, y=latencies, name="p99 Latency (ms)",
        line=dict(color="#FF6B6B", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=timestamps, y=error_rates, name="Error Rate",
        line=dict(color="#FFA94D", width=2),
        yaxis="y2",
    ))
    if pool_values and len(pool_values) == len(timestamps):
        fig.add_trace(go.Scatter(
            x=timestamps, y=pool_values, name="Pool Active",
            line=dict(color="#4DABF7", width=2, dash="dot"),
        ))

    # Incident marker
    fig.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Alert fires")

    fig.update_layout(
        height=300,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis_title="Minutes (relative to incident)",
        yaxis_title="Latency (ms) / Pool Count",
        yaxis2=dict(title="Error Rate", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ---------------------------------------------------------------------------
# Run pipeline
# ---------------------------------------------------------------------------
async def run_pipeline(scenario):
    import os
    from backend.app.agents.graph import build_graph
    from backend.app.providers.factory import create_providers
    from mock.providers.mock_llm import MockLLM

    providers = create_providers(mode="mock", scenario=scenario)

    if os.environ.get("ANTHROPIC_API_KEY"):
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model="claude-sonnet-4-20250514", temperature=0)
    else:
        llm = MockLLM()

    graph = build_graph(providers, llm)
    alert = scenario.get_alert_payload()
    initial_state = {"alarm": alert}

    stages = []
    final_state = {}
    total_start = time.time()

    async for event in graph.astream(initial_state):
        for node_name, node_state in event.items():
            elapsed = time.time() - total_start
            final_state.update(node_state)
            stages.append((node_name, dict(node_state), elapsed))

    total_time = time.time() - total_start
    return stages, final_state, total_time, providers


# ---------------------------------------------------------------------------
# RAG Explorer — run standalone knowledge search
# ---------------------------------------------------------------------------
async def run_rag_search(scenario, query: str):
    from backend.app.providers.factory import create_providers

    providers = create_providers(mode="mock", scenario=scenario)
    results = await providers.knowledge.search_similar(query, limit=10)
    return results, providers


# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------
def main():
    # Sidebar
    with st.sidebar:
        st.image("https://img.icons8.com/fluency/96/maintenance.png", width=64)
        st.title("Reflex Platform")
        st.caption("Observe → Analyze → Act")
        st.divider()

        scenario_name = st.selectbox(
            "Select Incident Scenario",
            list(SCENARIOS.keys()),
            format_func=lambda x: SCENARIO_LABELS[x],
        )

        run_button = st.button("▶  Run Demo", type="primary", use_container_width=True)

        st.divider()
        simulate_button = st.button("🚨 Simulate SEV-2 Alarm", use_container_width=True)
        if simulate_button:
            import json
            from urllib.request import Request, urlopen
            try:
                _scenario = load_scenario(scenario_name)
                alert = _scenario.get_alert_payload()
                payload = json.dumps({"alerts": [alert]}).encode()
                req = Request(
                    "http://localhost:8000/webhook/alertmanager",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                resp = urlopen(req, timeout=120)
                result = json.loads(resp.read())
                st.success(f"Webhook processed: {len(result.get('processed', []))} incident(s)")
                for iid in result.get("processed", []):
                    st.code(iid)
            except Exception as e:
                st.error(f"Webhook failed: {e}. Is the API server running on port 8000?")

        st.divider()
        st.markdown("**How it works:**")
        st.markdown("""
        1. Alert fires from monitoring
        2. AI searches knowledge base
        3. Finds matching runbooks & past incidents
        4. Produces root cause analysis
        5. Decides: auto-fix or ask human
        6. Executes and notifies
        """)

    scenario = load_scenario(scenario_name)

    # Header
    st.markdown(f"## {scenario.get_display_name()}")
    st.markdown(f"**Affected Service:** `{scenario.get_affected_service()}` | "
                f"**Blast Radius:** `{scenario.get_blast_radius()}`")

    # Tabs
    tab_demo, tab_live, tab_rag, tab_knowledge = st.tabs([
        "Pipeline Demo",
        "Live Incidents",
        "RAG Explorer",
        "Knowledge Base",
    ])

    # ---- TAB 1: Pipeline Demo ----
    with tab_demo:
        # Top row: dependency graph + metrics
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("#### Service Dependency Map")
            st.plotly_chart(
                render_dependency_graph(scenario.get_affected_service()),
                use_container_width=True,
            )
        with col2:
            st.markdown("#### Metrics (Anomaly Injection)")
            st.plotly_chart(
                render_metrics_chart(scenario),
                use_container_width=True,
            )

        st.divider()

        col_before, col_after = st.columns(2)

        with col_before:
            st.markdown("### Before (Manual Ops)")
            story = scenario.get_before_story()
            for time_str, desc in story.steps:
                st.markdown(f"- **{time_str}** — {desc}")
            st.error(f"**MTTR: {story.total_mttr_minutes} min** | "
                     f"{story.manual_steps} manual steps | Engineer woken up")

        with col_after:
            st.markdown("### After (Reflex)")

            if not run_button and "pipeline_result" not in st.session_state:
                st.info("Click **Run Demo** in the sidebar to see the AI in action")
            else:
                if run_button:
                    with st.spinner("Running Reflex pipeline..."):
                        stages, final_state, total_time, providers = run_async(
                            run_pipeline(scenario)
                        )
                        st.session_state["pipeline_result"] = (
                            stages, final_state, total_time, scenario_name, providers
                        )

                if "pipeline_result" in st.session_state:
                    cached = st.session_state["pipeline_result"]
                    if cached[3] != scenario_name:
                        del st.session_state["pipeline_result"]
                        st.info("Click **Run Demo** in the sidebar")
                    else:
                        stages, final_state, total_time = cached[0], cached[1], cached[2]
                        _render_pipeline_results(stages, final_state, total_time, scenario)

        # MTTR comparison
        if "pipeline_result" in st.session_state and st.session_state["pipeline_result"][3] == scenario_name:
            cached = st.session_state["pipeline_result"]
            st.divider()
            _render_mttr_comparison(scenario, cached[2], cached[1])

    # ---- TAB 2: Live Incidents ----
    with tab_live:
        st.markdown("#### Live Incident Feed")
        st.caption("Incidents received via webhook or chat analysis. Click 'Simulate SEV-2 Alarm' in the sidebar to send one.")

        import json
        from urllib.request import Request, urlopen

        try:
            resp = urlopen("http://localhost:8000/incidents", timeout=5)
            incidents = json.loads(resp.read())
        except Exception:
            incidents = []

        if not incidents:
            st.info("No incidents yet. Use the **Simulate SEV-2 Alarm** button in the sidebar, or send a webhook via curl.")
        else:
            for inc in incidents:
                severity_icon = {"critical": "🔴", "warning": "🟡"}.get(inc.get("severity", ""), "⚪")
                decision_icon = {
                    "auto_execute": "✅",
                    "human_approval": "🟡",
                    "escalate": "🔴",
                }.get(inc.get("action_decision", ""), "⚪")

                with st.expander(
                    f"{severity_icon} **{inc['incident_id']}** | "
                    f"`{inc.get('service', '?')}` | "
                    f"{decision_icon} {inc.get('action_decision', '?')} | "
                    f"confidence: {inc.get('confidence', 0):.2f}"
                ):
                    col_a, col_b = st.columns(2)
                    col_a.metric("Confidence", f"{inc.get('confidence', 0):.2f}")
                    col_b.metric("Blast Radius", inc.get("blast_radius", "?"))
                    st.markdown(f"**Root Cause:** {inc.get('root_cause', 'N/A')}")
                    st.markdown(f"**Source:** {inc.get('source', '?')}")

            if st.button("🔄 Refresh"):
                st.rerun()

    # ---- TAB 3: RAG Explorer ----
    with tab_rag:
        _render_rag_explorer(scenario)

    # ---- TAB 3: Knowledge Base Browser ----
    with tab_knowledge:
        _render_knowledge_browser()


# ---------------------------------------------------------------------------
# RAG Explorer tab
# ---------------------------------------------------------------------------
def _render_rag_explorer(scenario):
    st.markdown("### RAG Explorer")
    st.markdown(
        "See exactly what the AI retrieves from the knowledge base for any query. "
        "This is the same retrieval that powers the RCA node."
    )

    # Pre-fill with the scenario's alert context
    alert = scenario.get_alert_payload()
    service = alert.get("labels", {}).get("service", "")
    alert_name = alert.get("labels", {}).get("alertname", "")
    description = alert.get("annotations", {}).get("description", "")
    default_query = f"{service} {alert_name} {description}"

    query = st.text_area(
        "Search query (edit to explore different queries):",
        value=default_query,
        height=80,
    )

    col_types, col_limit = st.columns([3, 1])
    with col_types:
        source_types = st.multiselect(
            "Source types:",
            ["runbook", "jira", "confluence"],
            default=["runbook", "jira", "confluence"],
        )
    with col_limit:
        limit = st.number_input("Max results:", min_value=1, max_value=20, value=10)

    if st.button("Search Knowledge Base", type="primary"):
        with st.spinner("Searching..."):
            results, providers = run_async(run_rag_search(scenario, query))

        if not results:
            st.warning("No results found.")
        else:
            st.success(f"Found **{len(results)}** matching knowledge chunks")

            # Results visualization
            _render_rag_results(results, providers, source_types, limit)

    # Show pipeline RAG results if pipeline has been run
    if "pipeline_result" in st.session_state:
        cached = st.session_state["pipeline_result"]
        if cached[3] == scenario.get_name():
            final_state = cached[1]
            st.divider()
            st.markdown("### Pipeline RAG Results (from last run)")
            _render_pipeline_rag_detail(final_state)


def _render_rag_results(results, providers, source_types, limit):
    """Render RAG search results with scores and expandable content."""
    # Score chart
    filtered = [r for r in results if r["source_type"] in source_types][:limit]

    if filtered:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=[f"{r['source_type']}/{r['source_id']}" for r in filtered],
            y=[r["score"] for r in filtered],
            marker_color=[
                {"runbook": "#4DABF7", "jira": "#FFA94D", "confluence": "#69DB7C"}
                .get(r["source_type"], "#888")
                for r in filtered
            ],
            text=[f"{r['score']:.2f}" for r in filtered],
            textposition="outside",
        ))
        fig.update_layout(
            height=250,
            margin=dict(l=10, r=10, t=10, b=10),
            yaxis_title="Relevance Score",
            xaxis_tickangle=-30,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # Detailed results
    for i, result in enumerate(filtered):
        source_type = result["source_type"]
        source_id = result["source_id"]
        score = result["score"]
        title = result.get("title", source_id)

        icon = {"runbook": "📋", "jira": "🎫", "confluence": "📄"}.get(source_type, "📝")
        color = {"runbook": "blue", "jira": "orange", "confluence": "green"}.get(source_type, "gray")

        with st.expander(
            f"{icon} **{source_type.upper()}** — {source_id}: {title} (score: {score:.2f})",
            expanded=(i == 0),
        ):
            # Show metadata
            meta = result.get("metadata", {})
            if meta:
                meta_cols = st.columns(4)
                for j, (k, v) in enumerate(list(meta.items())[:4]):
                    if v is not None:
                        meta_cols[j].markdown(f"**{k}:** {v}")

            st.markdown("---")

            # Show full content
            if source_type == "runbook":
                full = run_async(providers.knowledge.get_runbook(source_id))
                if full:
                    st.markdown(full)
                else:
                    st.code(result.get("content", ""), language="markdown")
            elif source_type == "jira":
                ticket = run_async(providers.knowledge.get_ticket(source_id))
                if ticket:
                    st.markdown(f"**Summary:** {ticket.get('summary', '')}")
                    st.markdown(f"**Status:** {ticket.get('status', '')} | "
                                f"**Priority:** {ticket.get('priority', '')} | "
                                f"**Assignee:** {ticket.get('assignee', '')}")
                    st.markdown(f"**Created:** {ticket.get('created', '')} | "
                                f"**Resolved:** {ticket.get('resolved', '')}")
                    st.markdown(f"**Labels:** {', '.join(ticket.get('labels', []))}")
                    if ticket.get("description"):
                        st.markdown("**Description:**")
                        st.markdown(ticket["description"])
                    if ticket.get("resolution_notes"):
                        st.markdown("**Resolution Notes:**")
                        st.markdown(ticket["resolution_notes"])
                    if ticket.get("linked_runbook"):
                        st.markdown(f"**Linked Runbook:** `{ticket['linked_runbook']}`")
                else:
                    st.code(result.get("content", ""))
            else:
                st.markdown(result.get("content", ""))


def _render_pipeline_rag_detail(final_state):
    """Show the RAG context that was actually used in the pipeline run."""

    # What was retrieved
    rb_id = final_state.get("matching_runbook_id")
    tickets = final_state.get("matching_tickets", [])
    docs = final_state.get("matching_docs", [])
    logs = final_state.get("recent_error_logs", [])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Runbook", rb_id or "None")
    col2.metric("Jira Tickets", str(len(tickets)))
    col3.metric("Confluence Docs", str(len(docs)))
    col4.metric("Error Logs", str(len(logs)))

    # Show the assembled LLM context
    with st.expander("LLM Context (what was sent to the AI)", expanded=False):
        alert = final_state.get("alarm", {})
        alert_name = alert.get("labels", {}).get("alertname", "")
        service = final_state.get("service", "")
        description = alert.get("annotations", {}).get("description", "")

        context = f"**ALERT:** {alert_name} on {service}\n{description}\n\n"

        if rb_id and final_state.get("matching_runbook"):
            context += f"**MATCHING RUNBOOK ({rb_id}):**\n"
            context += final_state["matching_runbook"][:1500] + "\n\n"

        if tickets:
            context += "**SIMILAR PAST INCIDENTS:**\n"
            for t in tickets[:3]:
                context += f"- {t['key']}: {t['summary']}\n"
                context += f"  Resolution: {t.get('resolution_notes', 'N/A')[:300]}\n\n"

        if logs:
            context += "**RECENT ERROR LOGS:**\n"
            for log in logs[:5]:
                context += f"- [{log.get('timestamp', '')}] {log.get('message', '')}\n"

        st.markdown(context)

    # Show the LLM response
    with st.expander("LLM Response (AI analysis)", expanded=True):
        st.markdown(f"> {final_state.get('root_cause', 'N/A')}")

        signals = final_state.get("confidence_signals", {})
        evidence = final_state.get("evidence", [])

        st.markdown(f"**Confidence:** {final_state.get('confidence', 0):.0%}")
        st.markdown(f"**Evidence:** {', '.join(evidence)}")
        st.json(signals)


# ---------------------------------------------------------------------------
# Knowledge Base Browser tab
# ---------------------------------------------------------------------------
def _render_knowledge_browser():
    from mock.providers.knowledge import MockKnowledgeProvider

    provider = MockKnowledgeProvider()
    st.markdown("### Knowledge Base Browser")
    st.markdown("Browse all runbooks, Jira tickets, and Confluence docs in the system.")

    kb_tab1, kb_tab2, kb_tab3 = st.tabs(["Runbooks", "Jira Tickets", "Confluence Docs"])

    with kb_tab1:
        st.markdown(f"**{len(provider._runbooks)} runbooks loaded**")
        for rb_id, content in sorted(provider._runbooks.items()):
            title = content.split("\n")[0].replace("# ", "").strip() if content else rb_id
            with st.expander(f"📋 {rb_id}: {title}"):
                st.markdown(content)

    with kb_tab2:
        st.markdown(f"**{len(provider._tickets)} incident tickets loaded**")
        for ticket in provider._tickets:
            key = ticket.get("key", "")
            summary = ticket.get("summary", "")
            status = ticket.get("status", "")
            priority = ticket.get("priority", "")
            with st.expander(f"🎫 {key}: {summary} [{status}] [{priority}]"):
                col1, col2 = st.columns(2)
                col1.markdown(f"**Created:** {ticket.get('created', '')}")
                col2.markdown(f"**Resolved:** {ticket.get('resolved', '')}")
                col1.markdown(f"**Assignee:** {ticket.get('assignee', '')}")
                col2.markdown(f"**Linked Runbook:** `{ticket.get('linked_runbook', 'N/A')}`")
                st.markdown(f"**Labels:** {', '.join(ticket.get('labels', []))}")
                if ticket.get("description"):
                    st.markdown("**Description:**")
                    st.markdown(ticket["description"])
                if ticket.get("resolution_notes"):
                    st.markdown("**Resolution Notes:**")
                    st.markdown(ticket["resolution_notes"])

    with kb_tab3:
        st.markdown(f"**{len(provider._confluence)} pages loaded**")
        for page_id, content in sorted(provider._confluence.items()):
            title = content.split("\n")[0].replace("# ", "").strip() if content else page_id
            with st.expander(f"📄 {page_id}: {title}"):
                st.markdown(content)


def _render_pipeline_results(stages, final_state, total_time, scenario):
    """Render pipeline stages in the After column."""
    for node_name, state, elapsed in stages:
        if node_name == "intake":
            alert = state.get("alarm", {})
            st.success(f"**OBSERVE** — Alert received ({elapsed:.1f}s)")
            st.code(
                f"{alert.get('labels', {}).get('alertname', '')}\n"
                f"{alert.get('annotations', {}).get('description', '')}",
                language=None,
            )

        elif node_name == "noise":
            if state.get("is_noise"):
                st.warning(f"**ANALYZE** — Known issue: {state.get('noise_reason')}")
            else:
                st.info(f"**ANALYZE** — Not noise, proceeding to analysis ({elapsed:.1f}s)")

        elif node_name == "rca":
            st.info(f"**ANALYZE** — Root Cause Analysis ({elapsed:.1f}s)")

            # Knowledge retrieval
            rb_id = state.get("matching_runbook_id")
            tickets = state.get("matching_tickets", [])
            if rb_id or tickets:
                with st.expander("📚 Knowledge Retrieved", expanded=True):
                    if rb_id:
                        st.markdown(f"**Runbook:** `{rb_id}`")
                    if tickets:
                        st.markdown(f"**{len(tickets)} similar past incidents:**")
                        for t in tickets[:3]:
                            st.markdown(f"- `{t['key']}`: {t.get('summary', '')[:80]}")

            # RCA
            st.markdown(f"> {state.get('root_cause', '')}")

            # Confidence
            confidence = state.get("confidence", 0)
            signals = state.get("confidence_signals", {})
            col_c1, col_c2, col_c3, col_c4 = st.columns(4)
            col_c1.metric("Confidence", f"{confidence:.0%}")
            col_c2.metric("RAG Match", f"{signals.get('rag_match_score', 0):.2f}")
            col_c3.metric("Pattern Match", "Yes" if signals.get("pattern_match") else "No")
            col_c4.metric("Recency", f"{signals.get('recency_days', 'N/A')}d")

        elif node_name == "review":
            decision = state.get("action_decision", "")
            action = state.get("action_taken", {})
            blast = state.get("blast_radius", "")
            adj_conf = state.get("adjusted_confidence", 0)
            adjustments = state.get("review_adjustments", [])
            risk = state.get("risk_assessment", {})
            brief = state.get("decision_brief")

            # Review adjustments
            if adjustments:
                with st.expander("Review & Risk Assessment", expanded=True):
                    for adj in adjustments:
                        st.markdown(f"- {adj}")

                    # Risk factors visualization
                    risk_factors = risk.get("risk_factors", [])
                    if risk_factors:
                        rf_names = [rf["name"] for rf in risk_factors]
                        rf_deltas = [rf["risk_delta"] for rf in risk_factors]
                        rf_colors = ["#FF6B6B" if d > 0 else "#40C057" for d in rf_deltas]
                        fig = go.Figure(go.Bar(
                            x=rf_names, y=rf_deltas,
                            marker_color=rf_colors,
                            text=[f"{d:+.2f}" for d in rf_deltas],
                            textposition="outside",
                        ))
                        fig.update_layout(
                            height=200, margin=dict(l=10, r=10, t=10, b=10),
                            yaxis_title="Risk Delta",
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                        )
                        st.plotly_chart(fig, use_container_width=True)

            # Decision
            action_desc = f"`{action.get('action', '')}({action.get('deployment', '')})`"
            blast_note = ""
            if risk.get("base_blast_radius") != blast:
                blast_note = f" (upgraded from {risk.get('base_blast_radius', '?')})"

            if decision == "auto_execute":
                st.success(f"**AUTO-EXECUTE:** {action_desc} | "
                          f"Blast: {blast.upper()}{blast_note} | "
                          f"Confidence: {adj_conf:.0%}")
            elif decision == "human_approval":
                st.warning(f"**HUMAN APPROVAL REQUIRED:** {action_desc} | "
                          f"Blast: {blast.upper()}{blast_note} | "
                          f"Confidence: {adj_conf:.0%}")
            else:
                st.error(f"**ESCALATE TO ON-CALL** | Blast: {blast.upper()}")

            # Decision brief
            if brief:
                with st.expander("Decision Brief for Human Approver", expanded=True):
                    st.markdown(f"**Summary:** {brief.get('summary', '')}")
                    col_r1, col_r2 = st.columns(2)
                    col_r1.error(f"**Risk if act:** {brief.get('risk_if_act', '')}")
                    col_r2.warning(f"**Risk if wait:** {brief.get('risk_if_wait', '')}")

                    evidence_for = brief.get("evidence_for", [])
                    evidence_against = brief.get("evidence_against", [])
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        st.markdown("**Evidence for:**")
                        for e in evidence_for:
                            st.markdown(f"- {e}")
                    with col_e2:
                        st.markdown("**Contra-indicators:**")
                        for e in evidence_against:
                            st.markdown(f"- {e}")

                    st.markdown(f"**Recommendation:** {brief.get('recommendation', '')}")
                    st.markdown(f"**Estimated TTR:** {brief.get('estimated_ttr_minutes', '?')} minutes")

                    alts = brief.get("alternatives", [])
                    if alts:
                        st.markdown("**Alternatives:**")
                        for a in alts:
                            st.markdown(f"- `{a.get('action', '')}` — {a.get('reason', '')}")

        elif node_name == "remediation":
            result = state.get("action_result")
            if result and result.get("status") == "success":
                st.success(f"**EXECUTE** — {result.get('message', 'Done')}")

        elif node_name == "alert":
            st.info("**ALERT** — Notification sent to `#incidents`")


def _render_mttr_comparison(scenario, total_time, final_state):
    """Render the big MTTR comparison at the bottom."""
    story = scenario.get_before_story()
    before_seconds = story.total_mttr_minutes * 60
    improvement = (1 - total_time / before_seconds) * 100 if before_seconds > 0 else 100

    st.markdown("### 📊 Impact Summary")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Before MTTR", f"{story.total_mttr_minutes} min")
    col2.metric("After MTTR", f"{max(total_time, 0.1):.1f} sec", f"-{improvement:.0f}%")
    col3.metric("Manual Steps Eliminated", f"{story.manual_steps}", f"-{story.manual_steps}")
    decision = final_state.get("action_decision", "")
    col4.metric("Human Involvement",
                "None" if decision == "auto_execute" else "Approval Only")

    # Bar chart comparison
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Before (Manual)"], y=[story.total_mttr_minutes * 60],
        name="Manual Ops", marker_color="#FF4B4B", text=[f"{story.total_mttr_minutes} min"],
        textposition="outside",
    ))
    fig.add_trace(go.Bar(
        x=["After (Reflex)"], y=[max(total_time, 0.5)],
        name="Reflex", marker_color="#40C057", text=[f"{max(total_time, 0.1):.1f} sec"],
        textposition="outside",
    ))
    fig.update_layout(
        height=250,
        margin=dict(l=10, r=10, t=30, b=10),
        yaxis_title="Time (seconds)",
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
