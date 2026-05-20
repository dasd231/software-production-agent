from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, run_action, run_action_guarded
from agent.core.protocol import parse_and_validate_action_line
from agent.software_middle_model import (
    MiddleModelDatasetExportInput,
    MiddleModelInput,
    MiddleModelServerHandoffInput,
    append_middle_model_trace,
    build_middle_model_trace,
    build_software_middle_model_plan,
    decide_with_middle_model,
    export_middle_model_trace_dataset,
    load_middle_model_traces,
    prepare_middle_model_server_handoff,
)


def test_software_middle_model_plan_is_cpu_first_and_independent() -> None:
    plan = build_software_middle_model_plan()

    assert plan["schema"] == "software_middle_model_plan.v1"
    assert plan["safety_policy"]["default_backend"] == "deterministic_cpu_fallback"
    assert "does not launch GPU training by default" in plan["positioning"]["non_goals"]
    assert plan["interfaces"]["decision_action"] == "software_middle_model_decide"


def test_middle_model_shortcuts_high_confidence_low_risk_candidates() -> None:
    decision = decide_with_middle_model(
        MiddleModelInput(
            task="evidence_selection",
            features={"risk": "low"},
            candidates=(
                {"id": "fast_good", "quality_score": 0.94, "rule_cost_ms": 20},
                {"id": "slow_weaker", "quality_score": 0.70, "rule_cost_ms": 500},
            ),
            confidence_threshold=0.78,
            margin_threshold=0.12,
            rule_budget_ms=250,
        )
    )

    assert decision["schema"] == "software_middle_model_decision.v1"
    assert decision["decision"]["recommended_mode"] == "small_model_shortcut"
    assert decision["decision"]["should_run_expensive_rules"] is False
    assert decision["decision"]["selected_candidate_id"] == "fast_good"
    assert decision["ranked_candidates"][0]["id"] == "fast_good"


def test_middle_model_falls_back_for_high_risk_tasks() -> None:
    decision = decide_with_middle_model(
        {
            "task": "security_sensitive_rule",
            "features": {"security_sensitive": True},
            "candidates": [{"id": "apparently_good", "quality_score": 0.99, "rule_cost_ms": 10}],
        }
    )

    assert decision["decision"]["recommended_mode"] == "run_expensive_rules"
    assert decision["decision"]["should_run_expensive_rules"] is True
    assert decision["decision"]["reason"] == "high_risk_requires_rule_verification"


def _append_demo_trace(path: Path, *, suffix: str, quality: float = 0.9) -> None:
    middle_input = MiddleModelInput(
        task="repo_routing",
        features={"risk": "low", "source": suffix},
        candidates=(
            {"id": f"train_now_{suffix}", "quality_score": quality, "rule_cost_ms": 25},
            {"id": f"manual_review_{suffix}", "quality_score": 0.62, "rule_cost_ms": 420},
        ),
    )
    decision = decide_with_middle_model(middle_input)
    trace = build_middle_model_trace(
        middle_input,
        decision,
        final_accepted=True,
        latency_saved_ms=300,
        quality_delta=0.02,
        source_trace_id=f"run-{suffix}",
        outcome={"grade": "accepted"},
    )
    append_middle_model_trace(path, trace)


def test_middle_model_trace_build_append_and_load(tmp_path: Path) -> None:
    trace_path = tmp_path / "middle" / "traces.jsonl"
    _append_demo_trace(trace_path, suffix="one")
    rows = load_middle_model_traces(trace_path)

    assert len(rows) == 1
    assert rows[0]["schema"] == "software_middle_model_trace.v1"
    assert rows[0]["source_trace_id"] == "run-one"
    assert rows[0]["labels"]["final_accepted"] is True
    assert rows[0]["labels"]["selected_candidate_id"] == "train_now_one"
    assert rows[0]["outcome"]["grade"] == "accepted"


def test_middle_model_trace_dataset_export_and_server_handoff(tmp_path: Path) -> None:
    trace_path = tmp_path / "middle" / "traces.jsonl"
    for suffix in ("one", "two", "three"):
        _append_demo_trace(trace_path, suffix=suffix)

    dataset = export_middle_model_trace_dataset(
        MiddleModelDatasetExportInput(
            trace_paths=(trace_path,),
            output_dir=tmp_path / "training" / "middle",
            eval_ratio=0.34,
            min_traces=3,
            max_examples=10,
        )
    )
    handoff = prepare_middle_model_server_handoff(
        MiddleModelServerHandoffInput(
            training_dir=Path(dataset.output_dir),
            output_dir=tmp_path / "model" / "middle",
            min_train_examples=1,
            max_seq_length=512,
        )
    )

    assert dataset.validation["ok"] is True
    assert dataset.manifest["counts"]["train_examples"] >= 1
    assert Path(dataset.files["train"]).exists()
    assert Path(dataset.files["eval"]).exists()
    assert Path(dataset.files["dataset_snapshot_manifest"]).exists()
    assert handoff.handoff_ready is True
    assert Path(handoff.files["server_handoff"]).exists()
    assert Path(handoff.files["launch_command"]).exists()
    assert Path(handoff.files["training_resource_policy"]).exists()


