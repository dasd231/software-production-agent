"""Dry-run-first execution contracts for teacher distillation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from agent.distillation.catalog import list_teacher_models


VALID_EXECUTION_MODES = {"dry_run", "live"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}-{digest}"


def build_teacher_execution_plan(
    *,
    distillation_plan: dict[str, Any],
    prompt_batch: dict[str, Any],
    mode: str = "dry_run",
    allow_remote: bool = False,
    max_prompts: int = 0,
    max_output_tokens: int = 1024,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Describe the teacher calls that would be made, without making them by default."""

    selected_mode = str(mode or "dry_run").strip().lower()
    teachers = {row["id"]: row for row in list_teacher_models()}
    prompts = prompt_batch.get("prompts") if isinstance(prompt_batch.get("prompts"), list) else []
    cap = max(int(max_prompts), 0)
    bounded_prompts = prompts[:cap] if cap else prompts
    teacher_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    requests: list[dict[str, Any]] = []
    blockers: list[str] = []
    if selected_mode not in VALID_EXECUTION_MODES:
        blockers.append("unsupported_execution_mode")
    if selected_mode == "live" and not allow_remote:
        blockers.append("live_mode_requires_allow_remote")
    if not bool(distillation_plan.get("validation", {}).get("ok")):
        blockers.append("invalid_distillation_plan")
    if not bool(prompt_batch.get("validation", {}).get("ok")):
        blockers.append("invalid_prompt_batch")
    for prompt in bounded_prompts:
        teacher_id = str(prompt.get("teacher_id", "") or "")
        teacher = teachers.get(teacher_id, {})
        task_id = str(prompt.get("teacher_task_id", "") or "")
        row = {
            "request_id": _stable_id(
                "teacherreq",
                {
                    "prompt_id": prompt.get("prompt_id", ""),
                    "teacher_id": teacher_id,
                    "task_id": task_id,
                },
            ),
            "prompt_id": str(prompt.get("prompt_id", "") or ""),
            "teacher_id": teacher_id,
            "teacher_task_id": task_id,
            "instruction": str(prompt.get("instruction", "") or ""),
            "input": str(prompt.get("input", "") or ""),
            "provider": str(teacher.get("provider", "") or ""),
            "model": str(teacher.get("model", "") or ""),
            "messages": prompt.get("messages") if isinstance(prompt.get("messages"), list) else [],
            "max_output_tokens": max(int(max_output_tokens), 1),
            "temperature": float(temperature),
            "status": "planned",
        }
        if not teacher:
            row["status"] = "blocked"
            row["blockers"] = ["unknown_teacher"]
        requests.append(row)
        if teacher_id:
            teacher_counts[teacher_id] += 1
        if task_id:
            task_counts[task_id] += 1
    body = {
        "schema": "teacher_execution_plan.v1",
        "created_at": _now(),
        "distillation_id": str(distillation_plan.get("distillation_id", "") or ""),
        "prompt_batch_id": str(prompt_batch.get("batch_id", "") or ""),
        "mode": selected_mode,
        "safety": {
            "default_mode": "dry_run",
            "allow_remote": bool(allow_remote),
            "makes_remote_calls": selected_mode == "live" and bool(allow_remote),
        },
        "limits": {
            "max_prompts": cap,
            "max_output_tokens": max(int(max_output_tokens), 1),
            "temperature": float(temperature),
        },
        "counts": {
            "available_prompts": len(prompts),
            "planned_requests": len(requests),
            "blocked_requests": sum(1 for row in requests if row.get("status") == "blocked"),
        },
        "teacher_mix_observed": dict(sorted(teacher_counts.items())),
        "task_mix_observed": dict(sorted(task_counts.items())),
        "requests": requests,
        "validation": {
            "ok": not blockers and bool(requests) and all(row.get("status") != "blocked" for row in requests),
            "blockers": blockers,
            "plan_ok": bool(distillation_plan.get("validation", {}).get("ok")),
            "prompt_batch_ok": bool(prompt_batch.get("validation", {}).get("ok")),
        },
        "next_step": (
            "review planned prompts, then rerun with mode=live and allow_remote=true"
            if selected_mode == "dry_run"
            else "execute requests with a teacher runtime adapter and review outputs"
        ),
    }
    body["execution_plan_id"] = _stable_id("teacherexec", {k: v for k, v in body.items() if k != "created_at"})
    return body
