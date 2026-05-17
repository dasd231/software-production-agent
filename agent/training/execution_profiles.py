"""Execution profiles keep training design separate from compute placement."""

from __future__ import annotations

from typing import Any


def build_execution_profile(
    *,
    profile_id: str,
    execution_plane: str,
    runner: str,
    gpu_count: int = 1,
    strategy: str = "single_node",
    precision: str = "fp16",
    host_selector: str = "",
    scheduler: str = "operator",
    workspace_root: str = "",
    environment_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Build a portable execution profile consumed by runners, not research logic."""

    return {
        "schema": "training_execution_profile.v1",
        "profile_id": profile_id,
        "execution_plane": execution_plane,
        "runner": runner,
        "host_selector": host_selector,
        "scheduler": scheduler,
        "workspace_root": workspace_root,
        "resources": {
            "gpu_count": max(int(gpu_count), 0),
            "strategy": strategy,
            "precision": precision,
        },
        "environment_tags": list(environment_tags or []),
    }


def default_execution_profile(
    backend: str,
    *,
    gpu_count: int = 1,
    strategy: str = "single_node",
    precision: str = "fp16",
) -> dict[str, Any]:
    """Return a conservative default profile for the requested backend."""

    if backend == "linux_remote":
        return build_execution_profile(
            profile_id="linux_remote_default",
            execution_plane="remote_linux",
            runner=backend,
            gpu_count=gpu_count,
            strategy=strategy,
            precision=precision,
            host_selector="operator_selected",
            scheduler="operator_or_queue",
            workspace_root="/workspace/training_jobs",
            environment_tags=["linux", "cuda"],
        )
    if backend == "ray_cluster":
        return build_execution_profile(
            profile_id="ray_cluster_default",
            execution_plane="distributed_execution",
            runner=backend,
            gpu_count=gpu_count,
            strategy=strategy,
            precision=precision,
            host_selector="ray_resource_labels",
            scheduler="ray_jobs",
            workspace_root="object_store_or_shared_volume",
            environment_tags=["ray", "linux", "cuda"],
        )
    return build_execution_profile(
        profile_id="local_default",
        execution_plane="local",
        runner=backend,
        gpu_count=gpu_count,
        strategy=strategy,
        precision=precision,
        host_selector="current_machine",
        scheduler="operator",
        workspace_root=".",
        environment_tags=["local"],
    )
