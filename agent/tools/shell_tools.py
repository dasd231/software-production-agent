"""Shell 工具层 — 与 gstack 执行层对齐的薄封装；实际进程由 runtime.runner 执行。"""

from __future__ import annotations

from pathlib import Path

from agent.runtime.runner import CommandResult, run_command


def run_shell(cmd: str, cwd: Path, timeout: float | None = 120.0) -> CommandResult:
    return run_command(cmd, cwd=cwd, timeout=timeout)
