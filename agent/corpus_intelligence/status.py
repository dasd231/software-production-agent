"""Status summary for GitHub corpus flywheel runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _safe_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _exists(path_text: str) -> bool:
    return bool(str(path_text or "").strip()) and Path(str(path_text)).exists()


def _artifact(path_text: str) -> dict[str, Any]:
    return {"path": str(path_text or ""), "exists": _exists(path_text)}


def build_corpus_flywheel_status(output_root: Path) -> dict[str, Any]:
    """Read scheduler state and latest flywheel artifacts without running work."""

    root = output_root.resolve()
    state_path = root / "scheduler_state.json"
    state = _safe_json(state_path)
    state = state if isinstance(state, dict) else {}
    projectization_path = str(state.get("latest_projectization_manifest", "") or "")
    benchmark_path = str(state.get("latest_holdout_benchmark_path", "") or "")
    evaluation_path = str(state.get("latest_holdout_evaluation_path", "") or "")
    flywheel_path = str(state.get("latest_flywheel_report", "") or "")
    strategy_path = str(state.get("latest_strategy_path", "") or "")
    feedback_path = str(state.get("latest_feedback_path", "") or "")
    projectization = _safe_json(Path(projectization_path)) if projectization_path else {}
    benchmark_manifest = {}
    if benchmark_path:
        benchmark_dir = Path(benchmark_path).parent
        benchmark_manifest = _safe_json(benchmark_dir / "project_holdout_benchmark_manifest.json") or {}
    evaluation = _safe_json(Path(evaluation_path)) if evaluation_path else {}
    projectization_counts = (
        projectization.get("counts", {}) if isinstance(projectization, dict) and isinstance(projectization.get("counts"), dict) else {}
    )
    benchmark_counts = (
        benchmark_manifest.get("counts", {})
        if isinstance(benchmark_manifest, dict) and isinstance(benchmark_manifest.get("counts"), dict)
        else {}
    )
    evaluation_metrics = (
        evaluation.get("feedback_metrics", {})
        if isinstance(evaluation, dict) and isinstance(evaluation.get("feedback_metrics"), dict)
        else {}
    )
    next_steps: list[str] = []
    if not state:
        next_steps.append("run github_corpus_flywheel_cycle")
    elif not _exists(projectization_path):
        next_steps.append("inspect latest crawl; projectization artifact missing")
    elif not _exists(benchmark_path):
        next_steps.append("build project_holdout_benchmark")
    elif not _exists(evaluation_path):
        next_steps.append("run offline predictions then project_holdout_evaluate")
    else:
        next_steps.append("feed evaluation feedback_deltas into next github_corpus_flywheel_cycle")
        next_steps.append("prepare github_corpus_training_bundle if trainable routes exist")
    return {
        "schema": "github_corpus_flywheel_status.v1",
        "output_root": str(root),
        "state": {
            "path": str(state_path),
            "exists": bool(state),
            "latest_cycle_id": str(state.get("latest_cycle_id", "") or ""),
            "latest_completed_at": str(state.get("latest_completed_at", "") or ""),
            "cycle_count": len(state.get("cycles", [])) if isinstance(state.get("cycles"), list) else 0,
        },
        "artifacts": {
            "latest_strategy": _artifact(strategy_path),
            "latest_feedback": _artifact(feedback_path),
            "latest_projectization_manifest": _artifact(projectization_path),
            "latest_holdout_benchmark": _artifact(benchmark_path),
            "latest_holdout_evaluation": _artifact(evaluation_path),
            "latest_flywheel_report": _artifact(flywheel_path),
        },
        "counts": {
            "projectization": projectization_counts,
            "holdout_benchmark": benchmark_counts,
        },
        "feedback_metrics": evaluation_metrics,
        "next_steps": next_steps,
    }
