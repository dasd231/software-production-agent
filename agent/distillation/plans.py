"""Plans for teacher-task suites and distillation experiments."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from agent.distillation.catalog import list_teacher_models, list_teacher_tasks


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}-{digest}"


def _weight_map(raw: dict[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in sorted((raw or {}).items()):
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if weight > 0:
            out[str(key)] = round(weight, 6)
    return out


def build_teacher_task_suite(
    *,
    name: str,
    task_mix: dict[str, Any] | None = None,
    evidence_policy: str = "required",
) -> dict[str, Any]:
    tasks = {row["id"]: row for row in list_teacher_tasks()}
    normalized_mix = _weight_map(task_mix) or {
        "teacher_repo_grounded_qa": 0.30,
        "teacher_architecture_summary": 0.25,
        "teacher_symbol_localization": 0.20,
        "teacher_issue_to_code": 0.15,
        "teacher_change_impact": 0.10,
    }
    missing = [task_id for task_id in normalized_mix if task_id not in tasks]
    total = round(sum(normalized_mix.values()), 6)
    rows = [
        {
            "task_id": task_id,
            "weight": weight,
            "task": tasks.get(task_id, {}),
        }
        for task_id, weight in normalized_mix.items()
    ]
    body = {
        "schema": "teacher_task_suite.v1",
        "created_at": _now(),
        "name": name,
        "task_mix": normalized_mix,
        "tasks": rows,
        "evidence_policy": evidence_policy,
        "validation": {
            "ok": not missing and abs(total - 1.0) <= 1e-6,
            "missing_tasks": missing,
            "task_mix_total": total,
            "requires_evidence_tasks": [
                task_id for task_id, row in tasks.items() if task_id in normalized_mix and row.get("requires_evidence")
            ],
        },
    }
    body["suite_id"] = _stable_id("suite", {k: v for k, v in body.items() if k != "created_at"})
    return body


def build_distillation_plan(
    *,
    name: str,
    student_model: str,
    teacher_mix: dict[str, Any],
    task_suite: dict[str, Any],
    target_recipe_id: str = "",
    consensus_policy: str = "single_teacher",
    output_policy: str = "concise_grounded_answer",
    acceptance_thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    teachers = {row["id"]: row for row in list_teacher_models()}
    normalized_mix = _weight_map(teacher_mix)
    missing_teachers = [teacher_id for teacher_id in normalized_mix if teacher_id not in teachers]
    total = round(sum(normalized_mix.values()), 6)
    thresholds = {
        "min_citation_rate": 1.0,
        "min_grounded_rate": 0.95,
        "max_rejection_rate": 0.25,
        **(acceptance_thresholds or {}),
    }
    body = {
        "schema": "distillation_plan.v1",
        "created_at": _now(),
        "name": name,
        "student_model": student_model,
        "teacher_mix": normalized_mix,
        "teachers": [
            {"teacher_id": teacher_id, "weight": weight, "teacher": teachers.get(teacher_id, {})}
            for teacher_id, weight in normalized_mix.items()
        ],
        "task_suite": task_suite,
        "target_recipe_id": target_recipe_id,
        "consensus_policy": consensus_policy,
        "output_policy": output_policy,
        "acceptance_thresholds": thresholds,
        "validation": {
            "ok": (
                bool(normalized_mix)
                and not missing_teachers
                and abs(total - 1.0) <= 1e-6
                and bool(task_suite.get("validation", {}).get("ok"))
            ),
            "teacher_mix_total": total,
            "missing_teachers": missing_teachers,
            "teacher_count": len(normalized_mix),
            "task_suite_ok": bool(task_suite.get("validation", {}).get("ok")),
        },
    }
    body["distillation_id"] = _stable_id("distill", {k: v for k, v in body.items() if k != "created_at"})
    return body
