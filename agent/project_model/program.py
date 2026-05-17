"""Top-level program builder for an internet-scale project model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.project_model.catalog import (
    list_project_benchmarks,
    list_project_corpus_sources,
    list_project_training_stages,
    list_project_training_tasks,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_catalog(
    *,
    sources: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    stages: list[dict[str, Any]],
) -> dict[str, Any]:
    source_ids = {str(row.get("id", "")) for row in sources}
    task_ids = {str(row.get("id", "")) for row in tasks}
    missing_stage_sources: dict[str, list[str]] = {}
    missing_stage_tasks: dict[str, list[str]] = {}
    invalid_stage_weights: dict[str, float] = {}
    for stage in stages:
        stage_id = str(stage.get("id", ""))
        declared_sources = [str(item) for item in stage.get("source_ids", [])]
        task_mix = stage.get("task_mix") if isinstance(stage.get("task_mix"), list) else []
        missing_sources = [item for item in declared_sources if item not in source_ids]
        missing_tasks = [
            str(item.get("task_id", ""))
            for item in task_mix
            if isinstance(item, dict) and str(item.get("task_id", "")) not in task_ids
        ]
        if missing_sources:
            missing_stage_sources[stage_id] = missing_sources
        if missing_tasks:
            missing_stage_tasks[stage_id] = missing_tasks
        if task_mix:
            weight = round(
                sum(float(item.get("weight", 0.0)) for item in task_mix if isinstance(item, dict)),
                6,
            )
            if abs(weight - 1.0) > 1e-6:
                invalid_stage_weights[stage_id] = weight
    retrieval_stage_ids = {
        str(stage.get("id", ""))
        for stage in stages
        if any(
            isinstance(item, dict) and str(item.get("task_id", "")) == "evidence_retrieval"
            for item in (stage.get("task_mix") or [])
        )
    }
    qa_stage_ids = {
        str(stage.get("id", ""))
        for stage in stages
        if any(
            isinstance(item, dict) and str(item.get("task_id", "")) == "repo_grounded_qa"
            for item in (stage.get("task_mix") or [])
        )
    }
    return {
        "ok": not any((missing_stage_sources, missing_stage_tasks, invalid_stage_weights))
        and bool(retrieval_stage_ids & qa_stage_ids),
        "missing_stage_sources": missing_stage_sources,
        "missing_stage_tasks": missing_stage_tasks,
        "invalid_stage_weights": invalid_stage_weights,
        "retrieval_before_or_with_qa": bool(retrieval_stage_ids & qa_stage_ids),
    }


def _weighted_source_total(sources: list[dict[str, Any]]) -> float:
    return round(sum(float(row.get("sampling_weight", 0.0)) for row in sources), 6)


def build_project_model_program(
    *,
    ambition: str = "internet_scale",
    target_context_tokens: int = 32768,
) -> dict[str, Any]:
    """Return the canonical control-plane plan for the project-model direction."""

    sources = list_project_corpus_sources()
    tasks = list_project_training_tasks()
    benchmarks = list_project_benchmarks()
    stages = list_project_training_stages()
    validation = _validate_catalog(sources=sources, tasks=tasks, stages=stages)
    return {
        "schema": "project_model_program.v1",
        "generated_at": _now(),
        "ambition": ambition,
        "north_star": "Maximize repository understanding per token, not repository tokens per prompt.",
        "target_context_tokens": max(int(target_context_tokens), 1),
        "data_doctrine": {
            "posture": "maximal_open_web_coverage_under_governance",
            "rules": [
                "Prefer open, provenance-preserving sources over blind scraping.",
                "Keep repo_id, commit, path, span, source URL and license with every sample.",
                "Train code, docs, dependency manifests, tests and evolution traces as one linked project object.",
                "Near-duplicate removal and contamination checks happen before training, not after model surprise.",
            ],
        },
        "architecture_doctrine": {
            "preferred_shape": "retriever_reader_plus_project_memory",
            "anti_goals": [
                "Do not equate larger context windows with project understanding.",
                "Do not collapse project-model work into generic code completion only.",
                "Do not let web-scale ingestion bypass license, provenance or dedup gates.",
            ],
        },
        "compute_policy": {
            "default_mode": "control_plane_only",
            "operator_rule": "No heavy GPU job starts implicitly from planning code.",
            "current_practical_path": [
                "Prototype retrieval and repo-memory tasks on small held-out corpora.",
                "Use LoRA/SFT and contrastive retrieval experiments on available single-node GPUs.",
                "Reserve full continued pretraining or foundation-model work for dedicated external compute.",
            ],
        },
        "summary": {
            "sources": len(sources),
            "source_sampling_weight_total": _weighted_source_total(sources),
            "tasks": len(tasks),
            "benchmarks": len(benchmarks),
            "stages": len(stages),
        },
        "sources": sources,
        "tasks": tasks,
        "benchmarks": benchmarks,
        "stages": stages,
        "recommended_first_build": {
            "id": "repo_memory_v1",
            "goal": "Build retrieval-grounded project memory before attempting internet-scale continued pretraining.",
            "inputs": [
                "repository snapshot",
                "docs/README/ADR",
                "dependency manifests",
                "tests and CI",
            ],
            "outputs": [
                "project map",
                "symbol index",
                "evidence index",
                "grounded QA samples",
                "holdout evaluation report",
            ],
            "success_metrics": [
                "recall_at_5",
                "citation_precision",
                "architecture_summary_faithfulness",
                "tokens_per_correct_answer",
            ],
        },
        "validation": validation,
    }