def test_software_middle_model_actions_dispatch_and_can_write_trace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    plan = run_action(ws, {"type": "action", "action": "software_middle_model_plan", "args": {}})
    decision = run_action(
        ws,
        {
            "type": "action",
            "action": "software_middle_model_decide",
            "args": {
                "task": "repo_routing",
                "features": {"risk": "low"},
                "candidates": [
                    {"id": "train_now", "quality_score": 0.9, "rule_cost_ms": 25},
                    {"id": "manual_review", "quality_score": 0.66, "rule_cost_ms": 400},
                ],
                "trace_output_path": "middle_model/traces.jsonl",
                "final_accepted": True,
                "latency_saved_ms": 100,
                "quality_delta": 0.0,
                "source_trace_id": "executor-test",
                "outcome": {"grade": "accepted"},
            },
        },
    )
    traces = load_middle_model_traces(ws / "middle_model" / "traces.jsonl")

    assert plan["ok"] is True
    assert plan["plan"]["schema"] == "software_middle_model_plan.v1"
    assert decision["ok"] is True
    assert decision["decision"]["decision"]["selected_candidate_id"] == "train_now"
    assert decision["trace"]["schema"] == "software_middle_model_trace.v1"
    assert len(traces) == 1
    assert traces[0]["labels"]["final_accepted"] is True


def test_software_middle_model_dataset_and_handoff_actions_dispatch(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    for suffix in ("one", "two", "three"):
        _append_demo_trace(ws / "middle_model" / "traces.jsonl", suffix=suffix)

    dataset = run_action(
        ws,
        {
            "type": "action",
            "action": "software_middle_model_dataset_export",
            "args": {
                "trace_paths": ["middle_model/traces.jsonl"],
                "output_dir": "training_runs/middle-first",
                "eval_ratio": 0.34,
                "min_traces": 3,
            },
        },
    )
    handoff = run_action(
        ws,
        {
            "type": "action",
            "action": "software_middle_model_server_handoff",
            "args": {
                "training_dir": "training_runs/middle-first",
                "output_dir": "model_runs/middle-first",
                "min_train_examples": 1,
                "max_seq_length": 512,
            },
        },
    )

    assert dataset["ok"] is True
    assert dataset["manifest"]["schema"] == "software_middle_model_dataset_manifest.v1"
    assert handoff["ok"] is True
    assert handoff["handoff_ready"] is True
    assert Path(handoff["files"]["server_handoff"]).exists()


def test_software_middle_model_protocol_and_guarded_permissions(tmp_path: Path) -> None:
    parsed = parse_and_validate_action_line(
        '{"type":"action","action":"software_middle_model_decide","args":{"task":"x","candidates":[],"trace_output_path":"traces.jsonl"}}'
    )
    parsed_export = parse_and_validate_action_line(
        '{"type":"action","action":"software_middle_model_dataset_export","args":{"trace_paths":["traces.jsonl"],"output_dir":"out"}}'
    )
    assert parsed["action"] == "software_middle_model_decide"
    assert parsed_export["action"] == "software_middle_model_dataset_export"

    ws = tmp_path / "ws"
    ws.mkdir()
    allowed = run_action_guarded(
        ws,
        {"type": "action", "action": "software_middle_model_plan", "args": {}},
        limits=ExecutionLimits(granted_permissions=frozenset({"model:read"})),
    )
    allowed_decide = run_action_guarded(
        ws,
        {"type": "action", "action": "software_middle_model_decide", "args": {"task": "x", "candidates": []}},
        limits=ExecutionLimits(granted_permissions=frozenset({"model:route", "workspace:write"})),
    )
    blocked_handoff = run_action_guarded(
        ws,
        {
            "type": "action",
            "action": "software_middle_model_server_handoff",
            "args": {"training_dir": "training", "output_dir": "model"},
        },
        limits=ExecutionLimits(granted_permissions=frozenset({"dataset:read", "model:write"})),
    )
    blocked = run_action_guarded(
        ws,
        {"type": "action", "action": "software_middle_model_decide", "args": {"task": "x", "candidates": []}},
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )

    assert allowed["ok"] is True
    assert allowed_decide["ok"] is True
    assert blocked_handoff["ok"] is False
    assert blocked_handoff["error_code"] == "CONFIRMATION_REQUIRED"
    assert blocked["ok"] is False
    assert blocked["error_code"] == "PERMISSION_DENIED"
