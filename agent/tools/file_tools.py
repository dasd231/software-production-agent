"""文件工具层 — 语义来自 gstack「执行层」：仅受控文件操作，不作为应用主框架。"""

from __future__ import annotations

from pathlib import Path


class FileToolError(RuntimeError):
    pass


def _guard_path(root: Path, rel: str) -> Path:
    root = root.resolve()
    target = (root / rel).resolve()
    if root not in target.parents and target != root:
        raise FileToolError(f"path escapes workspace: {rel}")
    return target


def read_file(root: Path, rel_path: str) -> str:
    p = _guard_path(root, rel_path)
    if not p.is_file():
        raise FileToolError(f"not a file: {rel_path}")
    return p.read_text(encoding="utf-8", errors="replace")


def write_file(root: Path, rel_path: str, content: str) -> None:
    p = _guard_path(root, rel_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def list_files(root: Path, pattern: str = "**/*") -> list[str]:
    if not root.exists():
        return []
    out: list[str] = []
    for p in root.glob(pattern):
        if p.is_file():
            out.append(str(p.relative_to(root)).replace("\\", "/"))
    return sorted(out)
