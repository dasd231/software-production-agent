"""Local production verification for generated workspaces."""

from __future__ import annotations

import py_compile
import sys
from pathlib import Path
from typing import Any

from agent.runtime.runner import run_command

_IGNORE_PARTS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}


def _iter_python_files(workspace: Path, max_files: int = 200) -> list[Path]:
    files: list[Path] = []
    for p in workspace.rglob("*.py"):
        if not p.is_file():
            continue
        if set(p.relative_to(workspace).parts) & _IGNORE_PARTS:
            continue
        files.append(p)
        if len(files) >= max_files:
            break
    return sorted(files, key=lambda x: str(x.relative_to(workspace)).replace("\\", "/"))


def _has_pytest_targets(workspace: Path) -> bool:
    for p in workspace.rglob("test_*.py"):
        if p.is_file() and not (set(p.relative_to(workspace).parts) & _IGNORE_PARTS):
            return True
    tests_dir = workspace / "tests"
    return tests_dir.exists() and any(tests_dir.rglob("*.py"))


def run_production_checks(
    workspace: Path,
    *,
    include_pytest: bool = True,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Run deterministic local checks without asking the model to invent commands."""
    ws = workspace.resolve()
    ws.mkdir(parents=True, exist_ok=True)
    py_files = _iter_python_files(ws)
    compile_failures: list[dict[str, str]] = []
    for p in py_files:
        rel = str(p.relative_to(ws)).replace("\\", "/")
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as e:
            compile_failures.append({"path": rel, "error": str(e)})

    checks: list[dict[str, Any]] = [
        {
            "name": "py_compile",
            "ok": len(compile_failures) == 0,
            "files_checked": len(py_files),
            "failures": compile_failures[:10],
        }
    ]

    pytest_result: dict[str, Any] | None = None
    if include_pytest and _has_pytest_targets(ws):
        cmd = f'"{sys.executable}" -m pytest -q'
        result = run_command(cmd, cwd=ws, timeout=timeout)
        pytest_result = {
            "name": "pytest",
            "ok": result.ok(),
            "command": cmd,
            "returncode": result.returncode,
            "stdout": result.stdout[-4000:],
            "stderr": result.stderr[-4000:],
        }
        checks.append(pytest_result)
    elif include_pytest:
        checks.append({"name": "pytest", "ok": True, "skipped": True, "reason": "no pytest targets detected"})

    ok = all(bool(c.get("ok")) for c in checks)
    return {
        "ok": ok,
        "workspace": str(ws),
        "checks": checks,
        "summary": {
            "python_files": len(py_files),
            "compile_failures": len(compile_failures),
            "pytest_ran": pytest_result is not None,
        },
    }
