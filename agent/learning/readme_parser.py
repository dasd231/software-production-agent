"""README parser.

函数流程图：
    parse_readme(repo_path)
      -> find_readme()
      -> read_text()
      -> _extract_title()
      -> _split_sections()
      -> _summarize()
      -> ParsedReadme

你可以继续练算法/工程化的点：
    1. 摘要算法：现在是规则摘要；可接 LLM/card generator 或 TextRank。
    2. Markdown AST：现在按 heading 正则；可接 markdown-it/Marko 做结构解析。
    3. 质量评分：可识别 install/usage/API/license/test 等章节完整度。
"""

from __future__ import annotations

import re
from pathlib import Path

from agent.learning.schemas import ParsedReadme


def find_readme(repo_path: Path) -> Path | None:
    for name in ("README.md", "README.rst", "README.txt", "readme.md", "Readme.md"):
        path = repo_path / name
        if path.is_file():
            return path
    for path in repo_path.iterdir() if repo_path.exists() else []:
        if path.is_file() and path.name.lower().startswith("readme"):
            return path
    return None


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        m = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if m:
            return m.group(1).strip()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:100]
    return fallback


def _split_sections(text: str, limit: int = 1200) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current = "overview"
    sections[current] = []
    for line in text.splitlines():
        m = re.match(r"^\s{0,3}#{1,4}\s+(.+?)\s*$", line)
        if m:
            current = m.group(1).strip().lower()[:80]
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {key: "\n".join(value).strip()[:limit] for key, value in sections.items() if "\n".join(value).strip()}


def _summarize(text: str, limit: int = 420) -> str:
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    cleaned = re.sub(r"\[[^\]]+\]\([^)]+\)", lambda m: m.group(0).split("]")[0].lstrip("["), cleaned)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    summary = " ".join(lines[:6])
    return re.sub(r"\s+", " ", summary)[:limit]


def parse_readme(repo_path: Path) -> ParsedReadme:
    readme = find_readme(repo_path)
    if readme is None:
        return ParsedReadme(path="", title=repo_path.name, summary="", sections={})
    text = readme.read_text(encoding="utf-8", errors="replace")
    rel = readme.relative_to(repo_path).as_posix()
    return ParsedReadme(
        path=rel,
        title=_extract_title(text, repo_path.name),
        summary=_summarize(text),
        sections=_split_sections(text),
    )
