"""Backup local-model training job preparation and preflight."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.runtime.manifest import build_run_manifest, write_run_manifest
from agent.training.datasets import create_dataset_snapshot
from agent.training.jobs import create_training_job_manifest, transition_training_job, write_training_job_manifest
from agent.training.runners.local_trl import LocalTRLRunner
from agent.training.specs import build_training_job_spec


@dataclass(frozen=True)
class BackupModelTrainInput:
    training_dir: Path
    output_dir: Path
    base_model: str = ""
    adapter_name: str = "backup-local-lora"
    trainer_backend: str = "trl_sft"
    launch: bool = False
    min_quality_score: float = 6.5
    min_train_examples: int = 20
    max_seq_length: int = 2048
    learning_rate: float = 2e-4
    epochs: float = 1.0
    per_device_train_batch_size: int = 1
    gradient_accumulation_steps: int = 8
    lora_r: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    target_modules: str = "all-linear"
    evaluation_benchmark: str = "./benchmarks/backup_model_eval.v3.json"


@dataclass(frozen=True)
class BackupModelTrainResult:
    output_dir: str
    status: str
    launchable: bool
    files: dict[str, str] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    data_gate: dict[str, Any] = field(default_factory=dict)
    spec: dict[str, Any] = field(default_factory=dict)
    model_version: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "status": self.status,
            "launchable": self.launchable,
            "files": self.files,
            "environment": self.environment,
            "data_gate": self.data_gate,
            "spec": self.spec,
            "model_version": self.model_version,
            "manifest": self.manifest,
        }


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip())


def detect_training_environment() -> dict[str, Any]:
    packages = {name: importlib.util.find_spec(name) is not None for name in ("torch", "transformers", "datasets", "peft", "trl")}
    cuda_available = False
    cuda_device_count = 0
    torch_version = ""
    if packages["torch"]:
        try:
            import torch

            torch_version = str(getattr(torch, "__version__", ""))
            cuda_available = bool(torch.cuda.is_available())
            cuda_device_count = int(torch.cuda.device_count())
        except Exception:
            cuda_available = False
            cuda_device_count = 0
    missing = [name for name, ok in packages.items() if not ok]
    ready = not missing and cuda_available
    return {
        "schema": "backup_training_environment.v1",
        "packages": packages,
        "missing_packages": missing,
        "torch_version": torch_version,
        "cuda_available": cuda_available,
        "cuda_device_count": cuda_device_count,
        "ready": ready,
    }


def _stable_model_version(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=10).hexdigest()
    return f"backup-{digest}"


def _data_gate(inp: BackupModelTrainInput) -> dict[str, Any]:
    train_path = inp.training_dir / "train.jsonl"
    eval_path = inp.training_dir / "eval.jsonl"
    sample_quality = _safe_json(inp.training_dir / "sample_quality_report.json")
    governance = _safe_json(inp.training_dir / "governance_report.json")
    training_plan = _safe_json(inp.training_dir / "training_plan.json")
    train_examples = _count_jsonl(train_path)
    eval_examples = _count_jsonl(eval_path)
    sample_score = float(sample_quality.get("overall_score", 0.0) or 0.0)
    secret_scan = ((governance.get("metrics") or {}).get("secret_scan") or {}) if isinstance(governance.get("metrics"), dict) else {}
    blockers: list[str] = []
    if train_examples < max(int(inp.min_train_examples), 1):
        blockers.append("insufficient_train_examples")
    if sample_score < float(inp.min_quality_score):
        blockers.append("sample_quality_below_threshold")
    if str(secret_scan.get("status", "")) == "blocked":
        blockers.append("dataset_governance_blocked")
    if not train_path.exists():
        blockers.append("missing_train_jsonl")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "train_examples": train_examples,
        "eval_examples": eval_examples,
        "sample_quality_score": sample_score,
        "sample_quality_grade": sample_quality.get("grade"),
        "governance_grade": governance.get("grade"),
        "training_plan": training_plan,
    }


def _build_spec(
    inp: BackupModelTrainInput,
    data_gate: dict[str, Any],
    *,
    training_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    training_plan = data_gate.get("training_plan") if isinstance(data_gate.get("training_plan"), dict) else {}
    base_model = inp.base_model.strip() or str(training_plan.get("base_model", "") or "")
    return {
        "schema": "backup_model_training_spec.v1",
        "role": "backup_local_model",
        "base_model": base_model,
        "adapter_name": inp.adapter_name,
        "trainer_backend": inp.trainer_backend,
        "dataset": {
            "train_file": str(training_dir / "train.jsonl"),
            "eval_file": str(training_dir / "eval.jsonl"),
            "format": str(training_plan.get("dataset_format", "messages") or "messages"),
        },
        "hyperparameters": {
            "method": "LoRA/QLoRA SFT",
            "max_seq_length": int(inp.max_seq_length),
            "learning_rate": float(inp.learning_rate),
            "epochs": float(inp.epochs),
            "per_device_train_batch_size": int(inp.per_device_train_batch_size),
            "gradient_accumulation_steps": int(inp.gradient_accumulation_steps),
            "lora_r": int(inp.lora_r),
            "lora_alpha": int(inp.lora_alpha),
            "lora_dropout": float(inp.lora_dropout),
            "target_modules": inp.target_modules,
        },
        "output_dir": str(output_dir / "adapter"),
    }


def _load_or_create_dataset_snapshot(training_dir: Path) -> dict[str, Any]:
    path = training_dir / "dataset_snapshot_manifest.json"
    if path.exists():
        return _safe_json(path)
    return create_dataset_snapshot(training_dir, shard_size=1024, write_shards=True)


def prepare_backup_model_training(inp: BackupModelTrainInput) -> BackupModelTrainResult:
    training_dir = inp.training_dir.resolve()
    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    environment = detect_training_environment()
    data_gate = _data_gate(inp)
    spec = _build_spec(inp, data_gate, training_dir=training_dir, output_dir=output_dir)
    dataset_snapshot = _load_or_create_dataset_snapshot(training_dir)
    runner = LocalTRLRunner()
    training_job_spec = build_training_job_spec(
        base_model=spec["base_model"],
        adapter_name=inp.adapter_name,
        dataset_snapshot=dataset_snapshot,
        backend=runner.name,
        hyperparameters=spec["hyperparameters"],
        evaluation_benchmark=inp.evaluation_benchmark,
        output_dir=output_dir,
    )
    model_version = {
        "schema": "model_version_manifest.v1",
        "role": "backup_local_model",
        "model_version": "",
        "base_model": spec["base_model"],
        "adapter_name": inp.adapter_name,
        "training_dir": str(training_dir),
        "dataset_snapshot_id": dataset_snapshot.get("dataset_id"),
        "training_job_spec_id": training_job_spec.get("job_spec_id"),
        "quality_gate": {
            "sample_quality_score": data_gate["sample_quality_score"],
            "sample_quality_grade": data_gate["sample_quality_grade"],
            "governance_grade": data_gate["governance_grade"],
        },
        "rollout_stage": "candidate",
    }
    model_version["model_version"] = _stable_model_version(model_version)

    launchable = bool(data_gate["passed"] and environment["ready"] and spec["base_model"])
    if not data_gate["passed"]:
        status = "blocked_data_quality"
    elif not environment["ready"]:
        status = "blocked_environment"
    elif not spec["base_model"]:
        status = "blocked_missing_base_model"
    elif inp.launch:
        status = "launch_ready"
    else:
        status = "prepared_not_started"

    spec_path = output_dir / "backup_training_spec.json"
    training_job_spec_path = output_dir / "training_job_spec.json"
    training_job_manifest_path = output_dir / "training_job_manifest.json"
    env_path = output_dir / "training_environment.json"
    gate_path = output_dir / "data_gate.json"
    version_path = output_dir / "model_version_manifest.json"
    launch_path = output_dir / "launch_command.txt"
    report_path = output_dir / "report.md"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    training_job_spec_path.write_text(json.dumps(training_job_spec, ensure_ascii=False, indent=2), encoding="utf-8")
    env_path.write_text(json.dumps(environment, ensure_ascii=False, indent=2), encoding="utf-8")
    gate_path.write_text(json.dumps(data_gate, ensure_ascii=False, indent=2), encoding="utf-8")
    version_path.write_text(json.dumps(model_version, ensure_ascii=False, indent=2), encoding="utf-8")
    launch_path.write_text(runner.build_launch_command(spec_path), encoding="utf-8")
    training_job = create_training_job_manifest(
        job_id=training_job_spec["job_spec_id"],
        spec_path=training_job_spec_path,
        dataset_snapshot_id=str(dataset_snapshot.get("dataset_id", "")),
        backend=runner.name,
        execution_target="local",
    )
    training_job = transition_training_job(
        training_job,
        "validated" if data_gate["passed"] else "failed",
        detail="data_gate_passed" if data_gate["passed"] else ",".join(data_gate["blockers"]) or "data_gate_failed",
        error="" if data_gate["passed"] else ",".join(data_gate["blockers"]),
    )
    if data_gate["passed"]:
        training_job = transition_training_job(
            training_job,
            "queued" if not inp.launch else "dispatched",
            detail="ready_for_operator_dispatch" if not inp.launch else "operator_requested_launch",
        )
    write_training_job_manifest(training_job_manifest_path, training_job)
    report_path.write_text(
        "\n".join(
            [
                "# Backup Local Model Training",
                "",
                f"Status: `{status}`",
                f"Launchable: `{launchable}`",
                f"Base model: `{spec['base_model'] or 'missing'}`",
                f"Train examples: `{data_gate['train_examples']}`",
                f"Sample quality: `{data_gate['sample_quality_score']}`",
                f"Environment ready: `{environment['ready']}`",
                f"Dataset snapshot: `{dataset_snapshot.get('dataset_id', '')}`",
                f"Training job: `{training_job_spec.get('job_spec_id', '')}`",
                f"Runner: `{runner.name}`",
                "",
                "## Blockers",
                "",
                *[f"- {item}" for item in data_gate["blockers"]],
                *[f"- missing_package:{item}" for item in environment["missing_packages"]],
                *([] if environment["cuda_available"] else ["- cuda_unavailable"]),
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = {
        "spec": str(spec_path),
        "training_job_spec": str(training_job_spec_path),
        "training_job_manifest": str(training_job_manifest_path),
        "environment": str(env_path),
        "data_gate": str(gate_path),
        "model_version_manifest": str(version_path),
        "launch_command": str(launch_path),
        "report": str(report_path),
    }
    manifest = build_run_manifest(
        kind="backup_model_training",
        input_summary={
            "training_dir": str(training_dir),
            "base_model": spec["base_model"],
            "adapter_name": inp.adapter_name,
            "trainer_backend": inp.trainer_backend,
            "launch_requested": bool(inp.launch),
            "dataset_snapshot_id": dataset_snapshot.get("dataset_id"),
            "training_job_spec_id": training_job_spec.get("job_spec_id"),
            "runner": runner.describe(),
        },
        files=files,
        artifacts=[str(version_path), str(spec_path), str(training_job_spec_path), str(training_job_manifest_path)],
        source_refs=[
            {"type": "training_dir", "path": str(training_dir)},
            {"type": "dataset_snapshot", "path": str(training_dir / "dataset_snapshot_manifest.json")},
        ],
        risks=["training_environment_must_be_verified", "manual_model_eval_required_before_rollout"],
    )
    manifest_path = write_run_manifest(output_dir, manifest)
    files["run_manifest"] = str(manifest_path)
    return BackupModelTrainResult(
        output_dir=str(output_dir),
        status=status,
        launchable=launchable,
        files=files,
        environment=environment,
        data_gate=data_gate,
        spec={**spec, "training_job_spec": training_job_spec, "dataset_snapshot": dataset_snapshot},
        model_version=model_version,
        manifest=manifest,
    )
