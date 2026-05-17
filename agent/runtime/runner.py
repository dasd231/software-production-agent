"""Runtime：执行命令并捕获 stdout/stderr — 反馈给 Agent（AIread 第 96–104 行）。"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    cwd: str

    def ok(self) -> bool:
        return self.returncode == 0

    def feedback_block(self) -> str:
        parts = [
            f"command: {self.command}",
            f"cwd: {self.cwd}",
            f"returncode: {self.returncode}",
        ]
        if self.stdout.strip():
            parts.append("--- stdout ---\n" + self.stdout)
        if self.stderr.strip():
            parts.append("--- stderr ---\n" + self.stderr)
        return "\n".join(parts)


def run_command(cmd: str, cwd: Path, timeout: float | None = 120.0) -> CommandResult:
    """在 cwd 下执行 shell 命令（Windows 下通过 shell=True）。"""
    cwd = cwd.resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return CommandResult(
            command=cmd,
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            cwd=str(cwd),
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        err = (e.stderr or "") if isinstance(e.stderr, str) else str(e)
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout=out,
            stderr=err + "\n[timeout]",
            cwd=str(cwd),
        )
    except OSError as e:
        return CommandResult(
            command=cmd,
            returncode=-1,
            stdout="",
            stderr=str(e),
            cwd=str(cwd),
        )


def run_python_module(module: str, cwd: Path) -> CommandResult:
    """例如 python app.py → 用当前解释器。"""
    return run_command(f'"{sys.executable}" {module}', cwd=cwd)
