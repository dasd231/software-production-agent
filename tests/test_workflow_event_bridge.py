from __future__ import annotations

import json
from pathlib import Path

from agent.recorder import build_event_row
from agent.workflow.dataset import build_route_training_examples, write_route_training_dataset
from agent.workflow.event_bridge import agent_events_to_workflow_traces, load_workflow_traces_from_agent_events
from agent.workflow.interview import build_interview_readiness_report
from agent.workflow.optimizer import WorkflowOptimizer
from agent.workflow.project_graph import build_project_workflow, default_workflow_policy
from agent.workflow.replay import replay_logged_policy
from agent.workflow.rollout import build_canary_plan
from agent.workflow.schema import WorkflowPolicy
from agent.workflow.spec import describe_compiled_workflow


def _sample_agent_events() -> list[dict]:
    return [
        build_event_row(
            "decision_policy",
            {
                "run_id": "r1",
                "iteration": 1,
                "decision": {
                    "strategy": "verify",
                    "selected_action": "production_check",
                    "selected_score": 0.9,
                    "selected_bandit_score": 0.92,
                    "candidate_actions": [{"action": "production_check"}],
                    "reason": "verify before shipping",
                },
            },
            ts=100.0,
        ),
        build_event_row(
            "execute",
            {
                "run_id": "r1",
                "iteration": 1,
                "result_summary": {
                    "action": "production_check",
                    "ok": True,
                    "duration_ms": 123,
                    "returncode": 0,
                },
            },
            ts=101.0,
        ),
        build_event_row(
            "reward_signal",
            {
                "run_id": "r1",
                "iteration": 1,
                "reward": {"total": 1.0, "ok": True, "components": {"progress": 1.0}},
            },
            ts=102.0,
        ),
        build_event_row(
            "decision_trace",
            {
                "run_id": "r1",
                "iteration": 1,
                "trace": {
                    "strategy": "verify",
                    "policy_selected_action": "production_check",
                    "selected_action": "production_check",
                    "aligned_with_policy": True,
                    "reward_after_execution": {"total": 1.0, "ok": True},
                },
            },
            ts=103.0,
        ),
    ]


def test_agent_events_convert_to_workflow_traces(tmp_path: Path) -> None:
    rows = _sample_agent_events()
    events = agent_events_to_workflow_traces(rows)

    assert len(events) == 4
    assert {event.route_key for event in events if event.route_key} >= {
        "decision_strategy",
        "execution_action",
        "reward_quality",
        "decision_action",
    }

    path = tmp_path / ".agent_events.jsonl"
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    loaded = load_workflow_traces_from_agent_events(path)
    assert len(loaded) == len(events)


def test_real_agent_events_feed_optimizer_and_interview_report() -> None:
    events = agent_events_to_workflow_traces(_sample_agent_events())
    policy = default_workflow_policy()
    report = WorkflowOptimizer(min_samples_per_route=1).analyze(events, policy)
    readiness = build_interview_readiness_report(events, base_policy=policy)

    assert report.route_stats
    assert report.proposed_policy is not None
    assert "真实 .agent_events.jsonl" in readiness.to_markdown()


def test_canary_plan_is_conservative_for_findings() -> None:
    events = agent_events_to_workflow_traces(_sample_agent_events())
    policy = default_workflow_policy()
    report = WorkflowOptimizer(min_samples_per_route=1).analyze(events, policy)
    plan = build_canary_plan(report, candidate_policy_version="candidate-v1")

    assert plan.initial_traffic_percent <= 10.0
    assert plan.guardrails
    assert any(item.metric == "avg_reward_delta" for item in plan.guardrails)


def test_logged_policy_replay_reports_coverage_and_limits() -> None:
    events = agent_events_to_workflow_traces(_sample_agent_events())
    candidate = WorkflowPolicy(
        route_weights={
            "decision_strategy": {"verify": 1.0},
            "execution_action": {"production_check": 1.0},
            "reward_quality": {"positive": 1.0},
            "decision_action": {"production_check": 1.0},
        }
    )

    report = replay_logged_policy(events, candidate_policy=candidate)

    assert report.accepted_events == report.routed_events
    assert report.coverage == 1.0
    assert report.estimated_reward_candidate > 0
    assert "Logged replay" in report.to_markdown()


def test_workflow_spec_exports_mermaid_and_interview_markdown() -> None:
    workflow = build_project_workflow(policy=default_workflow_policy())
    spec = describe_compiled_workflow(workflow)

    mermaid = spec.to_mermaid()
    markdown = spec.to_interview_markdown()

    assert "flowchart TD" in mermaid
    assert "choose_action" in mermaid
    assert "Optimization hooks" in markdown
    assert any(edge.conditional for edge in spec.edges)


def test_route_training_dataset_exports_jsonl(tmp_path: Path) -> None:
    events = agent_events_to_workflow_traces(_sample_agent_events())
    examples = build_route_training_examples(events)
    out = tmp_path / "route_policy.jsonl"
    summary = write_route_training_dataset(events, out)

    assert examples
    assert examples[0].target["task"] == "workflow_route_policy"
    assert summary.example_count == len(examples)
    assert out.exists()
    assert out.read_text(encoding="utf-8").strip()
