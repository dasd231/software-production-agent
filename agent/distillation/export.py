"""Export accepted teacher outputs into training-prepare-compatible assets."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.distillation.prompts import TEACHER_TASK_TO_STUDENT_TASK


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=12)
    for part in parts:
        h.update(str(part).encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def export_distillation_training_examples(
    *,
    output_dir: Path,
    distillation_plan: dict[str, Any],
    teacher_output_review: dict[str, Any],
) -> dict[str, Any]:
    """Write accepted teacher supervision as a lightweight learning directory."""

    root = output_dir.resolve()
    accepted = (
        teacher_output_review.get("accepted_outputs")
        if isinstance(teacher_output_review.get("accepted_outputs"), list)
        else []
    )
    examples: list[dict[str, Any]] = []
    task_counts: Counter[str] = Counter()
    for row in accepted:
        if not isinstance(row, dict):
            continue
        task_id = str(row.get("task_id", "") or "")
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        task_type = str(metadata.get("student_task_type", "") or "") or TEACHER_TASK_TO_STUDENT_TASK.get(task_id, "sft")
        example = {
            "example_id": _stable_id(
                "distillation",
                str(distillation_plan.get("distillation_id", "") or ""),
                str(row.get("prompt_id", "") or ""),
                str(row.get("teacher_id", "") or ""),
            ),
            "task_type": task_type,
            "instruction": str(row.get("instruction", "") or ""),
            "input": str(row.get("input", "") or ""),
            "output": str(row.get("output", "") or ""),
            "citations": row.get("citations") if isinstance(row.get("citations"), list) else [],
            "metadata": {
                "source": "distillation_v1",
                "distillation_id": str(distillation_plan.get("distillation_id", "") or ""),
                "teacher_id": str(row.get("teacher_id", "") or ""),
                "teacher_task_id": task_id,
                "prompt_id": str(row.get("prompt_id", "") or ""),
                "source_example_id": str(metadata.get("source_example_id", "") or ""),
            },
        }
        examples.append(example)
        task_counts[task_type] += 1
    training_examples_path = root / "training_examples.jsonl"
    manifest_path = root / "distillation_export_manifest.json"
    report_path = root / "report.md"
    _write_jsonl(training_examples_path, examples)
    manifest = {
        "schema": "distillation_export_manifest.v1",
        "created_at": _now(),
        "distillation_id": str(distillation_plan.get("distillation_id", "") or ""),
        "review_id": str(teacher_output_review.get("review_id", "") or ""),
        "counts": {
            "training_examples": len(examples),
            **dict(sorted(task_counts.items())),
        },
        "files": {
            "training_examples": str(training_examples_path),
        },
        "compatible_with_training_prepare": True,
        "recommended_next_step": "pass this directory through training_prepare as a learning_dir",
    }
    _write_json(manifest_path, manifest)
    report_path.write_text(
        "\n".join(
            [
                "# Distillation Export",
                "",
                f"- Distillation id: `{manifest['distillation_id']}`",
                f"- Review id: `{manifest['review_id']}`",
                f"- Training examples: `{len(examples)}`",
                "",
                "## Task Mix",
                "",
                *[f"- `{task}`: `{count}`" for task, count in sorted(task_counts.items())],
                "",
                "## Next Step",
                "",
                "- 将当前目录作为 `learning_dir` 传入 `training_prepare`，再进入既有样本审查和训练集切分链路。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = {
        "training_examples": str(training_examples_path),
        "manifest": str(manifest_path),
        "report": str(report_path),
    }
    return {
        "schema": "distillation_export_result.v1",
        "output_dir": str(root),
        "files": files,
        "counts": manifest["counts"],
        "manifest": manifest,
    }
