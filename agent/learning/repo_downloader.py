"""Repository downloader / local copier.

函数流程图：
    download_repo(candidate, dest_root)
      -> _safe_repo_dir_name()
      -> 目标路径限制在 dest_root 内
      -> candidate.local_path 或 file:// ?
           -> copy_repo_tree()
         else
           -> git clone --depth 1 candidate.clone_url
      -> 返回本地 repo path

你可以继续练算法/工程化的点：
    1. 下载策略：现在支持 git clone/local copy；可加 zipball 下载和 content-addressed cache。
    2. 安全策略：现在不执行 repo 代码；后续可对下载内容做 size/license/malware 扫描。
    3. 缓存：可按 full_name + commit hash 缓存，避免重复下载。
    4. 并发：可对多 repo 下载做限速并发和失败重试。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from agent.learning.schemas import RepoCandidate

IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".pytest_cache", ".mypy_cache"}


class RepoDownloadError(RuntimeError):
    pass


def _safe_repo_dir_name(full_name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in full_name)
    return cleaned.strip("._") or "repo"


def _ensure_child(root: Path, target: Path) -> Path:
    root = root.resolve()
    target = target.resolve()
    if target != root and root not in target.parents:
        raise RepoDownloadError(f"path escapes destination root: {target}")
    return target


def copy_repo_tree(source: Path, dest: Path) -> Path:
    source = source.resolve()
    if not source.exists() or not source.is_dir():
        raise RepoDownloadError(f"not a directory: {source}")
    if dest.exists():
        shutil.rmtree(dest)

    def ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in IGNORED_DIRS or name.startswith(".agent_")}

    shutil.copytree(source, dest, ignore=ignore)
    return dest


def download_repo(candidate: RepoCandidate, dest_root: Path) -> Path:
    dest_root = dest_root.resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = _ensure_child(dest_root, dest_root / _safe_repo_dir_name(candidate.full_name))
    if candidate.local_path:
        return copy_repo_tree(Path(candidate.local_path), dest)
    if candidate.html_url.startswith("file://"):
        return copy_repo_tree(Path(candidate.html_url.removeprefix("file://")), dest)
    clone_url = candidate.clone_url or candidate.html_url
    if not clone_url:
        raise RepoDownloadError("candidate has no clone_url/html_url/local_path")
    if dest.exists():
        shutil.rmtree(dest)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(dest)],
            cwd=str(dest_root),
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise RepoDownloadError(str(exc)) from exc
    return dest
