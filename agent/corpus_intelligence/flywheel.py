"""End-to-end CPU-first corpus flywheel cycle."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.corpus_intelligence.feedback import build_corpus_feedback_report
from agent.corpus_intelligence.projectization import CorpusProjectizationInput, materialize_corpus_projectization
from agent.corpus_intelligence.scheduler import CorpusSchedulerConfig, run_corpus_scheduler_cycle
from agent.project_model.holdout_benchmark import (
    ProjectHoldoutBenchmarkBuildInput,
    ProjectHoldoutEvaluationInput,
    build_project_holdout_benchmark,
    evaluate_project_holdout,
)


@dataclass(frozen=True)
class CorpusFlywheelInput:
    output_root: Path
    seed_queries: tuple[str, ...]
    local_repos: tuple[Path, ...] = ()
    web_results: tuple[dict[str, Any], ...] = ()
    enable_github_network: bool = False
    interval_seconds: int = 3600
    repo_limit: int = 5
    max_query_arms: int = 4
    min_stars: int = 50
    allowed_licenses: tuple[str, ...] = ()
    updated_after: str = ""
    quality_threshold: float = 6.5
    downstream_metrics: dict[str, float] = field(default_factory=dict)
    downstream_metrics_path: Path | None = None
    predictions_path: Path | None = None
    baseline_report_path: Path | None = None
    cpu_thread_budget: int = 2
    max_cycles_retained: int = 50
    max_repos: int = 50
    max_files: int = 500
    max_slices: int = 800
    max_symbol_examples_per_repo: int = 64
    force: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json(path: Path | None) -> Any:
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _feedback_metrics_from_report(path: Path | None) -> dict[str, float]:
    payload = _safe_json(path)
    if not isinstance(payload, dict):
        return {}
    raw = payload.get("feedback_deltas") if isinstance(payload.get("feedback_deltas"), dict) else {}
    if not raw:
        raw = payload.get("feedback_metrics") if isinstance(payload.get("feedback_metrics"), dict) else {}
    return {
        str(key): float(value)
        for key, value in raw.items()
        if isinstance(value, (int, float))
    }


def _merge_metrics(left: dict[str, float], right: dict[str, float]) -> dict[str, float]:
    merged = {
        str(key): float(value)
        for key, value in left.items()
        if isinstance(value, (int, float))
    }
    merged.update(
        {
            str(key): float(value)
            for key, value in right.items()
            if isinstance(value, (int, float))
        }
    )
    return merged


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_scheduler_state(output_root: Path, updates: dict[str, Any]) -> None:
    state_path = output_root / "scheduler_state.json"
    state = _safe_json(state_path)
    if not isinstance(state, dict):
        return
    state.update(updates)
    _write_json(state_path, state)


def run_corpus_flywheel_cycle(inp: CorpusFlywheelInput) -> dict[str, Any]:
    """Run one bounded cycle from crawl to projectized holdout benchmark.

    This deliberately stays CPU-first. It does not call models and does not start
    training. If predictions are supplied, it scores them and writes feedback
    deltas that the next cycle can consume.
    """

    output_root = inp.output_root.resolve()
    downstream_metrics = _merge_metrics(
        inp.downstream_metrics,
        _feedback_metrics_from_report(inp.downstream_metrics_path.resolve() if inp.downstream_metrics_path else None),
    )
    scheduler_cycle = run_corpus_scheduler_cycle(
        CorpusSchedulerConfig(
            output_root=output_root,
            seed_queries=inp.seed_queries,
            local_repos=inp.local_repos,
            web_results=inp.web_results,
            enable_github_network=inp.enable_github_network,
            interval_seconds=max(int(inp.interval_seconds), 1),
            repo_limit=max(int(inp.repo_limit), 1),
            max_query_arms=max(int(inp.max_query_arms), 1),
            min_stars=max(int(inp.min_stars), 0),
            allowed_licenses=inp.allowed_licenses,
            updated_after=inp.updated_after,
            quality_threshold=float(inp.quality_threshold),
            downstream_metrics=downstream_metrics,
            cpu_thread_budget=max(int(inp.cpu_thread_budget), 1),
            max_cycles_retained=max(int(inp.max_cycles_retained), 1),
        ),
        force=bool(inp.force),
    )
    if not bool(scheduler_cycle.get("ran")):
        return {
            "schema": "github_corpus_flywheel_cycle.v1",
            "status": str(scheduler_cycle.get("status", "skipped")),
            "ran": False,
            "scheduler_cycle": scheduler_cycle,
            "downstream_metrics": downstream_metrics,
        }

    cycle_id = str(scheduler_cycle.get("cycle_id", "") or "")
    crawl = scheduler_cycle.get("crawl") if isinstance(scheduler_cycle.get("crawl"), dict) else {}
    crawl_output_dir = Path(str(crawl.get("output_dir", "") or ""))
    cycle_root = output_root / "cycles" / cycle_id
    projectized = materialize_corpus_projectization(
        CorpusProjectizationInput(
            crawl_output_dir=crawl_output_dir,
            output_dir=cycle_root / "projectized",
            max_repos=max(int(inp.max_repos), 0),
            max_files=max(int(inp.max_files), 1),
            max_slices=max(int(inp.max_slices), 1),
            max_symbol_examples_per_repo=max(int(inp.max_symbol_examples_per_repo), 0),
        )
    )
    benchmark = build_project_holdout_benchmark(
        ProjectHoldoutBenchmarkBuildInput(
            projectization_dir=Path(projectized.output_dir),
            output_dir=cycle_root / "holdout_benchmark",
        )
    )
    evaluation: dict[str, Any] = {}
    post_eval_feedback: dict[str, Any] = {}
    if inp.predictions_path:
        evaluation = evaluate_project_holdout(
            ProjectHoldoutEvaluationInput(
                benchmark_path=Path(benchmark.files["benchmark"]),
                predictions_path=inp.predictions_path.resolve(),
                output_dir=cycle_root / "holdout_evaluation",
                baseline_report_path=inp.baseline_report_path.resolve() if inp.baseline_report_path else None,
            )
        )
        ranking_path = Path(str((crawl.get("files") or {}).get("routing_report", "") or ""))
        ranking = _safe_json(ranking_path)
        if isinstance(ranking, dict):
            post_eval_feedback = build_corpus_feedback_report(
                ranking=ranking,
                downstream_metrics=evaluation.get("feedback_deltas")
                if isinstance(evaluation.get("feedback_deltas"), dict)
                else evaluation.get("feedback_metrics")
                if isinstance(evaluation.get("feedback_metrics"), dict)
                else {},
            )
            feedback_path = cycle_root / "post_eval_feedback_report.json"
            strategy_path = cycle_root / "post_eval_corpus_strategy.json"
            _write_json(feedback_path, post_eval_feedback)
            _write_json(strategy_path, post_eval_feedback.get("strategy", {}))
            _update_scheduler_state(
                output_root,
                {
                    "latest_feedback_path": str(feedback_path),
                    "latest_strategy_path": str(strategy_path),
                    "latest_holdout_evaluation_path": str(evaluation.get("files", {}).get("evaluation_report", "")),
                },
            )

    report = {
        "schema": "github_corpus_flywheel_cycle.v1",
        "status": "completed",
        "ran": True,
        "created_at": _now(),
        "cycle_id": cycle_id,
        "downstream_metrics": downstream_metrics,
        "scheduler_cycle": {
            "status": scheduler_cycle.get("status"),
            "state_path": scheduler_cycle.get("state_path"),
            "cycle_record_path": scheduler_cycle.get("cycle_record_path"),
        },
        "projectization": projectized.to_dict(),
        "holdout_benchmark": benchmark.to_dict(),
        "holdout_evaluation": evaluation,
        "post_eval_feedback": post_eval_feedback,
    }
    report_path = cycle_root / "flywheel_cycle_report.json"
    _write_json(report_path, report)
    _update_scheduler_state(
        output_root,
        {
            "latest_projectization_manifest": projectized.files.get("manifest", ""),
            "latest_holdout_benchmark_path": benchmark.files.get("benchmark", ""),
            "latest_flywheel_report": str(report_path),
        },
    )
    report["files"] = {"flywheel_report": str(report_path)}
    return report
