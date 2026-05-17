from __future__ import annotations

from pathlib import Path

from agent.training.promotion import evaluate_promotion, write_promotion_artifacts


def _report(
    *,
    label: str,
    benchmark_id: str,
    overall: float,
    action: float,
    grounded: float,
    reuse: float,
    model_version: str = "",
) -> dict:
    report = {
        "schema": "model_evaluation_report.v1",
        "label": label,
        "benchmark_id": benchmark_id,
        "summary": {"overall_score": overall, "grade": "good"},
        "reports": [
            {"stage": "model_eval.action_protocol", "overall_score": action},
            {"stage": "model_eval.grounded_answer", "overall_score": grounded},
            {"stage": "model_eval.solution_reuse", "overall_score": reuse},
        ],
    }
    if model_version:
        report["subject"] = {"model_version": model_version}
    return report


def test_promotion_gate_allows_candidate_ready_for_manual_review(tmp_path: Path) -> None:
    baseline = _report(
        label="base",
        benchmark_id="backup_model_eval.v3.json",
        overall=7.2,
        action=6.5,
        grounded=7.0,
        reuse=6.4,
    )
    candidate = _report(
        label="candidate",
        benchmark_id="backup_model_eval.v3.json",
        overall=7.6,
        action=6.8,
        grounded=7.2,
        reuse=6.5,
        model_version="backup-demo",
    )
    model_version = {
        "model_version": "backup-demo",
        "base_model": "demo/base",
        "adapter_name": "demo-adapter",
        "dataset_snapshot_id": "dataset-demo",
        "training_job_spec_id": "jobspec-demo",
    }

    decision = evaluate_promotion(
        baseline_report=baseline,
        candidate_report=candidate,
        model_version=model_version,
    )
    files = write_promotion_artifacts(tmp_path, decision)

    assert decision["passed"] is True
    assert decision["status"] == "ready_for_manual_review"
    assert decision["recommended_next_step"] == "manual_review_before_rollout"
    assert decision["model_version_manifest"]["dataset_snapshot_id"] == "dataset-demo"
    assert Path(files["decision"]).exists()
    assert "ready_for_manual_review" in Path(files["report"]).read_text(encoding="utf-8")


def test_promotion_gate_blocks_mismatched_subject_and_regression() -> None:
    baseline = _report(
        label="base",
        benchmark_id="backup_model_eval.v3.json",
        overall=8.0,
        action=7.5,
        grounded=7.2,
        reuse=6.8,
    )
    candidate = _report(
        label="candidate",
        benchmark_id="backup_model_eval.v3.json",
        overall=7.4,
        action=6.2,
        grounded=7.1,
        reuse=6.4,
        model_version="wrong-model",
    )

    decision = evaluate_promotion(
        baseline_report=baseline,
        candidate_report=candidate,
        model_version={"model_version": "backup-demo"},
    )

    failed_checks = {row["name"] for row in decision["checks"] if not row["passed"]}
    assert decision["passed"] is False
    assert decision["status"] == "blocked"
    assert "overall_delta_vs_baseline" in failed_checks
    assert "candidate_subject_matches_model_version" in failed_checks
    assert "stage_regression:model_eval.action_protocol" in failed_checks
    assert "run_regression_focused_ablation" in decision["recommended_actions"]
    assert "compare_against_baseline_before_more_training" in decision["recommended_actions"]


def test_promotion_gate_blocks_benchmark_mismatch() -> None:
    baseline = _report(
        label="base",
        benchmark_id="backup_model_eval.v2.json",
        overall=7.0,
        action=6.5,
        grounded=6.8,
        reuse=6.4,
    )
    candidate = _report(
        label="candidate",
        benchmark_id="backup_model_eval.v3.json",
        overall=7.8,
        action=7.0,
        grounded=7.2,
        reuse=6.8,
    )

    decision = evaluate_promotion(baseline_report=baseline, candidate_report=candidate)

    assert decision["passed"] is False
    assert next(row for row in decision["checks"] if row["name"] == "benchmark_match")["passed"] is False
