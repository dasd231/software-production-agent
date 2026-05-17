"""Contract-first Linux remote runner.

This runner intentionally does not open SSH connections yet.  It defines the
runner contract that a later dispatcher, queue worker or cluster adapter can
consume without changing training-job semantics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.training.runners.base import TrainingRunner


class LinuxRemoteRunner(TrainingRunner):
    name = "linux_remote"

    def build_launch_command(self, spec_path: Path) -> str:
        return f'python -m agent.training.safe_launcher --config "{spec_path}"'

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "execution_plane": "remote_linux",
            "supports_remote_dispatch": True,
            "supports_multi_gpu": True,
            "supports_resume": True,
            "launcher": "remote_python_module",
            "dispatch_mode": "contract_only",
        }
