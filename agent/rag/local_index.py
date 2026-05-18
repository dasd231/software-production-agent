"""Tiny local text retriever without external vector DB dependencies."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

_TEXT_EXTS = {".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml"}
_IGNORE_PARTS = {
    ".git",
    ".agent_cache",
    ".agent_feedback",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
_IGNORE_NAMES = {
    ".agent_events.jsonl",
    ".agent_session.jsonl",
    ".agent_state.json",
}
_ENTRY_NAMES = ("app.py", "main.py", "server.py", "pyproject.toml", "README.md")
_ENTRY_RANK = {name: i for i, name in enumerate(_ENTRY_NAMES)}


def _identifier_parts(token: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token)
    spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
    return {p.lower() for p in re.split(r"_+|\s+", spaced) if 3 <= len(p) <= 40}


def _tokens(s: str) -> set[str]:
    out: set[str] = set()
    for raw in re.findall(r"(?u)(?:[^\W\d]|_)\w{2,39}", s):
        token = raw.lower()
        if len(token) <= 40:
            out.add(token)
        out.update(_identifier_parts(raw))
    return out


def _entry_rank(name: str) -> int:
    return _ENTRY_RANK.get(name, len(_ENTRY_RANK))


def _iter_text_files(root: Path, max_files: int) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _IGNORE_PARTS)
        for name in sorted(filenames):
            if name in _IGNORE_NAMES:
                continue
            p = Path(dirpath) / name
            if p.suffix.lower() not in _TEXT_EXTS:
                continue
            out.append(p)
            if len(out) >= max_files:
                return out
    return out


def _read_text_prefix(path: Path, max_chars: int) -> tuple[str, bool, int]:
    try:
        size_bytes = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as f:
            text = f.read(max_chars + 1)
    except OSError:
        return "", False, 0
    if "\x00" in text:
        return "", False, size_bytes
    return text[:max_chars], len(text) > max_chars, size_bytes


def _line_window(lines: list[str], line_no: int, radius: int = 2) -> str:
    start = max(1, line_no - radius)
    end = min(len(lines), line_no + radius)
    return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1))[:700]


def _best_line_match(lines: list[str], q_tokens: set[str]) -> tuple[int, int, list[str]]:
    best_line = 1
    best_score = 0
    best_overlap: list[str] = []
    for i, line in enumerate(lines, start=1):
        overlap = sorted(_tokens(line) & q_tokens)
        score = len(overlap)
        if score > best_score:
            best_line = i
            best_score = score
            best_overlap = overlap
    return best_line, best_score, best_overlap


def build_local_index(root: Path, max_files: int = 80, max_chars_per_file: int = 3000) -> list[dict[str, Any]]:
    """Build a compact in-memory index snapshot for deterministic local retrieval."""
    ws = root.resolve()
    rows: list[dict[str, Any]] = []
    for p in _iter_text_files(ws, max_files=max_files):
        body, truncated, size_bytes = _read_text_prefix(p, max_chars=max_chars_per_file)
        if not body:
            continue
        rel = str(p.relative_to(ws)).replace("\\", "/")
        path_tokens = _tokens(re.sub(r"[/\\._-]+", " ", rel))
        body_tokens = _tokens(body)
        rows.append(
            {
                "path": rel,
                "name": p.name,
                "suffix": p.suffix.lower(),
                "tokens": sorted(body_tokens)[:1000],
                "path_tokens": sorted(path_tokens),
                "line_count": len(body.splitlines()),
                "size_bytes": size_bytes,
                "truncated": truncated,
                "preview": "\n".join(body.splitlines()[:8])[:500],
                "text": body,
            }
        )
    return rows


def retrieve_snippets(
    root: Path,
    query: str,
    top_k: int = 3,
    max_files: int = 80,
    max_chars_per_file: int = 3000,
) -> list[dict[str, Any]]:
    q_tokens = _tokens(query)
    index = build_local_index(root, max_files=max_files, max_chars_per_file=max_chars_per_file)
    if not q_tokens:
        entries = [row for row in index if str(row.get("name", "")) in _ENTRY_RANK]
        entries.sort(
            key=lambda row: (_entry_rank(str(row.get("name", ""))), str(row.get("path", "")))
        )
        entries = entries or index[: max(1, top_k)]
        return [
            {
                "path": row["path"],
                "score": 0,
                "line_start": 1,
                "line_end": min(int(row.get("line_count", 0) or 0), 8),
                "overlap_tokens": [],
                "size_bytes": int(row.get("size_bytes", 0) or 0),
                "truncated": bool(row.get("truncated", False)),
                "preview": row["preview"],
            }
            for row in entries[: max(1, top_k)]
        ]
    scored: list[tuple[int, int, int, str, dict[str, Any]]] = []
    query_l = query.lower()
    for row in index:
        body = str(row.get("text", ""))
        b_tokens = set(row.get("tokens", []))
        path_tokens = set(row.get("path_tokens", []))
        overlap = q_tokens & (b_tokens | path_tokens)
        score = len(overlap)
        if score <= 0:
            continue
        lines = body.splitlines()
        line_no, line_score, line_overlap = _best_line_match(lines, q_tokens)
        preview = _line_window(lines, line_no)
        phrase_bonus = 3 if query_l and query_l in body.lower() else 0
        path_bonus = len(q_tokens & path_tokens) * 2
        body_bonus = len(q_tokens & b_tokens) * 4
        score = body_bonus + path_bonus + line_score + phrase_bonus
        scored.append(
            (
                score,
                line_score,
                _entry_rank(str(row.get("name", ""))),
                str(row.get("path", "")),
                {
                    "path": str(row.get("path", "")),
                    "score": score,
                    "overlap_tokens": sorted(overlap)[:12],
                    "line_start": max(1, line_no - 2),
                    "line_end": min(len(lines), line_no + 2),
                    "line_overlap_tokens": line_overlap[:12],
                    "size_bytes": int(row.get("size_bytes", 0) or 0),
                    "truncated": bool(row.get("truncated", False)),
                    "preview": preview,
                },
            )
        )
    scored.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    return [item for _, _, _, _, item in scored[: max(1, top_k)]]
