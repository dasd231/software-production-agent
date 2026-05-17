"""Refresh lightweight research-workbench summaries from local artifacts."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKBENCH = ROOT / "research_workbench"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.distributed.plans import build_distributed_platform_plan
from agent.distributed.workloads import list_distributed_workloads
from agent.project_model.program import build_project_model_program
from agent.training.studio import build_training_platform_blueprint
from agent.distillation.catalog import list_teacher_models, list_teacher_tasks


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _child_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda p: p.name)


def _accepted_example_count(
    *,
    quality: dict[str, Any],
    evaluation: dict[str, Any],
    snapshot: dict[str, Any],
    task_mix: dict[str, Any],
) -> int | None:
    snapshot_counts = snapshot.get("counts") if isinstance(snapshot.get("counts"), dict) else {}
    metric_payload = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), dict) else {}
    example_metric = metric_payload.get("example_count") if isinstance(metric_payload.get("example_count"), dict) else {}
    candidates = [
        snapshot_counts.get("dataset_examples"),
        example_metric.get("value"),
        sum(int(value) for value in task_mix.values()) if task_mix else None,
        quality.get("with_citations"),
        quality.get("raw_examples"),
    ]
    for candidate in candidates:
        if isinstance(candidate, bool):
            continue
        if isinstance(candidate, (int, float)):
            return int(candidate)
    return None


def _task_balance_snapshot(
    *,
    task_mix: dict[str, Any],
    evaluation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evaluation = evaluation or {}
    metrics = evaluation.get("metrics") if isinstance(evaluation.get("metrics"), dict) else {}
    min_share_metric = metrics.get("min_task_share") if isinstance(metrics.get("min_task_share"), dict) else {}
    total = sum(int(value) for value in task_mix.values()) if task_mix else 0
    task_shares = {
        str(task): round(int(count) / total, 4)
        for task, count in task_mix.items()
        if total
    }
    min_task_share = min_share_metric.get("value")
    if not isinstance(min_task_share, (int, float)):
        min_task_share = min(task_shares.values()) if task_shares else None
    status = str(min_share_metric.get("status", "") or "")
    if not status and isinstance(min_task_share, (int, float)):
        status = "ok" if float(min_task_share) >= 0.05 else "watch"
    rarest_tasks = [
        task
        for task, share in sorted(task_shares.items())
        if isinstance(min_task_share, (int, float)) and share == round(float(min_task_share), 4)
    ]
    return {
        "task_shares": task_shares,
        "min_task_share": round(float(min_task_share), 4) if isinstance(min_task_share, (int, float)) else None,
        "task_balance_status": status,
        "rarest_tasks": rarest_tasks,
    }


def _training_runs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in _child_dirs(ROOT / "training_runs"):
        quality = _safe_json(run / "quality_report.json")
        evaluation = _safe_json(run / "evaluation_report.json")
        snapshot = _safe_json(run / "dataset_snapshot_manifest.json")
        task_mix = quality.get("by_task_type") or ((snapshot.get("task_mix") or {}).get("dataset", {}))
        task_mix = task_mix if isinstance(task_mix, dict) else {}
        balance = _task_balance_snapshot(task_mix=task_mix, evaluation=evaluation)
        rows.append(
            {
                "name": run.name,
                "path": str(run.relative_to(ROOT)),
                "dataset_id": snapshot.get("dataset_id", ""),
                "total_examples": _accepted_example_count(
                    quality=quality,
                    evaluation=evaluation,
                    snapshot=snapshot,
                    task_mix=task_mix,
                ),
                "task_mix": task_mix,
                "quality_score": quality.get("evaluation_score") or evaluation.get("overall_score"),
                "quality_grade": quality.get("evaluation_grade") or evaluation.get("grade"),
                **balance,
            }
        )
    return rows


def _model_runs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in _child_dirs(ROOT / "model_runs"):
        version = _safe_json(run / "model_version_manifest.json")
        job = _safe_json(run / "training_job_manifest.json")
        training_result = _safe_json(run / "adapter" / "training_result.json")
        training_dir_raw = str(version.get("training_dir", "") or "").strip()
        inferred_snapshot = (
            _safe_json(Path(training_dir_raw) / "dataset_snapshot_manifest.json")
            if training_dir_raw
            else {}
        )
        rows.append(
            {
                "name": run.name,
                "path": str(run.relative_to(ROOT)),
                "model_version": version.get("model_version", ""),
                "base_model": version.get("base_model", ""),
                "rollout_stage": version.get("rollout_stage", ""),
                "dataset_snapshot_id": version.get("dataset_snapshot_id", "") or inferred_snapshot.get("dataset_id", ""),
                "training_job_spec_id": version.get("training_job_spec_id", ""),
                "job_status": job.get("current_status", "") or version.get("training_status", ""),
                "train_loss": ((training_result.get("metrics") or {}).get("train_loss")),
                "eval_loss": ((training_result.get("eval_metrics") or {}).get("eval_loss")),
            }
        )
    return rows


def _model_evals() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in _child_dirs(ROOT / "model_evals"):
        report = _safe_json(run / "model_evaluation_report.json")
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        stage_scores = {
            str(row.get("stage", "")): row.get("overall_score")
            for row in report.get("reports", [])
            if isinstance(row, dict)
        }
        rows.append(
            {
                "name": run.name,
                "path": str(run.relative_to(ROOT)),
                "label": report.get("label", ""),
                "benchmark_id": report.get("benchmark_id", ""),
                "overall_score": summary.get("overall_score"),
                "grade": summary.get("grade"),
                "stage_scores": stage_scores,
                "subject": report.get("subject") if isinstance(report.get("subject"), dict) else {},
            }
        )
    return rows


def _promotion_decisions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run in _child_dirs(ROOT / "model_evals"):
        decision = _safe_json(run / "model_promotion_decision.json")
        if not decision:
            continue
        candidate = decision.get("candidate") if isinstance(decision.get("candidate"), dict) else {}
        rows.append(
            {
                "name": run.name,
                "path": str(run.relative_to(ROOT)),
                "status": decision.get("status", ""),
                "passed": bool(decision.get("passed", False)),
                "model_version": candidate.get("model_version", ""),
                "label": candidate.get("label", ""),
                "benchmark_id": candidate.get("benchmark_id", ""),
                "recommended_next_step": decision.get("recommended_next_step", ""),
                "recommended_actions": (
                    decision.get("recommended_actions")
                    if isinstance(decision.get("recommended_actions"), list)
                    else []
                ),
                "checks": decision.get("checks") if isinstance(decision.get("checks"), list) else [],
            }
        )
    return rows


def _benchmark_key(row: dict[str, Any]) -> str:
    benchmark_id = str(row.get("benchmark_id", "") or "").strip()
    if benchmark_id:
        return benchmark_id
    probe = f"{row.get('label', '')} {row.get('name', '')}".lower()
    match = re.search(r"(benchv\d+(?:_schema)?)", probe)
    return match.group(1) if match else "unspecified"


def _is_baseline_evaluation(row: dict[str, Any]) -> bool:
    subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
    if str(subject.get("subject_type", "") or "") == "base_model":
        return True
    label = str(row.get("label", "") or "").lower()
    return label == "base" or label == "baseline" or label.startswith("base_") or "_base" in label


def _evaluation_comparison(model_evals: list[dict[str, Any]]) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    by_benchmark: dict[str, list[dict[str, Any]]] = {}
    for row in model_evals:
        by_benchmark.setdefault(_benchmark_key(row), []).append(row)
    for benchmark, rows in sorted(by_benchmark.items()):
        sorted_rows = sorted(
            rows,
            key=lambda item: (
                float(item["overall_score"]) if isinstance(item.get("overall_score"), (int, float)) else -1,
                str(item.get("label", "")),
            ),
            reverse=True,
        )
        baseline_candidates = [row for row in rows if "base" in str(row.get("label", "")).lower()]
        baseline = max(
            baseline_candidates,
            key=lambda item: float(item["overall_score"]) if isinstance(item.get("overall_score"), (int, float)) else -1,
            default=None,
        )
        comparison_rows = []
        for row in sorted_rows:
            score = row.get("overall_score")
            base_score = baseline.get("overall_score") if baseline else None
            delta = None
            if isinstance(score, (int, float)) and isinstance(base_score, (int, float)):
                delta = round(float(score) - float(base_score), 2)
            comparison_rows.append(
                {
                    "name": row["name"],
                    "label": row.get("label", ""),
                    "overall_score": score,
                    "grade": row.get("grade", ""),
                    "delta_vs_baseline": delta,
                    "stage_scores": row.get("stage_scores", {}),
                }
            )
        groups.append(
            {
                "benchmark": benchmark,
                "baseline": (
                    {
                        "name": baseline["name"],
                        "label": baseline.get("label", ""),
                        "overall_score": baseline.get("overall_score"),
                    }
                    if baseline
                    else {}
                ),
                "best": (
                    {
                        "name": sorted_rows[0]["name"],
                        "label": sorted_rows[0].get("label", ""),
                        "overall_score": sorted_rows[0].get("overall_score"),
                    }
                    if sorted_rows
                    else {}
                ),
                "rows": comparison_rows,
            }
        )
    return {
        "schema": "research_experiment_comparison.v1",
        "generated_at": _now(),
        "groups": groups,
    }


def _metric_explainer() -> dict[str, Any]:
    taxonomy = _safe_json(WORKBENCH / "training_layers" / "metric_taxonomy.json")
    return {
        "schema": "research_metric_explainer.v1",
        "generated_at": _now(),
        "metric_groups": taxonomy.get("metric_groups", []),
        "notes": taxonomy.get("notes", []),
    }


def _promotion_overview(promotion_decisions: list[dict[str, Any]]) -> dict[str, Any]:
    failed_check_counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for row in promotion_decisions:
        failed_checks = [
            str(check.get("name", ""))
            for check in row.get("checks", [])
            if isinstance(check, dict) and not bool(check.get("passed", False))
        ]
        for name in failed_checks:
            failed_check_counts[name] = failed_check_counts.get(name, 0) + 1
        rows.append(
            {
                "name": row.get("name", ""),
                "label": row.get("label", ""),
                "model_version": row.get("model_version", ""),
                "benchmark_id": row.get("benchmark_id", ""),
                "status": row.get("status", ""),
                "failed_checks": failed_checks,
                "recommended_next_step": row.get("recommended_next_step", ""),
                "recommended_actions": row.get("recommended_actions", []),
            }
        )
    return {
        "schema": "research_promotion_overview.v1",
        "generated_at": _now(),
        "summary": {
            "total": len(promotion_decisions),
            "passed": sum(1 for row in promotion_decisions if row.get("passed")),
            "blocked": sum(1 for row in promotion_decisions if not row.get("passed")),
        },
        "rows": rows,
        "failed_check_counts": [
            {"check": name, "count": count}
            for name, count in sorted(failed_check_counts.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


_ACTION_TO_TASK = {
    "increase_action_protocol_supervision": "action_protocol_sft",
    "rebalance_grounded_answer_supervision": "rag_grounded_answer",
    "increase_solution_reuse_supervision": "solution_reuse_sft",
}


def _experiment_queue(
    training_runs: list[dict[str, Any]],
    model_runs: list[dict[str, Any]],
    model_evals: list[dict[str, Any]],
    promotion_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    datasets = {str(row.get("dataset_id", "")): row for row in training_runs if str(row.get("dataset_id", ""))}
    evaluations_by_model: dict[str, list[dict[str, Any]]] = {}
    for row in model_evals:
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        model_version = str(subject.get("model_version", "") or "")
        if model_version:
            evaluations_by_model.setdefault(model_version, []).append(row)
    decisions_by_model: dict[str, list[dict[str, Any]]] = {}
    for row in promotion_decisions:
        model_version = str(row.get("model_version", "") or "")
        if model_version:
            decisions_by_model.setdefault(model_version, []).append(row)

    rows: list[dict[str, Any]] = []
    for model in model_runs:
        model_version = str(model.get("model_version", "") or "")
        dataset_id = str(model.get("dataset_snapshot_id", "") or "")
        dataset = datasets.get(dataset_id, {})
        evaluations = evaluations_by_model.get(model_version, [])
        decisions = decisions_by_model.get(model_version, [])
        latest_decision = decisions[-1] if decisions else {}
        job_status = str(model.get("job_status", "") or "")
        rollout_stage = str(model.get("rollout_stage", "") or "")

        if job_status in {"created", "validated", "queued"} or (
            rollout_stage == "candidate" and job_status != "completed" and not evaluations
        ):
            next_action = "execute_training_job"
            reason = "training_job_not_completed"
        elif job_status == "completed" and not evaluations:
            next_action = "run_benchmark_evaluation"
            reason = "trained_without_precisely_linked_evaluation"
        elif evaluations and not decisions:
            next_action = "run_promotion_gate"
            reason = "evaluation_without_promotion_decision"
        elif decisions and not bool(latest_decision.get("passed", False)):
            next_action = "apply_remediation_then_retrain"
            reason = "promotion_blocked"
        elif decisions and bool(latest_decision.get("passed", False)):
            next_action = "manual_review"
            reason = "promotion_gate_passed"
        else:
            next_action = "inspect_lineage"
            reason = "insufficient_precise_evidence"

        rows.append(
            {
                "model_run": model.get("name", ""),
                "model_version": model_version,
                "dataset_id": dataset_id,
                "job_status": job_status,
                "rollout_stage": rollout_stage,
                "evaluation_count": len(evaluations),
                "latest_promotion_status": latest_decision.get("status", ""),
                "task_balance_status": dataset.get("task_balance_status", ""),
                "min_task_share": dataset.get("min_task_share"),
                "next_action": next_action,
                "reason": reason,
            }
        )

    action_counts: dict[str, int] = {}
    for row in rows:
        action = str(row.get("next_action", "") or "")
        if action:
            action_counts[action] = action_counts.get(action, 0) + 1
    priority = {
        "execute_training_job": 0,
        "run_benchmark_evaluation": 1,
        "run_promotion_gate": 2,
        "apply_remediation_then_retrain": 3,
        "manual_review": 4,
        "inspect_lineage": 5,
    }
    return {
        "schema": "research_experiment_queue.v1",
        "generated_at": _now(),
        "summary": {
            "models": len(rows),
            "action_counts": action_counts,
        },
        "rows": sorted(
            rows,
            key=lambda row: (
                priority.get(str(row.get("next_action", "")), 99),
                str(row.get("model_run", "")),
            ),
        ),
    }


def _dataset_evolution(
    training_runs: list[dict[str, Any]],
    model_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    models_by_dataset: dict[str, list[dict[str, Any]]] = {}
    for model in model_runs:
        dataset_id = str(model.get("dataset_snapshot_id", "") or "")
        if dataset_id:
            models_by_dataset.setdefault(dataset_id, []).append(model)

    rows: list[dict[str, Any]] = []
    for row in training_runs:
        dataset_id = str(row.get("dataset_id", "") or "")
        task_mix = row.get("task_mix") if isinstance(row.get("task_mix"), dict) else {}
        models = models_by_dataset.get(dataset_id, [])
        rows.append(
            {
                "training_run": row.get("name", ""),
                "dataset_id": dataset_id,
                "accepted_examples": row.get("total_examples"),
                "min_task_share": row.get("min_task_share"),
                "task_balance_status": row.get("task_balance_status", ""),
                "rag_grounded_answer_count": task_mix.get("rag_grounded_answer", 0),
                "action_protocol_count": task_mix.get("action_protocol_sft", 0),
                "model_runs": [model.get("name", "") for model in models],
                "has_candidate_model": any(str(model.get("rollout_stage", "")) == "candidate" for model in models),
            }
        )

    sorted_rows = sorted(rows, key=lambda item: str(item.get("training_run", "")))
    best_balanced = max(
        sorted_rows,
        key=lambda item: float(item["min_task_share"]) if isinstance(item.get("min_task_share"), (int, float)) else -1,
        default={},
    )
    first_watch = next((row for row in sorted_rows if row.get("task_balance_status") == "watch"), {})
    observations: list[str] = []
    if first_watch and best_balanced:
        observations.append(
            "grounded supervision improved from "
            f"{first_watch.get('rag_grounded_answer_count', 0)} to {best_balanced.get('rag_grounded_answer_count', 0)} examples"
        )
    if best_balanced and best_balanced.get("task_balance_status") == "ok":
        observations.append(
            f"best-balanced dataset is {best_balanced.get('training_run', '')} "
            f"with min_task_share={best_balanced.get('min_task_share', '')}"
        )
    if best_balanced and best_balanced.get("has_candidate_model"):
        observations.append("best-balanced dataset already has a candidate model prepared")
    elif best_balanced:
        observations.append("best-balanced dataset still lacks a candidate model")

    return {
        "schema": "research_dataset_evolution.v1",
        "generated_at": _now(),
        "summary": {
            "datasets": len(rows),
            "balanced_datasets": sum(1 for row in rows if row.get("task_balance_status") == "ok"),
            "watch_datasets": sum(1 for row in rows if row.get("task_balance_status") == "watch"),
        },
        "observations": observations,
        "rows": sorted_rows,
    }


def _platform_evolution() -> dict[str, Any]:
    plan = build_distributed_platform_plan()
    rows = []
    for plane in plan.get("planes", []):
        if not isinstance(plane, dict):
            continue
        rows.append(
            {
                "name": plane.get("name", ""),
                "primary": plane.get("primary", "project-owned"),
                "owns": plane.get("owns", []),
                "entry_condition": plane.get("entry_condition", ""),
            }
        )
    return {
        "schema": "research_platform_evolution.v1",
        "generated_at": _now(),
        "north_star": plan.get("north_star", ""),
        "adoption_order": plan.get("adoption_order", []),
        "anti_patterns": plan.get("anti_patterns", []),
        "rows": rows,
    }


def _distributed_execution_overview() -> dict[str, Any]:
    workloads = list_distributed_workloads()
    queue_counts: dict[str, int] = {}
    gpu_workloads: list[str] = []
    for row in workloads:
        queue = str(row.get("queue", "") or "default")
        queue_counts[queue] = queue_counts.get(queue, 0) + 1
        resources = row.get("resources") if isinstance(row.get("resources"), dict) else {}
        if int(resources.get("gpu", 0) or 0) > 0:
            gpu_workloads.append(str(row.get("id", "")))
    return {
        "schema": "research_distributed_execution_overview.v1",
        "generated_at": _now(),
        "summary": {
            "workloads": len(workloads),
            "gpu_workloads": len(gpu_workloads),
            "queues": len(queue_counts),
        },
        "queue_counts": queue_counts,
        "gpu_workloads": gpu_workloads,
        "rows": workloads,
    }


_NEXT_ACTION_TO_WORKLOAD = {
    "execute_training_job": "training_dispatch",
    "run_benchmark_evaluation": "benchmark_evaluation",
    "run_promotion_gate": "promotion_gate",
}


def _distributed_dispatch_candidates(experiment_queue: dict[str, Any]) -> dict[str, Any]:
    workloads = {row["id"]: row for row in list_distributed_workloads()}
    rows: list[dict[str, Any]] = []
    for row in experiment_queue.get("rows", []):
        if not isinstance(row, dict):
            continue
        next_action = str(row.get("next_action", "") or "")
        workload_id = _NEXT_ACTION_TO_WORKLOAD.get(next_action, "")
        if not workload_id:
            continue
        workload = workloads.get(workload_id, {})
        resources = workload.get("resources") if isinstance(workload.get("resources"), dict) else {}
        rows.append(
            {
                "model_run": row.get("model_run", ""),
                "next_action": next_action,
                "reason": row.get("reason", ""),
                "workload": workload_id,
                "queue": workload.get("queue", ""),
                "priority": workload.get("priority", ""),
                "resources": resources,
                "eligible": bool(workload),
            }
        )
    workload_counts: dict[str, int] = {}
    for row in rows:
        workload = str(row.get("workload", "") or "")
        workload_counts[workload] = workload_counts.get(workload, 0) + 1
    return {
        "schema": "research_distributed_dispatch_candidates.v1",
        "generated_at": _now(),
        "summary": {
            "dispatchable": len(rows),
            "workload_counts": workload_counts,
        },
        "rows": rows,
    }


def _project_model_program_overview() -> dict[str, Any]:
    program = build_project_model_program()
    return {
        "schema": "research_project_model_program.v1",
        "generated_at": _now(),
        "north_star": program.get("north_star", ""),
        "summary": program.get("summary", {}),
        "recommended_first_build": program.get("recommended_first_build", {}),
        "sources": program.get("sources", []),
        "stages": program.get("stages", []),
        "benchmarks": program.get("benchmarks", []),
        "validation": program.get("validation", {}),
    }


def _training_platform_blueprint_overview() -> dict[str, Any]:
    blueprint = build_training_platform_blueprint()
    return {
        "schema": "research_training_platform_blueprint.v1",
        "generated_at": _now(),
        "north_star": blueprint.get("north_star", ""),
        "route_memory": blueprint.get("route_memory", []),
        "required_capabilities": blueprint.get("required_capabilities", []),
        "planes": blueprint.get("planes", []),
        "knobs": blueprint.get("knobs", []),
        "current_priority": blueprint.get("current_priority", {}),
    }


def _distillation_overview() -> dict[str, Any]:
    teachers = list_teacher_models()
    tasks = list_teacher_tasks()
    return {
        "schema": "research_distillation_overview.v1",
        "generated_at": _now(),
        "summary": {
            "teachers": len(teachers),
            "teacher_tasks": len(tasks),
        },
        "teachers": teachers,
        "tasks": tasks,
        "notes": [
            "当前页面只展示蒸馏控制面目录，不代表已经触发真实教师调用。",
            "真实调用层应在 teacher registry 和 task suite 稳定后接入。",
        ],
    }


def _training_remediation(
    training_runs: list[dict[str, Any]],
    model_runs: list[dict[str, Any]],
    promotion_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    datasets = {str(row.get("dataset_id", "")): row for row in training_runs if str(row.get("dataset_id", ""))}
    models = {str(row.get("model_version", "")): row for row in model_runs if str(row.get("model_version", ""))}
    decisions_by_model: dict[str, list[dict[str, Any]]] = {}
    for decision in promotion_decisions:
        model_version = str(decision.get("model_version", "") or "")
        if model_version:
            decisions_by_model.setdefault(model_version, []).append(decision)

    action_counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    for model_version, decisions in sorted(decisions_by_model.items()):
        model = models.get(model_version, {})
        dataset_id = str(model.get("dataset_snapshot_id", "") or "")
        dataset = datasets.get(dataset_id, {})
        task_mix = dataset.get("task_mix") if isinstance(dataset.get("task_mix"), dict) else {}
        actions = sorted(
            {
                str(action)
                for decision in decisions
                for action in decision.get("recommended_actions", [])
                if str(action).strip()
            }
        )
        for action in actions:
            action_counts[action] = action_counts.get(action, 0) + 1
        task_support = {
            task: task_mix.get(task, 0)
            for action, task in _ACTION_TO_TASK.items()
            if action in actions
        }
        max_task_count = max((int(value) for value in task_mix.values()), default=0)
        underrepresented_tasks = [
            {
                "task": task,
                "count": count,
                "relative_to_largest_family": round((count / max_task_count), 4) if max_task_count else 0.0,
            }
            for task, count in task_support.items()
            if max_task_count and int(count) < max_task_count * 0.25
        ]
        rows.append(
            {
                "model_run": model.get("name", ""),
                "model_version": model_version,
                "dataset_id": dataset_id,
                "actions": actions,
                "task_support": task_support,
                "min_task_share": dataset.get("min_task_share"),
                "task_balance_status": dataset.get("task_balance_status", ""),
                "rarest_tasks": dataset.get("rarest_tasks", []),
                "underrepresented_tasks": underrepresented_tasks,
            }
        )
    return {
        "schema": "research_training_remediation.v1",
        "generated_at": _now(),
        "summary": {
            "models_with_recommendations": len(rows),
            "action_counts": action_counts,
        },
        "rows": rows,
    }


def _training_lineage(
    training_runs: list[dict[str, Any]],
    model_runs: list[dict[str, Any]],
    model_evals: list[dict[str, Any]],
    promotion_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    datasets: dict[str, dict[str, Any]] = {
        str(row.get("dataset_id", "")): {
            "dataset_id": row.get("dataset_id", ""),
            "training_run": row.get("name", ""),
            "quality_score": row.get("quality_score"),
            "quality_grade": row.get("quality_grade", ""),
            "task_mix": row.get("task_mix", {}),
            "model_runs": [],
        }
        for row in training_runs
        if str(row.get("dataset_id", "")).strip()
    }
    models_by_version: dict[str, dict[str, Any]] = {}
    for row in model_runs:
        entry = {
            "model_run": row.get("name", ""),
            "model_version": row.get("model_version", ""),
            "base_model": row.get("base_model", ""),
            "rollout_stage": row.get("rollout_stage", ""),
            "training_job_spec_id": row.get("training_job_spec_id", ""),
            "job_status": row.get("job_status", ""),
            "evaluations": [],
            "promotion_decisions": [],
        }
        dataset_id = str(row.get("dataset_snapshot_id", "") or "")
        if dataset_id in datasets:
            datasets[dataset_id]["model_runs"].append(entry)
        if str(row.get("model_version", "")).strip():
            models_by_version[str(row["model_version"])] = entry

    baseline_evaluations: list[dict[str, Any]] = []
    unlinked_candidate_evaluations: list[dict[str, Any]] = []
    for row in model_evals:
        subject = row.get("subject") if isinstance(row.get("subject"), dict) else {}
        model_version = str(subject.get("model_version", "") or "")
        eval_entry = {
            "evaluation_run": row.get("name", ""),
            "label": row.get("label", ""),
            "benchmark": _benchmark_key(row),
            "overall_score": row.get("overall_score"),
            "grade": row.get("grade", ""),
        }
        if model_version and model_version in models_by_version:
            models_by_version[model_version]["evaluations"].append(eval_entry)
        elif _is_baseline_evaluation(row):
            baseline_evaluations.append(eval_entry)
        else:
            unlinked_candidate_evaluations.append(eval_entry)

    unlinked_promotion_decisions: list[dict[str, Any]] = []
    for row in promotion_decisions:
        model_version = str(row.get("model_version", "") or "")
        decision_entry = {
            "decision_run": row.get("name", ""),
            "label": row.get("label", ""),
            "benchmark": str(row.get("benchmark_id", "") or ""),
            "status": row.get("status", ""),
            "passed": row.get("passed", False),
        }
        if model_version and model_version in models_by_version:
            models_by_version[model_version]["promotion_decisions"].append(decision_entry)
        else:
            unlinked_promotion_decisions.append(decision_entry)

    return {
        "schema": "research_training_lineage.v1",
        "generated_at": _now(),
        "datasets": list(datasets.values()),
        "baseline_evaluations": baseline_evaluations,
        "unlinked_candidate_evaluations": unlinked_candidate_evaluations,
        "unlinked_promotion_decisions": unlinked_promotion_decisions,
        "notes": [
            "训练数据到模型训练的链路来自 dataset_snapshot_id 的精确引用。",
            "baseline 评测不应挂到 adapter 版本上，会单独保留在 baseline_evaluations 中。",
            "候选模型评测只有在 report.subject.model_version 存在时才会被精确挂接；缺少引用的候选评测会保留在 unlinked_candidate_evaluations 中。",
            "晋级决策只有在 candidate.model_version 存在时才会被精确挂接；缺少模型版本引用的决策会保留在 unlinked_promotion_decisions 中。",
        ],
    }


def _to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 训练总览",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        "## 汇总",
        "",
        f"- 训练数据 run：`{payload['summary']['training_runs']}`",
        f"- 模型训练 run：`{payload['summary']['model_runs']}`",
        f"- 模型评测 run：`{payload['summary']['model_evals']}`",
        f"- 晋级决策 run：`{payload['summary']['promotion_decisions']}`",
        f"- 任务配比需关注的数据集：`{payload['summary']['task_balance_watch_runs']}`",
        "",
        "## 最近训练数据",
        "",
        "| Run | Dataset | Examples | Quality | Min Share | Balance | Task Mix |",
        "| --- | --- | ---: | --- | ---: | --- | --- |",
    ]
    for row in payload["training_runs"][-8:]:
        mix = ", ".join(f"{k}:{v}" for k, v in sorted((row.get("task_mix") or {}).items()))
        lines.append(
            f"| `{row['name']}` | `{row.get('dataset_id', '')}` | {row.get('total_examples', '')} | "
            f"{row.get('quality_score', '')} {row.get('quality_grade', '')} | "
            f"{row.get('min_task_share', '')} | {row.get('task_balance_status', '')} | {mix} |"
        )
    lines.extend(
        [
            "",
            "## 最近模型训练",
            "",
            "| Run | Base Model | Stage | Job | Train Loss | Eval Loss |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ]
    )
    for row in payload["model_runs"][-8:]:
        lines.append(
            f"| `{row['name']}` | `{row.get('base_model', '')}` | {row.get('rollout_stage', '')} | "
            f"{row.get('job_status', '')} | {row.get('train_loss', '')} | {row.get('eval_loss', '')} |"
        )
    lines.extend(
        [
            "",
            "## 最近模型评测",
            "",
            "| Eval | Label | Overall | Grade | Stage Scores |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for row in payload["model_evals"][-12:]:
        stages = ", ".join(f"{k.split('.')[-1]}:{v}" for k, v in sorted((row.get("stage_scores") or {}).items()))
        lines.append(
            f"| `{row['name']}` | `{row.get('label', '')}` | {row.get('overall_score', '')} | "
            f"{row.get('grade', '')} | {stages} |"
        )
    lines.extend(
        [
            "",
            "## 最近晋级决策",
            "",
            "| Decision | Label | Benchmark | Status | Next Step |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload["promotion_decisions"][-12:]:
        lines.append(
            f"| `{row['name']}` | `{row.get('label', '')}` | `{row.get('benchmark_id', '')}` | "
            f"{row.get('status', '')} | {row.get('recommended_next_step', '')} |"
        )
    lines.extend(
        [
            "",
            "## 使用说明",
            "",
            "- 这个页面只做轻量汇总，不替代正式实验登记。",
            "- 需要形成论文结论时，仍应在 `experiments/experiment_registry.csv` 中登记实验问题、数据、方法和结论。",
            "- 需要复盘同行工作时，使用 `literature/paper_reading_log.csv`。",
            "",
        ]
    )
    return "\n".join(lines)


def _comparison_to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 实验对比",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
    ]
    for group in payload["groups"]:
        baseline = group.get("baseline") or {}
        best = group.get("best") or {}
        lines.extend(
            [
                f"## {group['benchmark']}",
                "",
                f"- 基线：`{baseline.get('label', '未识别')}` / `{baseline.get('overall_score', '')}`",
                f"- 当前最好：`{best.get('label', '')}` / `{best.get('overall_score', '')}`",
                "",
                "| Eval | Label | Overall | Grade | Δ vs baseline |",
                "| --- | --- | ---: | --- | ---: |",
            ]
        )
        for row in group["rows"]:
            lines.append(
                f"| `{row['name']}` | `{row.get('label', '')}` | {row.get('overall_score', '')} | "
                f"{row.get('grade', '')} | {row.get('delta_vs_baseline', '')} |"
            )
        lines.append("")
    lines.extend(
        [
            "## 使用说明",
            "",
            "- 这个页面适合做 baseline / variant / tuned 模型的快速横向比较。",
            "- 只有在 benchmark 一致时，Δ 才适合进入正式结论。",
            "",
        ]
    )
    return "\n".join(lines)


def _metric_explainer_to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 指标说明",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
    ]
    for group in payload["metric_groups"]:
        lines.extend(
            [
                f"## {group.get('label', group.get('id', ''))}",
                "",
                "| 指标 | 含义 |",
                "| --- | --- |",
            ]
        )
        for metric in group.get("metrics", []):
            if isinstance(metric, dict):
                lines.append(f"| `{metric.get('name', '')}` | {metric.get('meaning', '')} |")
        lines.append("")
    if payload.get("notes"):
        lines.extend(["## 备注", ""])
        lines.extend(f"- {note}" for note in payload["notes"])
        lines.append("")
    return "\n".join(lines)


def _promotion_overview_to_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# 晋级门禁总览",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        "## 汇总",
        "",
        f"- 决策总数：`{summary.get('total', 0)}`",
        f"- 通过：`{summary.get('passed', 0)}`",
        f"- 阻塞：`{summary.get('blocked', 0)}`",
        "",
        "## 决策明细",
        "",
        "| Eval | Model Version | Benchmark | Status | Failed Checks | Recommended Actions |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["rows"]:
        failed = ", ".join(row.get("failed_checks", []))
        actions = ", ".join(row.get("recommended_actions", []))
        lines.append(
            f"| `{row.get('name', '')}` | `{row.get('model_version', '')}` | "
            f"`{row.get('benchmark_id', '')}` | {row.get('status', '')} | {failed} | {actions} |"
        )
    lines.extend(
        [
            "",
            "## 失败模式",
            "",
            "| Check | Count |",
            "| --- | ---: |",
        ]
    )
    for row in payload["failed_check_counts"]:
        lines.append(f"| `{row.get('check', '')}` | {row.get('count', 0)} |")
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- 先看重复出现最多的失败项，再决定下一批数据该补哪类能力。",
            "- 如果 `overall_delta_vs_baseline` 与某个 `stage_regression:*` 同时高频，说明当前训练在换能力，而不是稳定增益。",
            "",
        ]
    )
    return "\n".join(lines)


def _experiment_queue_to_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# 实验执行队列",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        "## 汇总",
        "",
        f"- 模型数：`{summary.get('models', 0)}`",
        "",
        "## 待办分布",
        "",
        "| Next Action | Count |",
        "| --- | ---: |",
    ]
    for action, count in sorted((summary.get("action_counts") or {}).items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{action}` | {count} |")
    lines.extend(
        [
            "",
            "## 队列",
            "",
            "| Model Run | Job | Eval Count | Promotion | Dataset Balance | Next Action | Reason |",
            "| --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for row in payload["rows"]:
        lines.append(
            f"| `{row.get('model_run', '')}` | {row.get('job_status', '')} | {row.get('evaluation_count', 0)} | "
            f"{row.get('latest_promotion_status', '')} | {row.get('min_task_share', '')} {row.get('task_balance_status', '')} | "
            f"`{row.get('next_action', '')}` | {row.get('reason', '')} |"
        )
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- 这个页面回答的是“下一步最该做什么”，不是“哪个模型最好”。",
            "- 如果某个已训练模型仍显示 `run_benchmark_evaluation`，说明当前没有可精确挂接到该模型版本的评测证据。",
            "- 如果某个候选模型仍显示 `execute_training_job`，说明数据与 job 已准备好，但训练本身尚未真正完成。",
            "",
        ]
    )
    return "\n".join(lines)


def _dataset_evolution_to_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# 数据集演进",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        "## 汇总",
        "",
        f"- 数据集数：`{summary.get('datasets', 0)}`",
        f"- 配比健康：`{summary.get('balanced_datasets', 0)}`",
        f"- 仍需关注：`{summary.get('watch_datasets', 0)}`",
        "",
        "## 关键观察",
        "",
    ]
    lines.extend(f"- {item}" for item in payload.get("observations", []))
    lines.extend(
        [
            "",
            "## 数据集序列",
            "",
            "| Training Run | Accepted | Grounded | Action Protocol | Min Share | Balance | Model Runs |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for row in payload["rows"]:
        lines.append(
            f"| `{row.get('training_run', '')}` | {row.get('accepted_examples', '')} | "
            f"{row.get('rag_grounded_answer_count', '')} | {row.get('action_protocol_count', '')} | "
            f"{row.get('min_task_share', '')} | {row.get('task_balance_status', '')} | "
            f"{', '.join(row.get('model_runs', []))} |"
        )
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- 这个页面更适合做研究复盘：先看数据怎么变，再看模型是否已经跟上验证。",
            "- 如果数据集配比已经修正，但模型仍停留在候选或未评测状态，当前缺的是实验闭环，不是继续改数据。",
            "",
        ]
    )
    return "\n".join(lines)


def _platform_evolution_to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 平台演进路线",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        f"- 北极星：{payload.get('north_star', '')}",
        "",
        "## 分层",
        "",
        "| Plane | Primary | Owns | Entry Condition |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| `{row.get('name', '')}` | {row.get('primary', '')} | "
            f"{', '.join(row.get('owns', []))} | {row.get('entry_condition', '')} |"
        )
    lines.extend(["", "## 推荐引入顺序", ""])
    lines.extend(f"- {item}" for item in payload.get("adoption_order", []))
    lines.extend(["", "## 明确避免", ""])
    lines.extend(f"- {item}" for item in payload.get("anti_patterns", []))
    lines.append("")
    return "\n".join(lines)


def _distributed_execution_overview_to_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# 分布式执行目录",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        "## 汇总",
        "",
        f"- 标准 workload：`{summary.get('workloads', 0)}`",
        f"- 需要 GPU 的 workload：`{summary.get('gpu_workloads', 0)}`",
        f"- 逻辑队列：`{summary.get('queues', 0)}`",
        "",
        "## 队列分布",
        "",
        "| Queue | Count |",
        "| --- | ---: |",
    ]
    for queue, count in sorted((payload.get("queue_counts") or {}).items()):
        lines.append(f"| `{queue}` | {count} |")
    lines.extend(
        [
            "",
            "## Workloads",
            "",
            "| Workload | Queue | Priority | CPU | GPU | Memory GB | Expected Outputs |",
            "| --- | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in payload["rows"]:
        resources = row.get("resources") if isinstance(row.get("resources"), dict) else {}
        lines.append(
            f"| `{row.get('id', '')}` | {row.get('queue', '')} | {row.get('priority', '')} | "
            f"{resources.get('cpu', '')} | {resources.get('gpu', '')} | {resources.get('memory_gb', '')} | "
            f"{', '.join(row.get('expected_outputs', []))} |"
        )
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- 这里定义的是未来进入 Ray 执行面的标准任务类型，不代表当前已经真的派发到集群。",
            "- 先把 queue / priority / resource profile 固定下来，可以避免后续接入分布式时把治理逻辑做散。",
            "",
        ]
    )
    return "\n".join(lines)


def _distributed_dispatch_candidates_to_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# 分布式派发候选",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        "## 汇总",
        "",
        f"- 当前可包装为分布式 job 的待办：`{summary.get('dispatchable', 0)}`",
        "",
        "## 按 workload",
        "",
        "| Workload | Count |",
        "| --- | ---: |",
    ]
    for workload, count in sorted((summary.get("workload_counts") or {}).items()):
        lines.append(f"| `{workload}` | {count} |")
    lines.extend(
        [
            "",
            "## 候选",
            "",
            "| Model Run | Next Action | Workload | Queue | Priority | CPU | GPU | Reason |",
            "| --- | --- | --- | --- | --- | ---: | ---: | --- |",
        ]
    )
    for row in payload["rows"]:
        resources = row.get("resources") if isinstance(row.get("resources"), dict) else {}
        lines.append(
            f"| `{row.get('model_run', '')}` | `{row.get('next_action', '')}` | `{row.get('workload', '')}` | "
            f"{row.get('queue', '')} | {row.get('priority', '')} | {resources.get('cpu', '')} | "
            f"{resources.get('gpu', '')} | {row.get('reason', '')} |"
        )
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- 这里把现有实验队列翻译成未来 Ray job 的候选清单。",
            "- `apply_remediation_then_retrain` 之类仍需人类设计的数据修复动作，不会被伪装成可直接派发的 job。",
            "",
        ]
    )
    return "\n".join(lines)


def _project_model_program_overview_to_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    first_build = (
        payload.get("recommended_first_build")
        if isinstance(payload.get("recommended_first_build"), dict)
        else {}
    )
    lines = [
        "# 项目大模型路线",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        f"- 北极星：{payload.get('north_star', '')}",
        f"- 数据源：`{summary.get('sources', 0)}`",
        f"- 训练任务：`{summary.get('tasks', 0)}`",
        f"- Benchmark：`{summary.get('benchmarks', 0)}`",
        f"- 阶段：`{summary.get('stages', 0)}`",
        "",
        "## 推荐首建",
        "",
        f"- ID：`{first_build.get('id', '')}`",
        f"- 目标：{first_build.get('goal', '')}",
        f"- 成功指标：{', '.join(first_build.get('success_metrics', []))}",
        "",
        "## 数据源",
        "",
        "| Source | Tier | Modalities | Weight | Governance |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for row in payload.get("sources", []):
        lines.append(
            f"| `{row.get('id', '')}` | {row.get('tier', '')} | "
            f"{', '.join(row.get('modalities', []))} | {row.get('sampling_weight', '')} | "
            f"{row.get('license_policy', '')} |"
        )
    lines.extend(
        [
            "",
            "## 训练阶段",
            "",
            "| Stage | Kind | Objective | Task Mix |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in payload.get("stages", []):
        task_mix = ", ".join(
            f"{item.get('task_id', '')}:{item.get('weight', '')}"
            for item in row.get("task_mix", [])
            if isinstance(item, dict)
        )
        lines.append(
            f"| `{row.get('id', '')}` | {row.get('kind', '')} | {row.get('objective', '')} | {task_mix} |"
        )
    lines.extend(
        [
            "",
            "## Benchmark",
            "",
            "| Benchmark | Capability | Metrics | Gate |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in payload.get("benchmarks", []):
        lines.append(
            f"| `{row.get('id', '')}` | {row.get('capability_slice', '')} | "
            f"{', '.join(row.get('primary_metrics', []))} | {row.get('stage_gate', '')} |"
        )
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- 这不是一次 GPU 任务，而是项目级模型的控制面蓝图。",
            "- 当前最值得先做的是 `repo_memory_v1`：先把项目表示、证据检索和 holdout 评测跑通，再决定何时扩大到互联网级继续预训练。",
            "",
        ]
    )
    return "\n".join(lines)


def _training_platform_blueprint_overview_to_markdown(payload: dict[str, Any]) -> str:
    priority = payload.get("current_priority") if isinstance(payload.get("current_priority"), dict) else {}
    lines = [
        "# 训练平台蓝图",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        f"- 北极星：{payload.get('north_star', '')}",
        f"- 当前路线：`{priority.get('route', '')}`",
        f"- 当前 Plane：`{priority.get('plane', '')}`",
        f"- 下一批建设：{', '.join(priority.get('next_builds', []))}",
        "",
        "## 路线记忆",
        "",
    ]
    lines.extend(f"- {item}" for item in payload.get("route_memory", []))
    lines.extend(
        [
            "",
            "## 四大 Plane",
            "",
            "| Plane | Purpose | State | Owns |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in payload.get("planes", []):
        lines.append(
            f"| `{row.get('id', '')}` | {row.get('purpose', '')} | {row.get('current_state', '')} | "
            f"{', '.join(row.get('owns', []))} |"
        )
    lines.extend(
        [
            "",
            "## 关键旋钮",
            "",
            "| Knob | Meaning | Affects |",
            "| --- | --- | --- |",
        ]
    )
    for row in payload.get("knobs", []):
        lines.append(
            f"| `{row.get('id', '')}` | {row.get('meaning', '')} | {', '.join(row.get('affects', []))} |"
        )
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- 这个页面固定四项硬能力与 A→B→C 路线，不让后续开发漂移。",
            "- `training_recipe` 与 `ablation_plan` 属于 Training Studio Plane；它们先于蒸馏链落地，是为了让后续实验可解释、可比较。",
            "",
        ]
    )
    return "\n".join(lines)


def _distillation_overview_to_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# 蒸馏控制面",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        f"- 教师模型：`{summary.get('teachers', 0)}`",
        f"- 教师任务：`{summary.get('teacher_tasks', 0)}`",
        "",
        "## Teachers",
        "",
        "| Teacher | Provider | Model | Role | Strengths | Cost |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload.get("teachers", []):
        lines.append(
            f"| `{row.get('id', '')}` | {row.get('provider', '')} | `{row.get('model', '')}` | "
            f"{row.get('role', '')} | {', '.join(row.get('strengths', []))} | {row.get('cost_tier', '')} |"
        )
    lines.extend(
        [
            "",
            "## Teacher Tasks",
            "",
            "| Task | Capability | Requires Evidence | Quality Checks |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in payload.get("tasks", []):
        lines.append(
            f"| `{row.get('id', '')}` | {row.get('capability', '')} | {row.get('requires_evidence', '')} | "
            f"{', '.join(row.get('quality_checks', []))} |"
        )
    lines.extend(["", "## 说明", ""])
    lines.extend(f"- {note}" for note in payload.get("notes", []))
    lines.append("")
    return "\n".join(lines)


def _training_remediation_to_markdown(payload: dict[str, Any]) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        "# 下一轮训练修复建议",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
        "## 汇总",
        "",
        f"- 需要修复建议的模型数：`{summary.get('models_with_recommendations', 0)}`",
        "",
        "## 高频动作",
        "",
        "| Action | Count |",
        "| --- | ---: |",
    ]
    for action, count in sorted((summary.get("action_counts") or {}).items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| `{action}` | {count} |")
    lines.extend(
        [
            "",
            "## 按模型查看",
            "",
            "| Model Run | Dataset | Balance | Rarest Tasks | Recommended Actions | Current Task Support | Underrepresented Tasks |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload["rows"]:
        support = ", ".join(f"{task}:{count}" for task, count in sorted((row.get("task_support") or {}).items()))
        under = ", ".join(
            f"{item.get('task')}:{item.get('count')}"
            for item in row.get("underrepresented_tasks", [])
            if isinstance(item, dict)
        )
        lines.append(
            f"| `{row.get('model_run', '')}` | `{row.get('dataset_id', '')}` | "
            f"{row.get('min_task_share', '')} {row.get('task_balance_status', '')} | "
            f"{', '.join(row.get('rarest_tasks', []))} | {', '.join(row.get('actions', []))} | {support} | {under} |"
        )
    lines.extend(
        [
            "",
            "## 读法",
            "",
            "- 这里不是自动下训练命令，而是把门禁失败翻译成下一轮数据设计线索。",
            "- 如果某个失败对应任务在当前数据里极少，优先补样本配比；如果样本已经很多仍失败，再考虑 prompt、格式或模型结构问题。",
            "",
        ]
    )
    return "\n".join(lines)


def _lineage_to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 训练证据谱系",
        "",
        f"生成时间：`{payload['generated_at']}`",
        "",
    ]
    for dataset in payload["datasets"]:
        mix = ", ".join(f"{k}:{v}" for k, v in sorted((dataset.get("task_mix") or {}).items()))
        lines.extend(
            [
                f"## `{dataset.get('dataset_id', '')}`",
                "",
                f"- 训练数据 run：`{dataset.get('training_run', '')}`",
                f"- 质量：`{dataset.get('quality_score', '')}` {dataset.get('quality_grade', '')}",
                f"- 任务配比：{mix}",
                "",
                "| Model Run | Model Version | Base Model | Job | Eval Count | Promotion |",
                "| --- | --- | --- | --- | ---: | --- |",
            ]
        )
        for model in dataset.get("model_runs", []):
            promotion_rows = model.get("promotion_decisions", [])
            latest_promotion = promotion_rows[-1].get("status", "") if promotion_rows else ""
            lines.append(
                f"| `{model.get('model_run', '')}` | `{model.get('model_version', '')}` | "
                f"`{model.get('base_model', '')}` | {model.get('job_status', '')} | "
                f"{len(model.get('evaluations', []))} | {latest_promotion} |"
            )
        lines.append("")
    lines.extend(
        [
            "## 基线评测",
            "",
            "| Eval | Label | Benchmark | Overall |",
            "| --- | --- | --- | ---: |",
        ]
    )
    for row in payload["baseline_evaluations"]:
        lines.append(
            f"| `{row.get('evaluation_run', '')}` | `{row.get('label', '')}` | "
            f"{row.get('benchmark', '')} | {row.get('overall_score', '')} |"
        )
    lines.extend(
        [
            "",
            "## 尚未精确挂接的候选评测",
            "",
            "| Eval | Label | Benchmark | Overall |",
            "| --- | --- | --- | ---: |",
        ]
    )
    for row in payload["unlinked_candidate_evaluations"]:
        lines.append(
            f"| `{row.get('evaluation_run', '')}` | `{row.get('label', '')}` | "
            f"{row.get('benchmark', '')} | {row.get('overall_score', '')} |"
        )
    lines.extend(
        [
            "",
            "## 尚未精确挂接的晋级决策",
            "",
            "| Decision | Label | Benchmark | Status |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in payload["unlinked_promotion_decisions"]:
        lines.append(
            f"| `{row.get('decision_run', '')}` | `{row.get('label', '')}` | "
            f"{row.get('benchmark', '')} | {row.get('status', '')} |"
        )
    lines.append("")
    if payload.get("notes"):
        lines.extend(["## 说明", ""])
        lines.extend(f"- {note}" for note in payload["notes"])
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    payload = {
        "schema": "research_training_overview.v1",
        "generated_at": _now(),
        "summary": {},
        "training_runs": _training_runs(),
        "model_runs": _model_runs(),
        "model_evals": _model_evals(),
        "promotion_decisions": _promotion_decisions(),
    }
    payload["summary"] = {
        "training_runs": len(payload["training_runs"]),
        "model_runs": len(payload["model_runs"]),
        "model_evals": len(payload["model_evals"]),
        "promotion_decisions": len(payload["promotion_decisions"]),
        "task_balance_watch_runs": sum(
            1 for row in payload["training_runs"] if row.get("task_balance_status") == "watch"
        ),
    }
    comparison = _evaluation_comparison(payload["model_evals"])
    metrics = _metric_explainer()
    promotion_overview = _promotion_overview(payload["promotion_decisions"])
    experiment_queue = _experiment_queue(
        payload["training_runs"],
        payload["model_runs"],
        payload["model_evals"],
        payload["promotion_decisions"],
    )
    dataset_evolution = _dataset_evolution(payload["training_runs"], payload["model_runs"])
    platform_evolution = _platform_evolution()
    distributed_execution = _distributed_execution_overview()
    distributed_dispatch = _distributed_dispatch_candidates(experiment_queue)
    project_model_program = _project_model_program_overview()
    training_platform_blueprint = _training_platform_blueprint_overview()
    distillation_overview = _distillation_overview()
    remediation = _training_remediation(
        payload["training_runs"],
        payload["model_runs"],
        payload["promotion_decisions"],
    )
    lineage = _training_lineage(
        payload["training_runs"],
        payload["model_runs"],
        payload["model_evals"],
        payload["promotion_decisions"],
    )

    dashboard_dir = WORKBENCH / "dashboards"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "training_overview.json": json.dumps(payload, ensure_ascii=False, indent=2),
        "training_overview.md": _to_markdown(payload),
        "experiment_comparison.json": json.dumps(comparison, ensure_ascii=False, indent=2),
        "experiment_comparison.md": _comparison_to_markdown(comparison),
        "metric_explainer.json": json.dumps(metrics, ensure_ascii=False, indent=2),
        "metric_explainer.md": _metric_explainer_to_markdown(metrics),
        "promotion_overview.json": json.dumps(promotion_overview, ensure_ascii=False, indent=2),
        "promotion_overview.md": _promotion_overview_to_markdown(promotion_overview),
        "experiment_queue.json": json.dumps(experiment_queue, ensure_ascii=False, indent=2),
        "experiment_queue.md": _experiment_queue_to_markdown(experiment_queue),
        "dataset_evolution.json": json.dumps(dataset_evolution, ensure_ascii=False, indent=2),
        "dataset_evolution.md": _dataset_evolution_to_markdown(dataset_evolution),
        "platform_evolution.json": json.dumps(platform_evolution, ensure_ascii=False, indent=2),
        "platform_evolution.md": _platform_evolution_to_markdown(platform_evolution),
        "distributed_execution.json": json.dumps(distributed_execution, ensure_ascii=False, indent=2),
        "distributed_execution.md": _distributed_execution_overview_to_markdown(distributed_execution),
        "distributed_dispatch_candidates.json": json.dumps(distributed_dispatch, ensure_ascii=False, indent=2),
        "distributed_dispatch_candidates.md": _distributed_dispatch_candidates_to_markdown(distributed_dispatch),
        "project_model_program.json": json.dumps(project_model_program, ensure_ascii=False, indent=2),
        "project_model_program.md": _project_model_program_overview_to_markdown(project_model_program),
        "training_platform_blueprint.json": json.dumps(training_platform_blueprint, ensure_ascii=False, indent=2),
        "training_platform_blueprint.md": _training_platform_blueprint_overview_to_markdown(training_platform_blueprint),
        "distillation_overview.json": json.dumps(distillation_overview, ensure_ascii=False, indent=2),
        "distillation_overview.md": _distillation_overview_to_markdown(distillation_overview),
        "training_remediation.json": json.dumps(remediation, ensure_ascii=False, indent=2),
        "training_remediation.md": _training_remediation_to_markdown(remediation),
        "training_lineage.json": json.dumps(lineage, ensure_ascii=False, indent=2),
        "training_lineage.md": _lineage_to_markdown(lineage),
    }
    for name, text in outputs.items():
        (dashboard_dir / name).write_text(text, encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
