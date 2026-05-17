"""Training-job specifications decoupled from any concrete runner."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.training.execution_profiles import default_execution_profile
from agent.training.sync_contracts import build_artifact_sync_contract


def _stable_digest(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()


def build_training_job_spec(
    *,
    base_model: str,
    adapter_name: str,
    dataset_snapshot: dict[str, Any],
    backend: str,
    hyperparameters: dict[str, Any],
    evaluation_benchmark: str = "",
    objective: str = "sft",
    resources: dict[str, Any] | None = None,
    execution_profile: dict[str, Any] | None = None,
    sync_contract: dict[str, Any] | None = None,
    resume_policy: dict[str, Any] | None = None,
    retry_policy: dict[str, Any] | None = None,
    output_dir: Path,
) -> dict[str, Any]:
    merged_resources = dict(
        {
            "gpu_count": 1,
            "strategy": "single_node",
            "precision": "fp16",
        },
        **(resources or {}),
    )
    dataset_ref = {
        "dataset_id": dataset_snapshot.get("dataset_id"),
        "manifest_path": str(Path(str(dataset_snapshot.get("training_dir", ""))) / "dataset_snapshot_manifest.json"),
        "train_file": ((dataset_snapshot.get("files") or {}).get("train") or {}).get("path", ""),
        "eval_file": ((dataset_snapshot.get("files") or {}).get("eval") or {}).get("path", ""),
        "shards": ((dataset_snapshot.get("sharding") or {}).get("shards") or []),
    }
    body = {
        "schema": "training_job_spec.v1",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "objective": objective,
        "base_model": base_model,
        "adapter_name": adapter_name,
        "dataset_snapshot": dataset_ref,
        "backend": backend,
        "resources": merged_resources,
        "execution_profile": execution_profile
        or default_execution_profile(
            backend,
            gpu_count=int(merged_resources["gpu_count"]),
            strategy=str(merged_resources["strategy"]),
            precision=str(merged_resources["precision"]),
        ),
        "hyperparameters": dict(hyperparameters),
        "evaluation": {
            "benchmark": evaluation_benchmark,
            "required_before_promotion": True,
        },
        "artifact_contract": {
            "adapter_dir": str(output_dir / "adapter"),
            "training_result": str(output_dir / "adapter" / "training_result.json"),
            "logs_dir": str(output_dir / "logs"),
            "checkpoints_dir": str(output_dir / "adapter"),
        },
        "sync_contract": sync_contract or build_artifact_sync_contract(dataset_snapshot=dataset_snapshot, output_dir=output_dir),
        "resume_policy": dict(
            {
                "enabled": True,
                "checkpoint_selector": "latest",
                "max_resume_attempts": 2,
            },
            **(resume_policy or {}),
        ),
        "retry_policy": dict(
            {
                "max_attempts": 2,
                "retryable_failures": ["transient_io", "preempted", "node_lost"],
                "backoff_seconds": 60,
            },
            **(retry_policy or {}),
        ),
    }
    body["job_spec_id"] = f"jobspec-{_stable_digest({k: v for k, v in body.items() if k != 'created_at'})}"
    return body
