"""Build a lightweight workspace index for context-aware planning/actions."""

from __future__ import annotations

from pathlib import Path

_IGNORE_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}
_PACKAGE_FILES = {"pyproject.toml", "requirements.txt", "package.json", "Cargo.toml", "go.mod"}


def _looks_like_test(path: str) -> bool:
    low = path.lower()
    return "/tests/" in f"/{low}" or low.startswith("test_") or "/test_" in low


def _guess_language(path: str) -> str | None:
    if path.endswith(".py"):
        return "python"
    if path.endswith(".ts") or path.endswith(".tsx") or path.endswith(".js") or path.endswith(".jsx"):
        return "javascript"
    if path.endswith(".go"):
        return "go"
    if path.endswith(".rs"):
        return "rust"
    return None


def build_workspace_index(root: Path, max_files: int = 2000) -> dict[str, object]:
    root = root.resolve()
    files: list[str] = []
    tests: list[str] = []
    languages: set[str] = set()
    entrypoints: list[str] = []
    package_files: list[str] = []
    ignored_count = 0
    truncated = False

    for p in root.rglob("*"):
        if p.is_dir():
            if p.name in _IGNORE_DIRS:
                ignored_count += 1
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if any(part in _IGNORE_DIRS for part in rel.split("/")):
            ignored_count += 1
            continue
        files.append(rel)
        if len(files) >= max_files:
            truncated = True
            break
        if _looks_like_test(rel):
            tests.append(rel)
        lang = _guess_language(rel)
        if lang:
            languages.add(lang)
        name = p.name
        if name in ("app.py", "main.py", "manage.py"):
            entrypoints.append(rel)
        if name in _PACKAGE_FILES:
            package_files.append(rel)

    return {
        "files": sorted(files),
        "languages": sorted(languages),
        "entrypoints": sorted(set(entrypoints)),
        "tests": sorted(tests),
        "package_files": sorted(package_files),
        "ignored_count": ignored_count,
        "truncated": truncated,
    }
