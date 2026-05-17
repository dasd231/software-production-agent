"""Sandbox run tester for downloaded repositories.

函数流程图：
    run_sandbox_tests(repo_path, allow_commands)
      -> guard repo_path exists
      -> static file size / suspicious path checks
      -> Python in-memory compile checks for .py files
      -> optional pytest command only when allow_commands=True
      -> SandboxReport

你可以继续练算法/工程化的点：
    1. 真沙箱：现在是保守本地静态/编译检查；可接 Docker/Firecracker/Windows Sandbox。
    2. 网络隔离：可用容器网络策略禁止外联。
    3. 资源限制：可加入 CPU/mem/fs/time quota。
    4. 恶意检测：可接 Semgrep/Bandit/npm audit/license scanner。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from agent.learning.schemas import SandboxReport

IGNORED_PARTS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


def _iter_python_files(repo_path: Path, limit: int = 120) -> list[Path]:
    out: list[Path] = []
    root = repo_path.resolve()
    for path in sorted(root.rglob("*.py")):
        parts = path.relative_to(root).parts
        if any(part in IGNORED_PARTS or part.startswith(".agent_") for part in parts):
            continue
        out.append(path)
        if len(out) >= limit:
            break
    return out


def _check_workspace_size(repo_path: Path, max_files: int = 5000) -> dict[str, Any]:
    count = 0
    for path in repo_path.rglob("*"):
        parts = path.relative_to(repo_path).parts
        if any(part in IGNORED_PARTS or part.startswith(".agent_") for part in parts):
            continue
        count += 1
        if count > max_files:
            return {"name": "workspace_size", "ok": False, "detail": f"file_count>{max_files}"}
    return {"name": "workspace_size", "ok": True, "detail": f"file_count={count}"}


def _check_python_compile(repo_path: Path) -> dict[str, Any]:
    failures = []
    for path in _iter_python_files(repo_path):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            compile(source, str(path), "exec")
        except (SyntaxError, ValueError, OSError) as exc:
            failures.append({"path": path.relative_to(repo_path).as_posix(), "error": str(exc)[:300]})
    return {"name": "python_compile", "ok": not failures, "failures": failures[:20]}


def _run_pytest(repo_path: Path, timeout: float) -> dict[str, Any]:
    tests_exist = any("test" in p.name.lower() for p in repo_path.rglob("test*.py"))
    if not tests_exist:
        return {"name": "pytest", "ok": True, "skipped": True, "detail": "no pytest-like files"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(repo_path.resolve()),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"name": "pytest", "ok": False, "error": str(exc)[:500]}
    return {
        "name": "pytest",
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-1200:],
        "stderr": (proc.stderr or "")[-1200:],
    }


def run_sandbox_tests(repo_path: Path, *, allow_commands: bool = False, timeout: float = 60.0) -> SandboxReport:
    repo_path = repo_path.resolve()
    checks: list[dict[str, Any]] = []
    if not repo_path.exists() or not repo_path.is_dir():
        return SandboxReport(ok=False, checks=[{"name": "repo_exists", "ok": False, "detail": str(repo_path)}])
    checks.append({"name": "repo_exists", "ok": True, "detail": str(repo_path)})
    checks.append(_check_workspace_size(repo_path))
    checks.append(_check_python_compile(repo_path))
    commands: list[str] = []
    if allow_commands:
        checks.append(_run_pytest(repo_path, timeout))
        commands.append(f"{sys.executable} -m pytest -q")
    ok = all(bool(check.get("ok")) for check in checks)
    return SandboxReport(ok=ok, checks=checks, commands_run=commands)
