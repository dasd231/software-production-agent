"""Runner abstraction for local, remote and future cluster training backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class TrainingRunner(ABC):
    name: str

    @abstractmethod
    def build_launch_command(self, spec_path: Path) -> str:
        """Return an operator-visible launch command for this runner."""

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Return runner capabilities for manifests and UIs."""
