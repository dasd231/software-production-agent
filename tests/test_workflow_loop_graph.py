from __future__ import annotations

from agent.recorder import build_event_row
from agent.workflow.loop_graph import analyze_agent_loop_events, build_agent_loop_graph_spec


def test_agent_loop_graph_spec_exports_semantic_edges() -> None:
    spec = build_agent_loop_graph_spec()
    mermaid = spec.to_mermaid()
    markdown = spec.to_markdown()

    assert "flowchart TD" in mermaid
    assert "decision_policy" in mermaid
    assert "context_budget_policy" in mermaid
    assert "migration bridge" in markdown
    assert any(edge.optimization_hook == "repair_policy" for edge in spec.edges)


def test_agent_loop_events_compile_to_graph_analysis() -> None:
    rows = [
        build_event_row("loop_start", {"run_id": "r1", "goal": "demo"}, ts=1.0),
        build_event_row("plan", {"run_id": "r1", "iteration": 0, "plan_summary": {"stage": "coding"}}, ts=2.0),
        build_event_row("context_enriched", {"run_id": "r1", "iteration": 0, "summary": {"skill_hints": 1}}, ts=3.0),
        build_event_row(
            "decision_policy",
            {"run_id": "r1", "iteration": 0, "decision": {"strategy": "implement", "selected_action": "run_command"}},
            ts=4.0,
        ),
        build_event_row(
            "decide",
            {"run_id": "r1", "iteration": 0, "action_summary": {"action": "run_command"}},
            ts=5.0,
        ),
        build_event_row(
            "reward_signal",
            {"run_id": "r1", "iteration": 0, "reward": {"total": -0.2, "ok": False}},
            ts=6.0,
        ),
        build_event_row(
            "decision_trace",
            {"run_id": "r1", "iteration": 0, "trace": {"selected_action": "run_command"}},
            ts=7.0,
        ),
        build_event_row(
            "execute",
            {"run_id": "r1", "iteration": 0, "result_summary": {"action": "run_command", "ok": False}},
            ts=8.0,
        ),
        build_event_row("fix", {"run_id": "r1", "iteration": 0, "action_summary": {"action": "write_file"}}, ts=9.0),
        build_event_row(
            "execute_fix",
            {"run_id": "r1", "iteration": 0, "result_summary": {"action": "write_file", "ok": True}},
            ts=10.0,
        ),
        build_event_row(
            "stopped",
            {"run_id": "r1", "reason": "max_iterations", "result_summary": {"reason": "max_iterations"}},
            ts=11.0,
        ),
    ]

    report = analyze_agent_loop_events(rows)

    assert report.total_events == len(rows)
    assert report.run_count == 1
    assert report.iteration_count == 1
    assert report.stage_counts["coding"] == 1
    assert report.action_counts["run_command"] >= 1
    assert report.terminal_counts["stopped:max_iterations"] == 1
    assert any(metric.source == "decide" and metric.target == "reward_trace" for metric in report.transition_metrics)
    assert any(finding.title == "Stopped runs dominate finished runs" for finding in report.findings)
    assert "Agent Loop Graph Analysis" in report.to_markdown()
