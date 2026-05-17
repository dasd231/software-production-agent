"""Source code slicer.

函数流程图：
    slice_repository(repo_path)
      -> iter source-like files from structure rules
      -> read text with size guard
      -> split into overlapping line windows
      -> tokenize each slice
      -> list[CodeSlice]

你可以继续练算法/工程化的点：
    1. 语义切片：现在按行窗口；可按 AST 函数/类/组件切片。
    2. Token 预算：现在简单 max_lines/max_chars；可按目标 embedding 模型 token 预算。
    3. 去重：可对重复 boilerplate、lock files、generated code 做 simhash 去重。
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.learning.schemas import CodeSlice

SOURCE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".vue": "vue",
    ".html": "html",
    ".css": "css",
    ".md": "markdown",
}
IGNORED_PARTS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build"}


def tokenize(text: str, limit: int = 80) -> tuple[str, ...]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u4e00-\u9fff]{2,}", text.lower())
    seen: list[str] = []
    seen_set: set[str] = set()
    for token in tokens:
        if token not in seen_set:
            seen.append(token)
            seen_set.add(token)
        if len(seen) >= limit:
            break
    return tuple(seen)


def _iter_source_files(repo_path: Path, max_file_bytes: int) -> list[Path]:
    root = repo_path.resolve()
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts
        if any(part in IGNORED_PARTS or part.startswith(".agent_") for part in parts):
            continue
        if not path.is_file() or path.suffix.lower() not in SOURCE_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > max_file_bytes:
                continue
        except OSError:
            continue
        out.append(path)
    return out


def slice_repository(
    repo_path: Path,
    *,
    max_lines: int = 80,
    overlap_lines: int = 12,
    max_file_bytes: int = 220_000,
    max_slices: int = 800,
) -> list[CodeSlice]:
    root = repo_path.resolve()
    slices: list[CodeSlice] = []
    step = max(max_lines - overlap_lines, 1)
    for path in _iter_source_files(root, max_file_bytes):
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        if not lines:
            continue
        for start in range(0, len(lines), step):
            chunk = "\n".join(lines[start : start + max_lines])
            if not chunk.strip():
                continue
            rel = path.relative_to(root).as_posix()
            slices.append(
                CodeSlice(
                    path=rel,
                    language=SOURCE_EXTENSIONS.get(path.suffix.lower(), ""),
                    start_line=start + 1,
                    end_line=min(start + max_lines, len(lines)),
                    text=chunk,
                    tokens=tokenize(chunk),
                )
            )
            if len(slices) >= max_slices:
                return slices
    return slices
