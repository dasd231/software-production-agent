"""Quality review for teacher-generated distillation outputs."""

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


def _normalise_citations(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        if not path:
            continue
        row = {"path": path}
        for key in ("line", "start_line", "end_line"):
            value = item.get(key)
            if isinstance(value, bool):
                continue
            if isinstance(value, int) and value > 0:
                row[key] = value
        rows.append(row)
    return rows


def review_teacher_outputs(
    *,
    distillation_plan: dict[str, Any],
    prompt_batch: dict[str, Any],
    teacher_outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Judge raw teacher outputs against the originating prompt evidence."""

    prompts = {
        str(row.get("prompt_id", "") or ""): row
        for row in (prompt_batch.get("prompts") if isinstance(prompt_batch.get("prompts"), list) else [])
        if str(row.get("prompt_id", "") or "")
    }
    accepted_outputs: list[dict[str, Any]] = []
    rejected_outputs: list[dict[str, Any]] = []
    teacher_counts: Counter[str] = Counter()
    task_counts: Counter[str] = Counter()
    citation_present = 0
    citation_grounded = 0
    for raw in teacher_outputs:
        prompt_id = str(raw.get("prompt_id", "") or "")
        prompt = prompts.get(prompt_id, {})
        output = str(raw.get("output", "") or "").strip()
        citations = _normalise_citations(raw.get("citations"))
        evidence = _normalise_citations(prompt.get("evidence_bundle"))
        evidence_paths = {str(row.get("path", "") or "") for row in evidence}
        citation_paths = {str(row.get("path", "") or "") for row in citations}
        unsupported_paths = sorted(path for path in citation_paths if path not in evidence_paths)
        teacher_id = str(raw.get("teacher_id", "") or "")
        task_id = str(raw.get("task_id", "") or raw.get("teacher_task_id", "") or "")
        blockers: list[str] = []
        if not prompt:
            blockers.append("unknown_prompt_id")
        if not teacher_id:
            blockers.append("missing_teacher_id")
        elif prompt and teacher_id != str(prompt.get("teacher_id", "") or ""):
            blockers.append("teacher_prompt_mismatch")
        if not task_id:
            blockers.append("missing_task_id")
        elif prompt and task_id != str(prompt.get("teacher_task_id", "") or ""):
            blockers.append("task_prompt_mismatch")
        if not output:
            blockers.append("missing_output")
        if not citations:
            blockers.append("missing_citations")
        if unsupported_paths:
            blockers.append("citations_not_in_prompt_evidence")
        normalized = {
            "teacher_id": teacher_id,
            "task_id": task_id,
            "prompt_id": prompt_id,
            "instruction": str(raw.get("instruction", "") or prompt.get("instruction", "") or ""),
            "input": str(raw.get("input", "") or prompt.get("input", "") or ""),
            "output": output,
            "citations": citations,
            "metadata": {
                **(raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}),
                "student_task_type": str(prompt.get("student_task_type", "") or ""),
                "source_example_id": str(prompt.get("source_example_id", "") or ""),
            },
        }
        review = {
            "eligible": not blockers,
            "reasons": ["passed_teacher_output_review"] if not blockers else blockers,
            "unsupported_citation_paths": unsupported_paths,
            "evidence_paths_available": sorted(evidence_paths),
        }
        if citations:
            citation_present += 1
        if citations and not unsupported_paths:
            citation_grounded += 1
        if blockers:
            rejected_outputs.append({"output": normalized, "review": review})
        else:
            accepted_outputs.append({**normalized, "review": review})
            teacher_counts[teacher_id] += 1
            task_counts[task_id] += 1
    total = len(teacher_outputs)
    thresholds = (
        distillation_plan.get("acceptance_thresholds")
        if isinstance(distillation_plan.get("acceptance_thresholds"), dict)
        else {}
    )
    citation_rate = citation_present / total if total else 0.0
    grounded_rate = citation_grounded / total if total else 0.0
    rejection_rate = len(rejected_outputs) / total if total else 0.0
    validation = {
        "ok": (
            bool(distillation_plan.get("validation", {}).get("ok"))
            and bool(prompt_batch.get("validation", {}).get("ok"))
            and citation_rate >= float(thresholds.get("min_citation_rate", 0.0) or 0.0)
            and grounded_rate >= float(thresholds.get("min_grounded_rate", 0.0) or 0.0)
            and rejection_rate <= float(thresholds.get("max_rejection_rate", 1.0) or 1.0)
        ),
        "citation_rate": round(citation_rate, 6),
        "grounded_rate": round(grounded_rate, 6),
        "rejection_rate": round(rejection_rate, 6),
        "plan_ok": bool(distillation_plan.get("validation", {}).get("ok")),
        "prompt_batch_ok": bool(prompt_batch.get("validation", {}).get("ok")),
    }
    body = {
        "schema": "teacher_output_review.v1",
        "created_at": _now(),
        "distillation_id": str(distillation_plan.get("distillation_id", "") or ""),
        "prompt_batch_id": str(prompt_batch.get("batch_id", "") or ""),
        "counts": {
            "teacher_outputs": total,
            "accepted_outputs": len(accepted_outputs),
            "rejected_outputs": len(rejected_outputs),
        },
        "teacher_mix_observed": dict(sorted(teacher_counts.items())),
        "task_mix_observed": dict(sorted(task_counts.items())),
        "accepted_outputs": accepted_outputs,
        "rejected_outputs": rejected_outputs,
        "validation": validation,
    }
    body["review_id"] = _stable_id("teacherreview", {k: v for k, v in body.items() if k != "created_at"})
    return body
