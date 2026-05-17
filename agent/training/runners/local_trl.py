"""Local single-node TRL runner used by the current workstation workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.training.runners.base import TrainingRunner


class LocalTRLRunner(TrainingRunner):
    name = "local_trl"

    def build_launch_command(self, spec_path: Path) -> str:
        return f'python -m agent.training.backup_trainer --config "{spec_path}"'

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "execution_plane": "local",
            "supports_remote_dispatch": False,
            "supports_multi_gpu": False,
            "supports_resume": True,
            "launcher": "python_module",
        }
