"""Synthesize first-generation repo-level training tasks from repo memories."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectTaskSynthesisInput:
    memory_dirs: tuple[Path, ...]
    output_dir: Path
    max_symbol_examples_per_repo: int = 64


@dataclass(frozen=True)
class ProjectTaskSynthesisResult:
    output_dir: str
    files: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "files": dict(self.files),
            "counts": dict(self.counts),
            "manifest": dict(self.manifest),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _stable_id(*parts: str) -> str:
    h = hashlib.blake2b(digest_size=12)
    for part in parts:
        h.update(str(part).encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _citation(path: str, *, line: int | None = None, start_line: int | None = None, end_line: int | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"path": path}
    if line is not None:
        out["line"] = line
    if start_line is not None:
        out["start_line"] = start_line
    if end_line is not None:
        out["end_line"] = end_line
    return out


def _structure_example(memory_dir: Path, manifest: dict[str, Any], project_map: dict[str, Any]) -> dict[str, Any]:
    structure = project_map.get("structure") if isinstance(project_map.get("structure"), dict) else {}
    repo = project_map.get("repo") if isinstance(project_map.get("repo"), dict) else {}
    repo_name = str(repo.get("full_name", "") or manifest.get("repo_id", ""))
    output = {
        "languages": structure.get("languages", {}),
        "entrypoints": structure.get("entrypoints", []),
        "tests": structure.get("tests", []),
        "package_files": structure.get("package_files", []),
    }
    return {
        "example_id": _stable_id("repo_structure_mapping", str(memory_dir), repo_name),
        "task_type": "repo_structure_mapping",
        "instruction": "根据项目快照，输出仓库的主要语言、入口、测试位置和依赖配置。",
        "input": f"仓库：{repo_name}",
        "output": json.dumps(output, ensure_ascii=False, sort_keys=True),
        "citations": [_citation(str(memory_dir / "project_map.json"))],
        "metadata": {"repo_id": manifest.get("repo_id", ""), "source": "repo_memory_v1"},
    }


def _architecture_summary_example(
    memory_dir: Path,
    manifest: dict[str, Any],
    project_map: dict[str, Any],
) -> dict[str, Any]:
    structure = project_map.get("structure") if isinstance(project_map.get("structure"), dict) else {}
    cards = project_map.get("knowledge_cards") if isinstance(project_map.get("knowledge_cards"), list) else []
    repo = project_map.get("repo") if isinstance(project_map.get("repo"), dict) else {}
    repo_name = str(repo.get("full_name", "") or manifest.get("repo_id", ""))
    overview = str((cards[0] if cards and isinstance(cards[0], dict) else {}).get("summary", "") or "")
    output = (
        f"{repo_name} 以 {', '.join((structure.get('languages') or {}).keys()) or '未知语言'} 为主。"
        f"入口文件包括 {', '.join(structure.get('entrypoints', [])[:5]) or '未识别'}；"
        f"测试位置包括 {', '.join(structure.get('tests', [])[:5]) or '未识别'}。"
        f"项目概述：{overview or '暂无 README 摘要。'}"
    )
    return {
        "example_id": _stable_id("architecture_summary", str(memory_dir), repo_name),
        "task_type": "architecture_summary",
        "instruction": "基于项目记忆卡，给出忠于证据的仓库架构摘要。",
        "input": f"仓库：{repo_name}",
        "output": output,
        "citations": [_citation(str(memory_dir / "project_map.json"))],
        "metadata": {"repo_id": manifest.get("repo_id", ""), "source": "repo_memory_v1"},
    }


def _symbol_examples(
    memory_dir: Path,
    manifest: dict[str, Any],
    symbols: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    repo_id = str(manifest.get("repo_id", ""))
    rows: list[dict[str, Any]] = []
    for symbol in symbols[: max(int(limit), 0)]:
        name = str(symbol.get("name", "") or "")
        path = str(symbol.get("path", "") or "")
        line = int(symbol.get("line", 0) or 0)
        kind = str(symbol.get("kind", "") or "")
        if not name or not path or line <= 0:
            continue
        rows.append(
            {
                "example_id": _stable_id("symbol_grounding", repo_id, name, path, str(line)),
                "task_type": "symbol_grounding",
                "instruction": "根据项目记忆，定位给定符号的定义位置。",
                "input": f"符号：{name}\n类型：{kind}",
                "output": f"`{name}` 定义在 `{path}` 第 {line} 行。",
                "citations": [_citation(path, line=line)],
                "metadata": {
                    "repo_id": repo_id,
                    "symbol_id": symbol.get("symbol_id", ""),
                    "source": "repo_memory_v1",
                },
            }
        )
    return rows


def _retrieval_rows(
    manifest: dict[str, Any],
    symbols: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    by_path: dict[str, list[dict[str, Any]]] = {}
    for row in evidence:
        by_path.setdefault(str(row.get("path", "")), []).append(row)
    examples: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    repo_id = str(manifest.get("repo_id", ""))
    for symbol in symbols[: max(int(limit), 0)]:
        name = str(symbol.get("name", "") or "")
        path = str(symbol.get("path", "") or "")
        line = int(symbol.get("line", 0) or 0)
        candidates = by_path.get(path, [])
        positive = next(
            (
                row
                for row in candidates
                if int(row.get("start_line", 0) or 0) <= line <= int(row.get("end_line", 0) or 0)
            ),
            candidates[0] if candidates else None,
        )
        if not name or not positive:
            continue
        query = f"项目里 `{name}` 在哪里定义？"
        citation = _citation(
            path,
            start_line=int(positive.get("start_line", 0) or 0),
            end_line=int(positive.get("end_line", 0) or 0),
        )
        examples.append(
            {
                "example_id": _stable_id("evidence_retrieval", repo_id, name, str(positive.get("evidence_id", ""))),
                "task_type": "evidence_retrieval",
                "instruction": "为项目问题找出最相关的证据片段。",
                "input": query,
                "output": f"优先查看 `{path}` 第 {citation['start_line']}-{citation['end_line']} 行。",
                "citations": [citation],
                "metadata": {
                    "repo_id": repo_id,
                    "positive_evidence_id": positive.get("evidence_id", ""),
                    "source": "repo_memory_v1",
                },
            }
        )
        pairs.append(
            {
                "pair_id": _stable_id("retrieval_pair", repo_id, name, str(positive.get("evidence_id", ""))),
                "repo_id": repo_id,
                "query": query,
                "positive_evidence_id": positive.get("evidence_id", ""),
                "positive_path": path,
                "positive_start_line": positive.get("start_line", 0),
                "positive_end_line": positive.get("end_line", 0),
            }
        )
    return examples, pairs


def synthesize_project_tasks(inp: ProjectTaskSynthesisInput) -> ProjectTaskSynthesisResult:
    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    examples: list[dict[str, Any]] = []
    retrieval_pairs: list[dict[str, Any]] = []
    source_manifests: list[dict[str, Any]] = []
    for memory_dir in inp.memory_dirs:
        root = memory_dir.resolve()
        manifest = _safe_json(root / "repo_memory_manifest.json")
        project_map = _safe_json(root / "project_map.json")
        symbols = _read_jsonl(root / "symbol_index.jsonl")
        evidence = _read_jsonl(root / "evidence_index.jsonl")
        if not manifest or not project_map:
            continue
        source_manifests.append(
            {
                "repo_id": manifest.get("repo_id", ""),
                "path": str(root / "repo_memory_manifest.json"),
            }
        )
        examples.append(_structure_example(root, manifest, project_map))
        examples.append(_architecture_summary_example(root, manifest, project_map))
        examples.extend(
            _symbol_examples(
                root,
                manifest,
                symbols,
                limit=inp.max_symbol_examples_per_repo,
            )
        )
        retrieval_examples, pairs = _retrieval_rows(
            manifest,
            symbols,
            evidence,
            limit=inp.max_symbol_examples_per_repo,
        )
        examples.extend(retrieval_examples)
        retrieval_pairs.extend(pairs)
    counts = Counter(str(row.get("task_type", "unknown")) for row in examples)
    training_examples_path = output_dir / "training_examples.jsonl"
    retrieval_pairs_path = output_dir / "retrieval_pairs.jsonl"
    manifest_path = output_dir / "project_task_manifest.json"
    report_path = output_dir / "report.md"
    _write_jsonl(training_examples_path, examples)
    _write_jsonl(retrieval_pairs_path, retrieval_pairs)
    manifest = {
        "schema": "project_task_manifest.v1",
        "created_at": _now(),
        "source_manifests": source_manifests,
        "counts": {
            "training_examples": len(examples),
            "retrieval_pairs": len(retrieval_pairs),
            **dict(counts),
        },
        "files": {
            "training_examples": str(training_examples_path),
            "retrieval_pairs": str(retrieval_pairs_path),
        },
        "compatible_with_training_prepare": True,
    }
    _write_json(manifest_path, manifest)
    report_path.write_text(
        "\n".join(
            [
                "# Project Task Synthesis",
                "",
                f"- Memory inputs: `{len(source_manifests)}`",
                f"- Training examples: `{len(examples)}`",
                f"- Retrieval pairs: `{len(retrieval_pairs)}`",
                "",
                "## Task Mix",
                "",
                *[f"- `{task}`: `{count}`" for task, count in sorted(counts.items())],
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = {
        "training_examples": str(training_examples_path),
        "retrieval_pairs": str(retrieval_pairs_path),
        "manifest": str(manifest_path),
        "report": str(report_path),
    }
    return ProjectTaskSynthesisResult(
        output_dir=str(output_dir),
        files=files,
        counts=dict(manifest["counts"]),
        manifest=manifest,
    )
