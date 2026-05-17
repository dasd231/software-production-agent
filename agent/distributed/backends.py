"""Contract-first distributed execution backends.

The project intentionally keeps this layer lightweight. Ray is represented as
an execution contract first; the repository does not need to import or start a
Ray cluster merely to describe how future distributed work will be submitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.distributed.workloads import get_distributed_workload


@dataclass(frozen=True)
class DistributedBackend:
    name: str
    execution_plane: str
    primary_workloads: tuple[str, ...]
    data_plane_role: str
    dispatch_mode: str
    capabilities: tuple[str, ...]

    def describe(self) -> dict[str, Any]:
        return {
            "schema": "distributed_backend.v1",
            "name": self.name,
            "execution_plane": self.execution_plane,
            "primary_workloads": list(self.primary_workloads),
            "data_plane_role": self.data_plane_role,
            "dispatch_mode": self.dispatch_mode,
            "capabilities": list(self.capabilities),
        }


class RayClusterBackend(DistributedBackend):
    def __init__(self) -> None:
        super().__init__(
            name="ray_cluster",
            execution_plane="distributed_execution",
            primary_workloads=(
                "agent_workflow",
                "learning_run",
                "benchmark_evaluation",
                "training_dispatch",
            ),
            data_plane_role="execution_orchestration_not_system_of_record",
            dispatch_mode="contract_only",
            capabilities=(
                "tasks",
                "actors",
                "resource_labels",
                "retryable_jobs",
                "placement_groups",
                "future_ray_data_train_serve_extension",
            ),
        )

    def build_submission_plan(
        self,
        *,
        job_id: str,
        workload: str,
        entrypoint: str,
        resources: dict[str, Any] | None = None,
        queue: str = "default",
        runtime_env: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workload_spec = get_distributed_workload(workload) or {}
        default_resources = workload_spec.get("resources") if isinstance(workload_spec.get("resources"), dict) else {}
        merged_resources = {
            "cpu": 1,
            "gpu": 0,
            "memory_gb": 2,
            **default_resources,
            **(resources or {}),
        }
        return {
            "schema": "ray_submission_plan.v1",
            "backend": self.name,
            "job_id": job_id,
            "workload": workload,
            "entrypoint": entrypoint,
            "queue": queue if queue != "default" or not workload_spec else str(workload_spec.get("queue", "default")),
            "resources": merged_resources,
            "runtime_env": dict(runtime_env or {}),
            "workload_spec": workload_spec,
            "submission_mode": "contract_only",
            "notes": [
                "This repository records the submission contract but does not start a Ray cluster.",
                "Control-plane manifests remain authoritative; Ray is only the execution substrate.",
            ],
        }


def list_distributed_backends() -> list[dict[str, Any]]:
    return [RayClusterBackend().describe()]
