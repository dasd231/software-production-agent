"""Portable manifests for future distributed execution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.distributed.workloads import get_distributed_workload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_distributed_job_manifest(
    *,
    job_id: str,
    backend: str,
    workload: str,
    source_manifest_id: str = "",
    queue: str = "default",
    resources: dict[str, Any] | None = None,
    inputs: list[dict[str, Any]] | None = None,
    outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a contract-first distributed job manifest without dispatching it."""

    created_at = _now()
    workload_spec = get_distributed_workload(workload) or {}
    default_resources = workload_spec.get("resources") if isinstance(workload_spec.get("resources"), dict) else {}
    retry_policy = workload_spec.get("retry_policy") if isinstance(workload_spec.get("retry_policy"), dict) else {}
    return {
        "schema": "distributed_job_manifest.v1",
        "job_id": job_id,
        "created_at": created_at,
        "backend": backend,
        "workload": workload,
        "queue": queue if queue != "default" or not workload_spec else str(workload_spec.get("queue", "default")),
        "source_manifest_id": source_manifest_id,
        "resources": {
            "cpu": 1,
            "gpu": 0,
            "memory_gb": 2,
            **default_resources,
            **(resources or {}),
        },
        "retry_policy": retry_policy,
        "workload_spec": workload_spec,
        "inputs": list(inputs or []),
        "outputs": list(outputs or []),
        "current_status": "planned",
        "status_history": [{"status": "planned", "at": created_at, "detail": "manifest_created"}],
        "runtime": {
            "remote_job_id": "",
            "execution_host": "",
            "last_heartbeat_at": "",
            "retry_count": 0,
            "failure_classification": "",
        },
    }
