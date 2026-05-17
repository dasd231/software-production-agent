"""Evaluation-gate decisions for trained backup local models.

The gate is intentionally conservative: it can recommend that a model enter
manual review, but it never promotes a model automatically.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REQUIRED_STAGES = (
    "model_eval.action_protocol",
    "model_eval.grounded_answer",
    "model_eval.solution_reuse",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"expected JSON object: {path}")
    return raw


def _summary_score(report: dict[str, Any]) -> float:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    return _safe_float(summary.get("overall_score"))


def _stage_scores(report: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in report.get("reports", []):
        if isinstance(row, dict):
            stage = str(row.get("stage", "") or "")
            if stage:
                out[stage] = _safe_float(row.get("overall_score"))
    return out


def _subject_model_version(report: dict[str, Any]) -> str:
    subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
    return str(subject.get("model_version", "") or "")


def _check(name: str, passed: bool, *, detail: str, actual: Any = None, expected: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "detail": detail,
        "actual": actual,
        "expected": expected,
    }


def _recommended_actions(checks: list[dict[str, Any]]) -> list[str]:
    failed = {str(row.get("name", "")) for row in checks if not bool(row.get("passed", False))}
    actions: list[str] = []
    if "benchmark_match" in failed:
        actions.append("re_evaluate_on_same_benchmark")
    if "candidate_subject_matches_model_version" in failed:
        actions.append("re_evaluate_with_model_version_manifest")
    if any(name.startswith("stage_floor:model_eval.action_protocol") for name in failed):
        actions.append("increase_action_protocol_supervision")
    if any(
        name.startswith("stage_floor:model_eval.grounded_answer")
        or name.startswith("stage_regression:model_eval.grounded_answer")
        for name in failed
    ):
        actions.append("rebalance_grounded_answer_supervision")
    if any(name.startswith("stage_floor:model_eval.solution_reuse") for name in failed):
        actions.append("increase_solution_reuse_supervision")
    if any(name.startswith("stage_regression:") for name in failed):
        actions.append("run_regression_focused_ablation")
    if "overall_delta_vs_baseline" in failed:
        actions.append("compare_against_baseline_before_more_training")
    if "overall_floor" in failed:
        actions.append("raise_candidate_overall_quality")
    return actions


def evaluate_promotion(
    *,
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    model_version: dict[str, Any] | None = None,
    min_overall_score: float = 7.0,
    min_delta_vs_baseline: float = 0.0,
    min_stage_scores: dict[str, float] | None = None,
    max_stage_regression: float = 0.0,
    require_same_benchmark: bool = True,
) -> dict[str, Any]:
    """Build a reproducible gate decision for a candidate evaluation."""

    stage_thresholds = dict(min_stage_scores or {stage: 6.0 for stage in DEFAULT_REQUIRED_STAGES})
    baseline_score = _summary_score(baseline_report)
    candidate_score = _summary_score(candidate_report)
    baseline_stages = _stage_scores(baseline_report)
    candidate_stages = _stage_scores(candidate_report)
    baseline_benchmark = str(baseline_report.get("benchmark_id", "") or "")
    candidate_benchmark = str(candidate_report.get("benchmark_id", "") or "")
    candidate_model_version = _subject_model_version(candidate_report)
    expected_model_version = str((model_version or {}).get("model_version", "") or "")

    checks: list[dict[str, Any]] = []
    checks.append(
        _check(
            "benchmark_match",
            (not require_same_benchmark) or bool(candidate_benchmark and candidate_benchmark == baseline_benchmark),
            detail="candidate and baseline must use the same benchmark",
            actual=candidate_benchmark,
            expected=baseline_benchmark,
        )
    )
    checks.append(
        _check(
            "overall_floor",
            candidate_score >= float(min_overall_score),
            detail="candidate overall score must clear the minimum floor",
            actual=round(candidate_score, 4),
            expected=float(min_overall_score),
        )
    )
    checks.append(
        _check(
            "overall_delta_vs_baseline",
            candidate_score - baseline_score >= float(min_delta_vs_baseline),
            detail="candidate must not underperform the baseline beyond policy",
            actual=round(candidate_score - baseline_score, 4),
            expected=float(min_delta_vs_baseline),
        )
    )
    if expected_model_version:
        checks.append(
            _check(
                "candidate_subject_matches_model_version",
                bool(candidate_model_version and candidate_model_version == expected_model_version),
                detail="candidate report must point at the intended model version",
                actual=candidate_model_version,
                expected=expected_model_version,
            )
        )

    for stage, threshold in stage_thresholds.items():
        candidate_stage_score = candidate_stages.get(stage)
        checks.append(
            _check(
                f"stage_floor:{stage}",
                candidate_stage_score is not None and candidate_stage_score >= float(threshold),
                detail="candidate stage score must clear the minimum floor",
                actual=candidate_stage_score,
                expected=float(threshold),
            )
        )
        if stage in baseline_stages:
            checks.append(
                _check(
                    f"stage_regression:{stage}",
                    candidate_stage_score is not None
                    and candidate_stage_score - baseline_stages[stage] >= -float(max_stage_regression),
                    detail="candidate stage score must stay within the allowed regression budget",
                    actual=None if candidate_stage_score is None else round(candidate_stage_score - baseline_stages[stage], 4),
                    expected=f">= {-float(max_stage_regression)}",
                )
            )

    passed = all(bool(row["passed"]) for row in checks)
    summary = candidate_report.get("summary") if isinstance(candidate_report.get("summary"), dict) else {}
    decision = {
        "schema": "model_promotion_decision.v1",
        "generated_at": _now(),
        "passed": passed,
        "status": "ready_for_manual_review" if passed else "blocked",
        "candidate": {
            "label": candidate_report.get("label", ""),
            "benchmark_id": candidate_benchmark,
            "model_version": candidate_model_version,
            "overall_score": candidate_score,
            "grade": summary.get("grade", ""),
            "stage_scores": candidate_stages,
        },
        "baseline": {
            "label": baseline_report.get("label", ""),
            "benchmark_id": baseline_benchmark,
            "overall_score": baseline_score,
            "stage_scores": baseline_stages,
        },
        "policy": {
            "require_same_benchmark": require_same_benchmark,
            "min_overall_score": float(min_overall_score),
            "min_delta_vs_baseline": float(min_delta_vs_baseline),
            "min_stage_scores": stage_thresholds,
            "max_stage_regression": float(max_stage_regression),
        },
        "checks": checks,
        "recommended_next_step": (
            "manual_review_before_rollout" if passed else "adjust_data_or_training_then_re_evaluate"
        ),
        "recommended_actions": [] if passed else _recommended_actions(checks),
    }
    if expected_model_version:
        decision["model_version_manifest"] = {
            "model_version": expected_model_version,
            "base_model": model_version.get("base_model", "") if isinstance(model_version, dict) else "",
            "adapter_name": model_version.get("adapter_name", "") if isinstance(model_version, dict) else "",
            "dataset_snapshot_id": model_version.get("dataset_snapshot_id", "") if isinstance(model_version, dict) else "",
            "training_job_spec_id": model_version.get("training_job_spec_id", "") if isinstance(model_version, dict) else "",
        }
    return decision


def _write_markdown_report(path: Path, decision: dict[str, Any]) -> None:
    candidate = decision.get("candidate") if isinstance(decision.get("candidate"), dict) else {}
    baseline = decision.get("baseline") if isinstance(decision.get("baseline"), dict) else {}
    lines = [
        "# Model Promotion Decision",
        "",
        f"Status: `{decision.get('status', '')}`",
        f"Candidate: `{candidate.get('label', '')}`",
        f"Baseline: `{baseline.get('label', '')}`",
        f"Benchmark: `{candidate.get('benchmark_id', '')}`",
        f"Candidate overall: `{candidate.get('overall_score', '')}`",
        f"Baseline overall: `{baseline.get('overall_score', '')}`",
        f"Recommended next step: `{decision.get('recommended_next_step', '')}`",
        f"Recommended actions: `{', '.join(decision.get('recommended_actions', []))}`",
        "",
        "## Checks",
        "",
        "| Check | Passed | Actual | Expected |",
        "| --- | --- | --- | --- |",
    ]
    for row in decision.get("checks", []):
        if isinstance(row, dict):
            lines.append(
                f"| `{row.get('name', '')}` | {row.get('passed', False)} | "
                f"{row.get('actual', '')} | {row.get('expected', '')} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_promotion_artifacts(output_dir: Path, decision: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_path = output_dir / "model_promotion_decision.json"
    report_path = output_dir / "promotion_report.md"
    decision_path.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown_report(report_path, decision)
    return {
        "decision": str(decision_path),
        "report": str(report_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate whether a trained model is ready for manual promotion review")
    parser.add_argument("--baseline-report", required=True)
    parser.add_argument("--candidate-report", required=True)
    parser.add_argument("--model-version-manifest", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--min-overall-score", type=float, default=7.0)
    parser.add_argument("--min-delta-vs-baseline", type=float, default=0.0)
    parser.add_argument("--max-stage-regression", type=float, default=0.0)
    args = parser.parse_args(argv)

    baseline = _safe_json(Path(args.baseline_report))
    candidate = _safe_json(Path(args.candidate_report))
    model_version = _safe_json(Path(args.model_version_manifest)) if args.model_version_manifest else None
    decision = evaluate_promotion(
        baseline_report=baseline,
        candidate_report=candidate,
        model_version=model_version,
        min_overall_score=float(args.min_overall_score),
        min_delta_vs_baseline=float(args.min_delta_vs_baseline),
        max_stage_regression=float(args.max_stage_regression),
    )
    write_promotion_artifacts(Path(args.output_dir), decision)
    print(json.dumps({"status": decision["status"], "passed": decision["passed"]}, ensure_ascii=False))
    return 0 if decision["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
