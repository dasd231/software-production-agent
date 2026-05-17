"""Prompt builders for project-model teacher distillation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from agent.distillation.catalog import list_teacher_models, list_teacher_tasks


TASK_TYPE_TO_TEACHER_TASK: dict[str, str] = {
    "repo_grounded_qa": "teacher_repo_grounded_qa",
    "architecture_summary": "teacher_architecture_summary",
    "symbol_grounding": "teacher_symbol_localization",
    "issue_to_code_localization": "teacher_issue_to_code",
    "change_impact_reasoning": "teacher_change_impact",
}

TEACHER_TASK_TO_STUDENT_TASK: dict[str, str] = {
    "teacher_repo_grounded_qa": "repo_grounded_qa",
    "teacher_architecture_summary": "architecture_summary",
    "teacher_symbol_localization": "symbol_grounding",
    "teacher_issue_to_code": "issue_to_code_localization",
    "teacher_change_impact": "change_impact_reasoning",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}-{digest}"


def _normalized_citations(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        if not path:
            continue
        row: dict[str, Any] = {"path": path}
        for key in ("line", "start_line", "end_line"):
            value = item.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value > 0:
                row[key] = value
        rows.append(row)
    return rows


def _teacher_task_id(example: dict[str, Any]) -> str:
    metadata = example.get("metadata") if isinstance(example.get("metadata"), dict) else {}
    explicit = str(metadata.get("teacher_task_id", "") or example.get("teacher_task_id", "") or "").strip()
    if explicit:
        return explicit
    return TASK_TYPE_TO_TEACHER_TASK.get(str(example.get("task_type", "") or ""), "")


def _weighted_teacher_pick(example_id: str, teacher_mix: dict[str, Any]) -> str:
    rows: list[tuple[str, float]] = []
    for key, value in sorted(teacher_mix.items()):
        try:
            weight = float(value)
        except (TypeError, ValueError):
            continue
        if weight > 0:
            rows.append((str(key), weight))
    if not rows:
        return ""
    total = sum(weight for _, weight in rows)
    digest = hashlib.blake2b(example_id.encode("utf-8", errors="ignore"), digest_size=8).digest()
    point = int.from_bytes(digest, "big") / float(2**64)
    cursor = 0.0
    for teacher_id, weight in rows:
        cursor += weight / total
        if point <= cursor:
            return teacher_id
    return rows[-1][0]


def _messages(
    *,
    task: dict[str, Any],
    example: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    system = (
        "你是项目级代码理解教师模型。"
        "只能根据用户提供的项目证据作答，不得补充无证据事实。"
        '必须返回一个 JSON 对象，键为 "output" 与 "citations"；'
        '"citations" 只能复用输入 evidence_bundle 中的条目。'
    )
    payload = {
        "teacher_task_id": task.get("id", ""),
        "capability": task.get("capability", ""),
        "expected_output": task.get("expected_output", ""),
        "instruction": str(example.get("instruction", "") or ""),
        "input": str(example.get("input", "") or ""),
        "evidence_bundle": evidence,
    }
    user = json.dumps(payload, ensure_ascii=False, indent=2)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_teacher_prompt_batch(
    *,
    distillation_plan: dict[str, Any],
    source_examples: list[dict[str, Any]],
    max_prompts: int = 0,
) -> dict[str, Any]:
    """Convert governed source examples into auditable teacher prompts."""

    teachers = {row["id"]: row for row in list_teacher_models()}
    tasks = {row["id"]: row for row in list_teacher_tasks()}
    task_suite = distillation_plan.get("task_suite") if isinstance(distillation_plan.get("task_suite"), dict) else {}
    allowed_tasks = set(
        str(task_id)
        for task_id in (task_suite.get("task_mix") if isinstance(task_suite.get("task_mix"), dict) else {})
        if str(task_id).strip()
    )
    teacher_mix = (
        distillation_plan.get("teacher_mix")
        if isinstance(distillation_plan.get("teacher_mix"), dict)
        else {}
    )

    prompts: list[dict[str, Any]] = []
    skipped_examples: list[dict[str, Any]] = []
    teacher_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    cap = max(int(max_prompts), 0)
    for index, example in enumerate(source_examples):
        example_id = str(example.get("example_id", "") or f"source-{index}")
        task_id = _teacher_task_id(example)
        task = tasks.get(task_id, {})
        evidence = _normalized_citations(example.get("citations"))
        reasons: list[str] = []
        if not task_id:
            reasons.append("unmapped_source_task")
        elif task_id not in tasks:
            reasons.append("unknown_teacher_task")
        elif allowed_tasks and task_id not in allowed_tasks:
            reasons.append("task_not_in_suite")
        if bool(task.get("requires_evidence")) and not evidence:
            reasons.append("missing_evidence_bundle")
        teacher_id = _weighted_teacher_pick(example_id, teacher_mix)
        if not teacher_id:
            reasons.append("missing_teacher_mix")
        elif teacher_id not in teachers:
            reasons.append("unknown_teacher")
        if cap and len(prompts) >= cap:
            reasons.append("max_prompts_limit")
        if reasons:
            skipped_examples.append(
                {
                    "example_id": example_id,
                    "task_type": str(example.get("task_type", "") or ""),
                    "teacher_task_id": task_id,
                    "reasons": reasons,
                }
            )
            continue
        student_task_type = TEACHER_TASK_TO_STUDENT_TASK.get(task_id, str(example.get("task_type", "") or "sft"))
        prompt_body = {
            "distillation_id": str(distillation_plan.get("distillation_id", "") or ""),
            "teacher_id": teacher_id,
            "teacher_task_id": task_id,
            "student_task_type": student_task_type,
            "source_example_id": example_id,
            "instruction": str(example.get("instruction", "") or ""),
            "input": str(example.get("input", "") or ""),
            "evidence_bundle": evidence,
        }
        prompt = {
            "schema": "teacher_prompt.v1",
            **prompt_body,
            "messages": _messages(task=task, example=example, evidence=evidence),
            "output_contract": {
                "format": "json_object",
                "required_keys": ["output", "citations"],
                "citation_policy": "must_reuse_prompt_evidence_only",
            },
            "metadata": {
                "source_task_type": str(example.get("task_type", "") or ""),
                "source_metadata": example.get("metadata") if isinstance(example.get("metadata"), dict) else {},
            },
        }
        prompt["prompt_id"] = _stable_id("prompt", prompt_body)
        prompts.append(prompt)
        teacher_counts[teacher_id] += 1
        task_counts[task_id] += 1
    body = {
        "schema": "teacher_prompt_batch.v1",
        "created_at": _now(),
        "distillation_id": str(distillation_plan.get("distillation_id", "") or ""),
        "counts": {
            "source_examples": len(source_examples),
            "prompts": len(prompts),
            "skipped_examples": len(skipped_examples),
        },
        "teacher_mix_observed": dict(sorted(teacher_counts.items())),
        "task_mix_observed": dict(sorted(task_counts.items())),
        "prompts": prompts,
        "skipped_examples": skipped_examples,
        "validation": {
            "ok": bool(distillation_plan.get("validation", {}).get("ok")) and bool(prompts),
            "plan_ok": bool(distillation_plan.get("validation", {}).get("ok")),
            "prompt_count": len(prompts),
            "skipped_count": len(skipped_examples),
        },
    }
    body["batch_id"] = _stable_id("promptbatch", {k: v for k, v in body.items() if k != "created_at"})
    return body
