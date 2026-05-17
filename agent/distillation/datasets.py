"""Dataset manifests for teacher-generated supervision."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}-{digest}"


def _teacher_output_status(row: dict[str, Any]) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    task_id = str(row.get("task_id", "") or "")
    output = str(row.get("output", "") or "").strip()
    citations = row.get("citations") if isinstance(row.get("citations"), list) else []
    teacher_id = str(row.get("teacher_id", "") or "")
    if not teacher_id:
        blockers.append("missing_teacher_id")
    if not task_id:
        blockers.append("missing_task_id")
    if not output:
        blockers.append("missing_output")
    if not citations:
        blockers.append("missing_citations")
    return not blockers, blockers


def build_distillation_dataset_manifest(
    *,
    distillation_plan: dict[str, Any],
    teacher_outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    teacher_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    citation_count = 0
    for row in teacher_outputs:
        eligible, blockers = _teacher_output_status(row)
        normalized = {
            "teacher_id": str(row.get("teacher_id", "") or ""),
            "task_id": str(row.get("task_id", "") or ""),
            "prompt_id": str(row.get("prompt_id", "") or ""),
            "instruction": str(row.get("instruction", "") or ""),
            "input": str(row.get("input", "") or ""),
            "output": str(row.get("output", "") or ""),
            "citations": row.get("citations") if isinstance(row.get("citations"), list) else [],
            "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        }
        if normalized["citations"]:
            citation_count += 1
        if eligible:
            accepted.append(normalized)
            teacher_counts[normalized["teacher_id"]] += 1
            task_counts[normalized["task_id"]] += 1
        else:
            rejected.append({"row": normalized, "reasons": blockers})
    total = len(teacher_outputs)
    thresholds = (
        distillation_plan.get("acceptance_thresholds")
        if isinstance(distillation_plan.get("acceptance_thresholds"), dict)
        else {}
    )
    citation_rate = citation_count / total if total else 0.0
    rejection_rate = len(rejected) / total if total else 0.0
    validation = {
        "ok": (
            bool(distillation_plan.get("validation", {}).get("ok"))
            and citation_rate >= float(thresholds.get("min_citation_rate", 0.0) or 0.0)
            and rejection_rate <= float(thresholds.get("max_rejection_rate", 1.0) or 1.0)
        ),
        "citation_rate": round(citation_rate, 6),
        "rejection_rate": round(rejection_rate, 6),
        "plan_ok": bool(distillation_plan.get("validation", {}).get("ok")),
    }
    body = {
        "schema": "distillation_dataset_manifest.v1",
        "created_at": _now(),
        "distillation_id": distillation_plan.get("distillation_id", ""),
        "counts": {
            "raw_teacher_outputs": total,
            "accepted_examples": len(accepted),
            "rejected_examples": len(rejected),
        },
        "teacher_mix_observed": dict(sorted(teacher_counts.items())),
        "task_mix_observed": dict(sorted(task_counts.items())),
        "accepted_examples": accepted,
        "rejected_examples": rejected,
        "validation": validation,
        "next_step": "convert_accepted_examples_to_training_prepare_input",
    }
    body["dataset_id"] = _stable_id("distillset", {k: v for k, v in body.items() if k != "created_at"})
    return body
