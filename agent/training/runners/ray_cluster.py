"""Contract-first Ray cluster runner for future distributed training dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.training.runners.base import TrainingRunner


class RayClusterRunner(TrainingRunner):
    name = "ray_cluster"

    def build_launch_command(self, spec_path: Path) -> str:
        return f'python -m agent.training.backup_trainer --config "{spec_path}"'

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "execution_plane": "distributed_execution",
            "supports_remote_dispatch": True,
            "supports_multi_gpu": True,
            "supports_resume": True,
            "launcher": "ray_job_submission",
            "dispatch_mode": "contract_only",
        }
