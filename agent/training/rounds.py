"""Transparent plans for the first supervised training round."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()
    return f"{prefix}-{digest}"


def build_first_training_round_plan(
    *,
    name: str,
    learning_dirs: list[str] | tuple[str, ...],
    solution_dirs: list[str] | tuple[str, ...] = (),
    training_output_dir: str,
    model_output_dir: str,
    base_model: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
    dataset_format: str = "messages",
    eval_ratio: float = 0.15,
    min_chars: int = 20,
    max_examples: int = 2000,
    include_protocol_examples: bool = True,
    protocol_example_limit: int = 0,
    min_train_examples: int = 20,
    notes: str = "",
) -> dict[str, Any]:
    """Describe the shortest auditable path to a first LoRA/SFT round."""

    normalized_learning_dirs = [str(Path(path)) for path in learning_dirs if str(path).strip()]
    normalized_solution_dirs = [str(Path(path)) for path in solution_dirs if str(path).strip()]
    blockers: list[str] = []
    warnings: list[str] = []
    if not normalized_learning_dirs:
        blockers.append("missing_learning_dirs")
    if not str(training_output_dir).strip():
        blockers.append("missing_training_output_dir")
    if not str(model_output_dir).strip():
        blockers.append("missing_model_output_dir")
    if not str(base_model).strip():
        blockers.append("missing_base_model")
    if float(eval_ratio) < 0 or float(eval_ratio) > 0.5:
        blockers.append("eval_ratio_out_of_range")
    if int(min_train_examples) < 1:
        blockers.append("min_train_examples_must_be_positive")
    if not normalized_solution_dirs:
        warnings.append("no_solution_dirs_supplied")
    body = {
        "schema": "first_training_round_plan.v1",
        "created_at": _now(),
        "name": name,
        "intent": "prepare a small, auditable first supervised round before scaling model or corpus size",
        "inputs": {
            "learning_dirs": normalized_learning_dirs,
            "solution_dirs": normalized_solution_dirs,
            "distillation_optional": True,
        },
        "recommended_sequence": [
            "review learning_dirs and any distillation exports",
            "run training_prepare",
            "inspect sample_quality_report and dataset_snapshot_manifest",
            "run backup_model_train with launch=false",
            "move the prepared job to the GPU server and execute the generated launch command",
        ],
        "actions": [
            {
                "type": "action",
                "action": "training_prepare",
                "args": {
                    "output_dir": training_output_dir,
                    "learning_dirs": normalized_learning_dirs,
                    "solution_dirs": normalized_solution_dirs,
                    "dataset_format": dataset_format,
                    "eval_ratio": float(eval_ratio),
                    "min_chars": int(min_chars),
                    "max_examples": int(max_examples),
                    "include_protocol_examples": bool(include_protocol_examples),
                    "protocol_example_limit": int(protocol_example_limit),
                },
            },
            {
                "type": "action",
                "action": "backup_model_train",
                "args": {
                    "training_dir": training_output_dir,
                    "output_dir": model_output_dir,
                    "base_model": base_model,
                    "adapter_name": "first-round-lora",
                    "launch": False,
                    "min_train_examples": int(min_train_examples),
                },
            },
        ],
        "server_handoff": {
            "strategy": "prepare locally, execute explicitly on the GPU server",
            "why": "keeps design transparent while avoiding accidental heavy jobs on a shared machine",
            "resource_policy_profile": "shared_conservative",
            "preflight_action": "training_server_preflight",
            "must_verify_before_launch": [
                "training environment packages are installed",
                "CUDA is visible on the server",
                "dataset quality and governance reports passed",
                "training_server_preflight admits the shared-conservative policy",
                "launch_command.txt points at the intended base model and output directory",
            ],
        },
        "notes": notes,
        "validation": {
            "ok": not blockers,
            "blockers": blockers,
            "warnings": warnings,
        },
    }
    body["round_id"] = _stable_id("round", {k: v for k, v in body.items() if k != "created_at"})
    return body
