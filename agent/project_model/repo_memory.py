"""Build lightweight project-memory artifacts from a repository snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.learning.code_slicer import slice_repository
from agent.learning.knowledge_cards import build_knowledge_cards
from agent.learning.readme_parser import parse_readme
from agent.learning.schemas import CodeSlice, RepoCandidate
from agent.learning.structure_parser import parse_structure


@dataclass(frozen=True)
class RepoMemoryBuildInput:
    repo_path: Path
    output_dir: Path
    max_files: int = 500
    max_slices: int = 800


@dataclass(frozen=True)
class RepoMemoryBuildResult:
    output_dir: str
    repo_id: str
    files: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "repo_id": self.repo_id,
            "files": dict(self.files),
            "counts": dict(self.counts),
            "manifest": dict(self.manifest),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_digest(*parts: str, digest_size: int = 12) -> str:
    h = hashlib.blake2b(digest_size=digest_size)
    for part in parts:
        h.update(str(part).encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def _candidate_from_local_repo(repo_path: Path) -> RepoCandidate:
    root = repo_path.resolve()
    return RepoCandidate(
        full_name=f"local/{root.name}",
        html_url=f"file://{root}",
        description="Local repository snapshot supplied to repo-memory builder.",
        license_spdx="LOCAL",
        updated_at=datetime.fromtimestamp(root.stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        local_path=str(root),
    )


_SYMBOL_PATTERNS: dict[str, tuple[tuple[str, str], ...]] = {
    "python": (
        ("class", r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)"),
        ("function", r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "javascript": (
        ("class", r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        ("function", r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        ("function", r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\("),
    ),
    "typescript": (
        ("class", r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        ("interface", r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        ("function", r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)"),
        ("function", r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?\("),
    ),
    "java": (
        ("class", r"^\s*(?:public\s+)?(?:abstract\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)"),
        ("interface", r"^\s*(?:public\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "go": (
        ("function", r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][A-Za-z0-9_]*)"),
    ),
    "rust": (
        ("function", r"^\s*(?:pub\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)"),
        ("struct", r"^\s*(?:pub\s+)?struct\s+([A-Za-z_][A-Za-z0-9_]*)"),
        ("enum", r"^\s*(?:pub\s+)?enum\s+([A-Za-z_][A-Za-z0-9_]*)"),
        ("trait", r"^\s*(?:pub\s+)?trait\s+([A-Za-z_][A-Za-z0-9_]*)"),
    ),
}


def _extract_symbols(slices: list[CodeSlice]) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for sl in slices:
        patterns = _SYMBOL_PATTERNS.get(sl.language, ())
        if not patterns:
            continue
        for offset, line in enumerate(sl.text.splitlines(), start=sl.start_line):
            for symbol_kind, pattern in patterns:
                match = re.match(pattern, line)
                if not match:
                    continue
                name = match.group(1)
                key = (sl.path, name, offset)
                if key in seen:
                    continue
                seen.add(key)
                symbols.append(
                    {
                        "symbol_id": f"sym-{_stable_digest(sl.path, name, str(offset), digest_size=10)}",
                        "name": name,
                        "kind": symbol_kind,
                        "language": sl.language,
                        "path": sl.path,
                        "line": offset,
                        "slice_id": sl.slice_id,
                    }
                )
    return symbols


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _evidence_rows(repo_id: str, slices: list[CodeSlice]) -> list[dict[str, Any]]:
    return [
        {
            "evidence_id": f"ev-{_stable_digest(repo_id, sl.slice_id, digest_size=10)}",
            "repo_id": repo_id,
            "path": sl.path,
            "language": sl.language,
            "start_line": sl.start_line,
            "end_line": sl.end_line,
            "tokens": list(sl.tokens),
            "text": sl.text,
        }
        for sl in slices
    ]


def build_repo_memory(inp: RepoMemoryBuildInput) -> RepoMemoryBuildResult:
    repo_path = inp.repo_path.resolve()
    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate = _candidate_from_local_repo(repo_path)
    readme = parse_readme(repo_path)
    structure = parse_structure(repo_path, max_files=max(int(inp.max_files), 1))
    slices = slice_repository(repo_path, max_slices=max(int(inp.max_slices), 1))
    cards = build_knowledge_cards(candidate, readme, structure, slices)
    repo_id = f"repo-{_stable_digest(str(repo_path), str(repo_path.stat().st_mtime_ns))}"
    symbols = _extract_symbols(slices)
    evidence = _evidence_rows(repo_id, slices)

    project_map = {
        "schema": "project_map.v1",
        "repo_id": repo_id,
        "repo": candidate.to_dict(),
        "readme": readme.to_dict(),
        "structure": structure.to_dict(),
        "knowledge_cards": [card.to_dict() for card in cards],
    }
    project_map_path = output_dir / "project_map.json"
    symbol_index_path = output_dir / "symbol_index.jsonl"
    evidence_index_path = output_dir / "evidence_index.jsonl"
    manifest_path = output_dir / "repo_memory_manifest.json"
    report_path = output_dir / "report.md"
    _write_json(project_map_path, project_map)
    _write_jsonl(symbol_index_path, symbols)
    _write_jsonl(evidence_index_path, evidence)
    manifest = {
        "schema": "repo_memory_manifest.v1",
        "created_at": _now(),
        "repo_id": repo_id,
        "repo_path": str(repo_path),
        "counts": {
            "files": len(structure.files),
            "directories": len(structure.directories),
            "slices": len(slices),
            "symbols": len(symbols),
            "evidence_records": len(evidence),
            "knowledge_cards": len(cards),
        },
        "files": {
            "project_map": str(project_map_path),
            "symbol_index": str(symbol_index_path),
            "evidence_index": str(evidence_index_path),
        },
        "training_readiness": {
            "recommended_stage": "retrieval_grounded_understanding",
            "ready_for_tasks": [
                "repo_structure_mapping",
                "symbol_grounding",
                "evidence_retrieval",
                "repo_grounded_qa",
                "architecture_summary",
            ],
            "blockers": [],
        },
    }
    _write_json(manifest_path, manifest)
    report_path.write_text(
        "\n".join(
            [
                "# Repo Memory v1",
                "",
                f"- Repo id: `{repo_id}`",
                f"- Files: `{len(structure.files)}`",
                f"- Slices: `{len(slices)}`",
                f"- Symbols: `{len(symbols)}`",
                f"- Evidence records: `{len(evidence)}`",
                f"- Knowledge cards: `{len(cards)}`",
                "",
                "## Output",
                "",
                f"- Project map: `{project_map_path}`",
                f"- Symbol index: `{symbol_index_path}`",
                f"- Evidence index: `{evidence_index_path}`",
                f"- Manifest: `{manifest_path}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = {
        "project_map": str(project_map_path),
        "symbol_index": str(symbol_index_path),
        "evidence_index": str(evidence_index_path),
        "manifest": str(manifest_path),
        "report": str(report_path),
    }
    return RepoMemoryBuildResult(
        output_dir=str(output_dir),
        repo_id=repo_id,
        files=files,
        counts=dict(manifest["counts"]),
        manifest=manifest,
    )
