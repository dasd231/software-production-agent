"""Human-facing training-studio contracts above executable job specs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}-{digest}"


def list_training_platform_planes() -> list[dict[str, Any]]:
    """Return the four top-level planes of the research training platform."""

    return [
        {
            "id": "distillation_plane",
            "label": "Distillation Plane",
            "purpose": "Absorb capabilities from stronger external or internal teacher models.",
            "owns": [
                "teacher registry",
                "teacher task suite",
                "distillation datasets",
                "teacher output quality gates",
            ],
            "current_state": "active_build",
        },
        {
            "id": "corpus_intelligence_plane",
            "label": "Corpus Intelligence Plane",
            "purpose": "Turn internet repositories into governed, labeled and re-samplable project assets.",
            "owns": [
                "crawler",
                "repo labels",
                "quality taxonomy",
                "provenance and dedup",
            ],
            "current_state": "foundation_exists",
        },
        {
            "id": "training_studio_plane",
            "label": "Training Studio Plane",
            "purpose": "Expose transparent, adjustable recipes, knobs and ablations to the researcher.",
            "owns": [
                "training recipes",
                "knob registry",
                "ablation plans",
                "experiment cards",
            ],
            "current_state": "active_build",
        },
        {
            "id": "benchmark_research_plane",
            "label": "Benchmark & Research Plane",
            "purpose": "Compare against internal baselines, market models and paper claims under shared metrics.",
            "owns": [
                "benchmark registry",
                "external model registry",
                "paper claim matrix",
                "comparison dashboards",
            ],
            "current_state": "skeleton_exists",
        },
    ]


def list_training_knobs() -> list[dict[str, Any]]:
    """Expose the user-adjustable knobs that should remain visible in recipes."""

    return [
        {
            "id": "objective",
            "label": "Training objective",
            "meaning": "What signal the model optimizes against.",
            "recommended_values": ["sft", "retrieval_contrastive", "distillation_sft", "continued_pretraining"],
            "affects": ["capability_target", "loss", "dataset_shape"],
        },
        {
            "id": "base_model",
            "label": "Base model",
            "meaning": "The starting model before any adaptation.",
            "recommended_values": ["open-weight coder model", "general reasoning model"],
            "affects": ["ceiling", "cost", "serving_compatibility"],
        },
        {
            "id": "task_mix",
            "label": "Task mix",
            "meaning": "How much weight each capability slice receives.",
            "recommended_values": ["sum_to_1.0", "min_task_share>=0.05"],
            "affects": ["capability_balance", "regression_risk"],
        },
        {
            "id": "data_mix",
            "label": "Data-source mix",
            "meaning": "How training examples are sourced across corpora or builders.",
            "recommended_values": ["governed_sources_only", "source_refs_attached"],
            "affects": ["coverage", "license_risk", "generalization"],
        },
        {
            "id": "teacher_mix",
            "label": "Teacher mix",
            "meaning": "Which teacher models contribute supervision when distillation is enabled.",
            "recommended_values": ["single_teacher", "multi_teacher_consensus"],
            "affects": ["quality", "cost", "style_bias"],
        },
        {
            "id": "context_window",
            "label": "Context window",
            "meaning": "Prompt budget used by the model or reader.",
            "recommended_values": [8192, 32768, 65536],
            "affects": ["latency", "memory", "long_context_behavior"],
        },
        {
            "id": "adapter_method",
            "label": "Adaptation method",
            "meaning": "How parameters are updated.",
            "recommended_values": ["lora", "qlora", "full_finetune"],
            "affects": ["gpu_memory", "trainable_parameters", "merge_strategy"],
        },
        {
            "id": "evaluation_suite",
            "label": "Evaluation suite",
            "meaning": "What benchmark set gates the experiment.",
            "recommended_values": ["internal_holdout", "public_repo_benchmarks", "paper_reproduction_suite"],
            "affects": ["promotion_gate", "paper_comparability"],
        },
    ]


def build_training_platform_blueprint() -> dict[str, Any]:
    """Describe the higher-order training platform the user requested."""

    planes = list_training_platform_planes()
    return {
        "schema": "training_platform_blueprint.v1",
        "generated_at": _now(),
        "north_star": "Transparent, adjustable and research-comparable training for project-level models.",
        "route_memory": [
            "A: build the platform top level first",
            "B: add distillation next",
            "C: thicken paper-grade comparison after that",
        ],
        "required_capabilities": [
            {
                "id": "distill_other_models",
                "label": "蒸馏其他模型",
                "plane": "distillation_plane",
            },
            {
                "id": "crawl_label_train_projects",
                "label": "爬取优质项目、打标签并训练",
                "plane": "corpus_intelligence_plane",
            },
            {
                "id": "transparent_adjustable_training",
                "label": "模型设计与训练方法快捷透明可调",
                "plane": "training_studio_plane",
            },
            {
                "id": "market_and_paper_comparison",
                "label": "与市场模型和同方向论文对比",
                "plane": "benchmark_research_plane",
            },
        ],
        "planes": planes,
        "knobs": list_training_knobs(),
        "current_priority": {
            "route": "B",
            "plane": "distillation_plane",
            "next_builds": [
                "teacher_prompt_batch",
                "teacher_execution_plan",
                "teacher_execution_run",
                "first_training_round_plan",
            ],
        },
    }


def _normalize_weight_map(raw: dict[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in sorted((raw or {}).items()):
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if weight > 0:
            out[str(key)] = round(weight, 6)
    return out


def _normalise_string_list(values: list[str] | tuple[str, ...] | None) -> list[str]:
    return [str(value) for value in (values or []) if str(value).strip()]


def _recipe_validation(task_mix: dict[str, float], objective: str) -> dict[str, Any]:
    task_total = round(sum(task_mix.values()), 6)
    min_task_share = min(task_mix.values()) if task_mix else 0.0
    warnings: list[str] = []
    blockers: list[str] = []
    if task_mix and abs(task_total - 1.0) > 1e-6:
        blockers.append("task_mix_must_sum_to_1")
    if task_mix and min_task_share < 0.05:
        warnings.append("min_task_share_below_recommended_floor")
    return {
        "ok": not blockers,
        "task_mix_total": task_total,
        "min_task_share": round(min_task_share, 6),
        "warnings": warnings,
        "blockers": blockers,
    }


def build_training_recipe(
    *,
    name: str,
    research_question: str,
    base_model: str,
    objective: str,
    task_mix: dict[str, Any] | None = None,
    data_mix: dict[str, Any] | None = None,
    teacher_mix: dict[str, Any] | None = None,
    method: dict[str, Any] | None = None,
    evaluation_suite: list[str] | tuple[str, ...] | None = None,
    knobs: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    """Build a human-facing recipe that explains a research run before execution."""

    normalized_task_mix = _normalize_weight_map(task_mix)
    normalized_data_mix = _normalize_weight_map(data_mix)
    normalized_teacher_mix = _normalize_weight_map(teacher_mix)
    validation = _recipe_validation(normalized_task_mix, objective)
    body = {
        "schema": "training_recipe.v1",
        "created_at": _now(),
        "name": name,
        "research_question": research_question,
        "base_model": base_model,
        "objective": objective,
        "task_mix": normalized_task_mix,
        "data_mix": normalized_data_mix,
        "teacher_mix": normalized_teacher_mix,
        "method": dict(method or {}),
        "evaluation_suite": _normalise_string_list(evaluation_suite),
        "knobs": dict(knobs or {}),
        "notes": notes,
        "validation": validation,
    }
    identity = {key: value for key, value in body.items() if key != "created_at"}
    body["recipe_id"] = _stable_id("recipe", identity)
    return body


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(dict(out[key]), value)
        else:
            out[key] = value
    return out


def _changed_paths(base: Any, variant: Any, prefix: str = "") -> list[str]:
    if isinstance(base, dict) and isinstance(variant, dict):
        keys = sorted(set(base) | set(variant))
        paths: list[str] = []
        for key in keys:
            child = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_changed_paths(base.get(key), variant.get(key), child))
        return paths
    if base != variant:
        return [prefix]
    return []


def build_ablation_plan(
    *,
    name: str,
    research_question: str,
    baseline_recipe: dict[str, Any],
    variants: list[dict[str, Any]],
    primary_metrics: list[str] | tuple[str, ...],
    success_criteria: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    """Build one-variable-ish experiment variants from a baseline recipe."""

    variant_rows: list[dict[str, Any]] = []
    for raw in variants:
        variant_name = str(raw.get("name", "") or "").strip()
        patch = raw.get("patch") if isinstance(raw.get("patch"), dict) else {}
        purpose = str(raw.get("purpose", "") or "")
        merged = _deep_merge(
            {key: value for key, value in baseline_recipe.items() if key not in {"recipe_id", "created_at"}},
            patch,
        )
        recipe = build_training_recipe(
            name=str(merged.get("name", variant_name or baseline_recipe.get("name", ""))),
            research_question=str(merged.get("research_question", research_question)),
            base_model=str(merged.get("base_model", "")),
            objective=str(merged.get("objective", "")),
            task_mix=merged.get("task_mix") if isinstance(merged.get("task_mix"), dict) else {},
            data_mix=merged.get("data_mix") if isinstance(merged.get("data_mix"), dict) else {},
            teacher_mix=merged.get("teacher_mix") if isinstance(merged.get("teacher_mix"), dict) else {},
            method=merged.get("method") if isinstance(merged.get("method"), dict) else {},
            evaluation_suite=merged.get("evaluation_suite") if isinstance(merged.get("evaluation_suite"), list) else [],
            knobs=merged.get("knobs") if isinstance(merged.get("knobs"), dict) else {},
            notes=str(merged.get("notes", "")),
        )
        changed = [
            path
            for path in _changed_paths(
                {key: value for key, value in baseline_recipe.items() if key not in {"recipe_id", "created_at", "validation"}},
                {key: value for key, value in recipe.items() if key not in {"recipe_id", "created_at", "validation"}},
            )
            if path not in {"name"}
        ]
        variant_rows.append(
            {
                "name": variant_name or recipe["name"],
                "purpose": purpose,
                "patch": patch,
                "recipe": recipe,
                "changed_paths": changed,
                "change_count": len(changed),
            }
        )
    body = {
        "schema": "ablation_plan.v1",
        "created_at": _now(),
        "name": name,
        "research_question": research_question,
        "baseline_recipe": baseline_recipe,
        "variants": variant_rows,
        "primary_metrics": _normalise_string_list(primary_metrics),
        "success_criteria": _normalise_string_list(success_criteria),
        "validation": {
            "ok": all(row["recipe"].get("validation", {}).get("ok") for row in variant_rows),
            "variant_count": len(variant_rows),
            "single_change_variants": sum(1 for row in variant_rows if row["change_count"] == 1),
            "multi_change_variants": sum(1 for row in variant_rows if row["change_count"] > 1),
        },
    }
    identity = {key: value for key, value in body.items() if key != "created_at"}
    body["ablation_id"] = _stable_id("ablation", identity)
    return body
