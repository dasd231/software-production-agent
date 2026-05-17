"""Git 工具 — 轻量封装；由 executor 以结构化 Action 调用。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.runtime.runner import run_command


def git_status(cwd: Path) -> str:
    r = run_command("git status --porcelain", cwd=cwd, timeout=30.0)
    if r.returncode != 0:
        return f"(git unavailable) {r.stderr.strip()}"
    return r.stdout or "(clean)"


def git_init_if_needed(cwd: Path) -> dict[str, Any]:
    if (cwd / ".git").exists():
        return {"ok": True, "status": "already_git_repo", "stderr": ""}
    r = run_command("git init", cwd=cwd, timeout=60.0)
    return {
        "ok": r.returncode == 0,
        "status": "init_ok" if r.returncode == 0 else "init_failed",
        "stdout": r.stdout,
        "stderr": r.stderr,
    }
