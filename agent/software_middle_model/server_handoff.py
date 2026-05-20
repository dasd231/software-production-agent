"""Server handoff pack for the first software middle-model training round."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.chains.model_training import BackupModelTrainInput, prepare_backup_model_training
from agent.training.resource_guard import build_training_resource_policy


@dataclass(frozen=True)
class MiddleModelServerHandoffInput:
    training_dir: Path
    output_dir: Path
    base_model: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"
    adapter_name: str = "software-middle-model-lora"
    min_train_examples: int = 1
    max_seq_length: int = 1024
    learning_rate: float = 2e-4
    epochs: float = 1.0
    cpu_threads: int = 4
    max_gpu_memory_gb: float = 12.0


@dataclass(frozen=True)
class MiddleModelServerHandoffResult:
    output_dir: str
    handoff_ready: bool
    files: dict[str, str] = field(default_factory=dict)
    training_job: dict[str, Any] = field(default_factory=dict)
    resource_policy: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "handoff_ready": self.handoff_ready,
            "files": self.files,
            "training_job": self.training_job,
            "resource_policy": self.resource_policy,
            "validation": self.validation,
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def prepare_middle_model_server_handoff(inp: MiddleModelServerHandoffInput) -> MiddleModelServerHandoffResult:
    training_dir = inp.training_dir.resolve()
    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    training_job = prepare_backup_model_training(
        BackupModelTrainInput(
            training_dir=training_dir,
            output_dir=output_dir,
            base_model=inp.base_model,
            adapter_name=inp.adapter_name,
            launch=False,
            min_quality_score=6.5,
            min_train_examples=max(int(inp.min_train_examples), 1),
            max_seq_length=max(int(inp.max_seq_length), 128),
            learning_rate=float(inp.learning_rate),
            epochs=float(inp.epochs),
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            lora_r=16,
            lora_alpha=32,
            lora_dropout=0.05,
        )
    ).to_dict()
    policy = build_training_resource_policy(cpu_threads=inp.cpu_threads, max_gpu_memory_gb=inp.max_gpu_memory_gb)
    policy_path = output_dir / "training_resource_policy.json"
    preflight_action_path = output_dir / "server_preflight_action.json"
    handoff_path = output_dir / "SERVER_HANDOFF.md"
    _write_json(policy_path, policy)
    preflight_action = {"type": "action", "action": "training_server_preflight", "args": {"policy": policy}}
    _write_json(preflight_action_path, preflight_action)

    files = dict(training_job.get("files") or {})
    spec_path = Path(str(files.get("spec", output_dir / "backup_training_spec.json"))).resolve()
    launch_command = _safe_read(Path(str(files.get("launch_command", output_dir / "launch_command.txt"))))
    blockers = list((training_job.get("data_gate") or {}).get("blockers", [])) if isinstance(training_job.get("data_gate"), dict) else []
    data_gate_passed = bool((training_job.get("data_gate") or {}).get("passed")) if isinstance(training_job.get("data_gate"), dict) else False
    handoff_ready = bool(data_gate_passed and spec_path.exists())
    status = str(training_job.get("status", "") or "")
    validation = {
        "ok": handoff_ready,
        "data_gate_passed": data_gate_passed,
        "local_preparation_status": status,
        "blockers": blockers,
        "warnings": [
            "local_environment_may_be_blocked_without_cuda; server preflight must pass before launch",
            "operator must run the launch command manually on the shared GPU server",
        ],
    }
    handoff_path.write_text(
        "\n".join(
            [
                "# Software Middle Model Server Handoff",
                "",
                f"Created at: `{_now()}`",
                f"Training dir: `{training_dir}`",
                f"Output dir: `{output_dir}`",
                f"Base model: `{inp.base_model}`",
                f"Adapter: `{inp.adapter_name}`",
                f"Handoff ready: `{handoff_ready}`",
                f"Local preparation status: `{status}`",
                "",
                "## Before launch on the shared server",
                "",
                "1. Confirm this package is on the server under `/data/ThreadModel` or another agreed work dir.",
                "2. Run `nvidia-smi` and make sure nobody else is using the GPU.",
                "3. Run the resource preflight action or equivalent server check.",
                "4. Run a dry-run trainer command before real training.",
                "",
                "## Preflight action",
                "",
                "```json",
                json.dumps(preflight_action, ensure_ascii=False, indent=2),
                "```",
                "",
                "## Dry run",
                "",
                "```bash",
                f"python -m agent.training.backup_trainer --config {spec_path} --dry-run",
                "```",
                "",
                "## Launch command",
                "",
                "```bash",
                launch_command or f"python -m agent.training.backup_trainer --config {spec_path}",
                "```",
                "",
                "## Stop rules",
                "",
                "- Do not launch if `training_server_preflight` is not admitted.",
                "- Do not launch if another compute process is visible in `nvidia-smi`.",
                "- Keep this first run small; it is a smoke training round for the middle model, not a final claim.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files.update(
        {
            "training_resource_policy": str(policy_path),
            "server_preflight_action": str(preflight_action_path),
            "server_handoff": str(handoff_path),
        }
    )
    summary = {
        "schema": "software_middle_model_server_handoff.v1",
        "created_at": _now(),
        "handoff_ready": handoff_ready,
        "training_dir": str(training_dir),
        "output_dir": str(output_dir),
        "training_job_status": status,
        "files": files,
        "validation": validation,
    }
    summary_path = output_dir / "software_middle_model_server_handoff.json"
    _write_json(summary_path, summary)
    files["handoff_manifest"] = str(summary_path)
    return MiddleModelServerHandoffResult(
        output_dir=str(output_dir),
        handoff_ready=handoff_ready,
        files=files,
        training_job=training_job,
        resource_policy=policy,
        validation=validation,
    )
