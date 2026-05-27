from __future__ import annotations

import json
from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.local_training import run_local_training


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_local_training_trains_middle_and_github_cpu_models(tmp_path: Path) -> None:
    traces = tmp_path / "middle_traces.jsonl"
    rankings = tmp_path / "ranking.jsonl"
    _write_jsonl(
        traces,
        [
            {
                "trace_id": "t1",
                "features": {"risk": "low"},
                "ranked_candidates": [{"id": "a"}, {"id": "b"}],
                "decision": {"confidence": 0.91, "margin": 0.3, "risk_signal": 0.1, "should_run_expensive_rules": False},
                "labels": {"should_run_expensive_rules": False, "final_accepted": True, "latency_saved_ms": 120, "quality_delta": 0.1},
            },
            {
                "trace_id": "t2",
                "features": {"risk": "high"},
                "ranked_candidates": [{"id": "a"}],
                "decision": {"confidence": 0.42, "margin": 0.02, "risk_signal": 0.9, "should_run_expensive_rules": True},
                "labels": {"should_run_expensive_rules": True, "final_accepted": False, "latency_saved_ms": 0, "quality_delta": -0.2},
            },
        ],
    )
    _write_jsonl(
        rankings,
        [
            {
                "routes": ["train_now"],
                "scores": {
                    "lexical_relevance": 8,
                    "repo_quality": 9,
                    "freshness": 7,
                    "governance": 9,
                    "novelty": 5,
                    "downstream_utility": 8,
                },
            },
            {
                "routes": ["quarantine"],
                "scores": {
                    "lexical_relevance": 2,
                    "repo_quality": 2,
                    "freshness": 3,
                    "governance": 0,
                    "novelty": 4,
                    "downstream_utility": 1,
                },
            },
        ],
    )

    manifest = run_local_training(
        target="both",
        output_dir=tmp_path / "out",
        middle_trace_paths=(traces,),
        github_ranking_paths=(rankings,),
        epochs=5,
    )

    assert manifest["results"]["middle_model"]["status"] == "trained"
    assert manifest["results"]["github_evaluator"]["status"] == "trained"
    assert (tmp_path / "out" / "middle_model_local.json").exists()
    assert (tmp_path / "out" / "github_evaluator_local.json").exists()


def test_local_training_action_respects_confirmation_and_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"local_training_run","args":'
        '{"target":"both","output_dir":"local-train","epochs":3}}'
    )
    denied_confirmation = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"model:train", "workspace:write"})),
    )
    assert denied_confirmation["ok"] is False
    assert denied_confirmation["error_code"] == "CONFIRMATION_REQUIRED"

    allowed = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(
            granted_permissions=frozenset({"model:train", "workspace:write"}),
            confirmed_actions=frozenset({"local_training_run"}),
        ),
    )
    assert allowed["ok"] is True
    assert allowed["summary"]["middle_status"] == "needs_data"
    assert (tmp_path / "local-train" / "local_training_manifest.json").exists()


def test_local_training_writes_extracted_examples_and_quality_eval(tmp_path: Path) -> None:
    from agent.local_training import write_demo_local_training_data

    data_paths = write_demo_local_training_data(tmp_path / "demo")
    manifest = run_local_training(
        target="both",
        output_dir=tmp_path / "out2",
        middle_trace_paths=(Path(data_paths["middle_trace_path"]),),
        github_ranking_paths=(Path(data_paths["github_ranking_path"]),),
        epochs=8,
    )

    assert manifest["schema"] == "local_training_manifest.v2"
    assert manifest["quality_evaluation"]["schema"] == "model_training_quality_evaluation.v1"
    assert (tmp_path / "out2" / "middle_model_examples.jsonl").exists()
    assert (tmp_path / "out2" / "github_evaluator_examples.jsonl").exists()
    middle = json.loads((tmp_path / "out2" / "middle_model_local.json").read_text(encoding="utf-8"))
    github = json.loads((tmp_path / "out2" / "github_evaluator_local.json").read_text(encoding="utf-8"))
    assert "must_have_coverage" in middle["feature_names"]
    assert "license_signal" in github["feature_names"]


def test_local_training_inference_applies_hard_gates(tmp_path: Path) -> None:
    from agent.local_training import classify_middle_decision, score_github_repo, write_demo_local_training_data
    from agent.local_training.inference import load_local_model

    data_paths = write_demo_local_training_data(tmp_path / "demo")
    run_local_training(
        target="both",
        output_dir=tmp_path / "out3",
        middle_trace_paths=(Path(data_paths["middle_trace_path"]),),
        github_ranking_paths=(Path(data_paths["github_ranking_path"]),),
        epochs=8,
    )
    middle_model = load_local_model(tmp_path / "out3", target="middle")
    github_model = load_local_model(tmp_path / "out3", target="github")

    middle_prediction = classify_middle_decision(
        middle_model,
        {
            "decision": {"confidence": 0.98, "margin": 0.7, "risk_signal": "low"},
            "coverage_report": {"must_have_coverage_rate": 0.4},
            "labels": {"latency_saved_ms": 800, "quality_delta": 0.1},
        },
    )
    assert middle_prediction["decision"] == "run_expensive_rules"
    assert middle_prediction["hard_gate_triggered"] is True

    github_prediction = score_github_repo(
        github_model,
        {
            "repo": "unsafe/repo",
            "scores": {"lexical_relevance": 10, "repo_quality": 10, "freshness": 10, "governance": 10, "novelty": 10, "downstream_utility": 10},
            "checks": {"license_ok": False, "secret_scan_passed": True},
        },
    )
    assert github_prediction["decision"] == "observe_or_quarantine"
    assert github_prediction["hard_gate_triggered"] is True
