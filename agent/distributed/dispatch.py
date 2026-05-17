"""Preview-only distributed dispatch planning."""

from __future__ import annotations

from typing import Any

from agent.distributed.backends import RayClusterBackend
from agent.distributed.manifests import build_distributed_job_manifest
from agent.distributed.workloads import get_distributed_workload


def build_distributed_job_plan(
    *,
    job_id: str,
    workload: str,
    entrypoint: str = "",
    backend: str = "ray_cluster",
    source_manifest_id: str = "",
    queue: str = "default",
    resources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    workload_spec = get_distributed_workload(workload)
    if not workload_spec:
        raise ValueError(f"unknown distributed workload: {workload}")
    if backend != "ray_cluster":
        raise ValueError(f"unsupported distributed backend: {backend}")

    resolved_entrypoint = entrypoint or str(workload_spec.get("source_action", ""))
    manifest = build_distributed_job_manifest(
        job_id=job_id,
        backend=backend,
        workload=workload,
        source_manifest_id=source_manifest_id,
        queue=queue,
        resources=resources,
    )
    submission = RayClusterBackend().build_submission_plan(
        job_id=job_id,
        workload=workload,
        entrypoint=resolved_entrypoint,
        queue=queue,
        resources=resources,
    )
    return {
        "schema": "distributed_job_plan.v1",
        "dispatch_mode": "preview_only",
        "workload": workload_spec,
        "manifest": manifest,
        "submission": submission,
    }
