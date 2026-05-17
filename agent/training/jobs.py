"""Training-job lifecycle manifests for local and remote execution."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


JOB_STATUSES = (
    "created",
    "validated",
    "queued",
    "dispatched",
    "running",
    "completed",
    "failed",
    "evaluated",
    "promoted",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_training_job_manifest(
    *,
    job_id: str,
    spec_path: Path,
    dataset_snapshot_id: str,
    backend: str,
    execution_target: str,
) -> dict[str, Any]:
    created_at = _now()
    return {
        "schema": "training_job_manifest.v1",
        "job_id": job_id,
        "created_at": created_at,
        "current_status": "created",
        "spec_path": str(spec_path),
        "dataset_snapshot_id": dataset_snapshot_id,
        "backend": backend,
        "execution_target": execution_target,
        "attempts": 0,
        "retry_count": 0,
        "remote_job_id": "",
        "execution_host": "",
        "resume_from_checkpoint": "",
        "last_heartbeat_at": "",
        "failure_classification": "",
        "last_error": "",
        "artifacts": [],
        "status_history": [{"status": "created", "at": created_at, "detail": "job_manifest_created"}],
    }


def transition_training_job(
    manifest: dict[str, Any],
    status: str,
    *,
    detail: str = "",
    execution_target: str | None = None,
    error: str = "",
    artifacts: list[str] | None = None,
) -> dict[str, Any]:
    if status not in JOB_STATUSES:
        raise ValueError(f"unknown training job status: {status}")
    out = dict(manifest)
    out["current_status"] = status
    if execution_target is not None:
        out["execution_target"] = execution_target
    if status in {"dispatched", "running"}:
        out["attempts"] = int(out.get("attempts", 0) or 0) + (1 if status == "dispatched" else 0)
    if error:
        out["last_error"] = error
    artifact_rows = list(out.get("artifacts", [])) if isinstance(out.get("artifacts"), list) else []
    for artifact in artifacts or []:
        if artifact not in artifact_rows:
            artifact_rows.append(artifact)
    out["artifacts"] = artifact_rows
    history = list(out.get("status_history", [])) if isinstance(out.get("status_history"), list) else []
    history.append({"status": status, "at": _now(), "detail": detail})
    out["status_history"] = history
    return out


def update_training_job_runtime(
    manifest: dict[str, Any],
    *,
    remote_job_id: str | None = None,
    execution_host: str | None = None,
    resume_from_checkpoint: str | None = None,
    heartbeat: bool = False,
    failure_classification: str | None = None,
    retry_count: int | None = None,
) -> dict[str, Any]:
    """Patch runtime-only fields without forcing a lifecycle transition."""

    out = dict(manifest)
    if remote_job_id is not None:
        out["remote_job_id"] = remote_job_id
    if execution_host is not None:
        out["execution_host"] = execution_host
    if resume_from_checkpoint is not None:
        out["resume_from_checkpoint"] = resume_from_checkpoint
    if failure_classification is not None:
        out["failure_classification"] = failure_classification
    if retry_count is not None:
        out["retry_count"] = max(int(retry_count), 0)
    if heartbeat:
        out["last_heartbeat_at"] = _now()
    return out


def write_training_job_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_training_job_manifest(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("training job manifest must be a JSON object")
    return raw
