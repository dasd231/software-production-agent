"""Hierarchical small-to-big RAG index utilities.

The learning pipeline already has good hybrid retrieval. This module adds the
missing scale-oriented layer: retrieve small child chunks for precision, then
expand them to parent chunks for context. The parent/child metadata is explicit
so Spark or other offline jobs can filter, aggregate and audit records without
parsing free-form text.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from agent.learning.schemas import CodeSlice, VectorRecord
from agent.learning.vector_store import VectorIndex, build_vector_index

SCHEMA_VERSION = "hierarchical_rag.v1"
PARENT_CHUNKS_FILE = "rag_parent_chunks.jsonl"
HIERARCHY_META_FILE = "rag_hierarchy_meta.json"


@dataclass(frozen=True)
class ParentChunk:
    parent_id: str
    text: str
    metadata: dict[str, Any]
    child_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SmallToBigSearchResult:
    score: float
    parent: ParentChunk
    child_hits: list[dict[str, Any]]

    def to_record(self) -> VectorRecord:
        metadata = dict(self.parent.metadata)
        metadata.update(
            {
                "schema": SCHEMA_VERSION,
                "granularity": "parent",
                "small_to_big": True,
                "matched_children": self.child_hits,
                "matched_child_count": len(self.child_hits),
            }
        )
        return VectorRecord(
            record_id=self.parent.parent_id,
            text=self.parent.text,
            metadata=metadata,
            vector=[],
        )


def _stable_hash(value: str, *, length: int = 12) -> str:
    return hashlib.blake2b(value.encode("utf-8"), digest_size=16).hexdigest()[:length]


def _estimate_tokens(text: str) -> int:
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    ascii_chars = max(len(text) - cjk, 0)
    return max(1, int(ascii_chars / 4 + cjk * 1.15))


def _path_parts(path: str) -> list[str]:
    return [part for part in path.replace("\\", "/").split("/") if part]


def _extension(path: str) -> str:
    name = _path_parts(path)[-1] if _path_parts(path) else path
    return Path(name).suffix.lower()


def infer_content_type(path: str, language: str = "") -> str:
    ext = _extension(path)
    name = (_path_parts(path)[-1] if _path_parts(path) else path).lower()
    lower_path = path.lower().replace("\\", "/")
    if name in {"readme.md", "license", "contributing.md"} or ext in {".md", ".rst", ".txt"}:
        return "documentation"
    if ext in {".yaml", ".yml", ".toml", ".ini", ".env", ".properties"} or name in {
        "dockerfile",
        "pom.xml",
        "package.json",
        "pyproject.toml",
    }:
        return "configuration"
    if "/test" in lower_path or "tests/" in lower_path or name.startswith("test_") or name.endswith("test.py"):
        return "test"
    if ext in {".sql"}:
        return "database"
    if language or ext in {".py", ".java", ".go", ".rs", ".js", ".ts", ".tsx", ".vue"}:
        return "code"
    return "artifact"


def infer_source_kind(path: str, language: str = "") -> str:
    content_type = infer_content_type(path, language)
    if content_type == "test":
        return "test_code"
    if content_type == "configuration":
        return "config"
    if content_type == "documentation":
        return "doc"
    if content_type == "database":
        return "schema"
    return "source_code"


def infer_symbol_hints(text: str, language: str = "") -> list[str]:
    patterns = [
        r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\bdef\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\bfunction\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"\b(?:public|private|protected)?\s*(?:static\s+)?[A-Za-z0-9_<>,\[\]]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        r"\bconst\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
    ]
    seen: list[str] = []
    used: set[str] = set()
    for pat in patterns:
        for m in re.finditer(pat, text):
            sym = m.group(1)
            if sym not in used:
                seen.append(sym)
                used.add(sym)
            if len(seen) >= 12:
                return seen
    return seen


def framework_hints(path: str, text: str) -> list[str]:
    hay = f"{path}\n{text}".lower()
    hints: list[str] = []
    checks = {
        "spring": ["@restcontroller", "springframework", "pom.xml"],
        "fastapi": ["fastapi", "@app.get", "@router."],
        "flask": ["flask", "@app.route"],
        "vue": ["<template", "definecomponent", "app.vue"],
        "react": ["react", "usestate", "tsx"],
        "pytest": ["pytest", "test_"],
        "docker": ["dockerfile", "docker-compose"],
        "kubernetes": ["apiversion:", "kind: deployment", "kind: service"],
    }
    for name, needles in checks.items():
        if any(n in hay for n in needles):
            hints.append(name)
    return hints


def build_rag_metadata(
    sl: CodeSlice,
    *,
    parent_id: str = "",
    repo_id: str = "",
    parent_start_line: int = 0,
    parent_end_line: int = 0,
    parent_token_count: int = 0,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    parts = _path_parts(sl.path)
    meta: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "schema_version": 1,
        "granularity": "child",
        "repo_id": repo_id,
        "path": sl.path,
        "path_parts": parts,
        "module_path": "/".join(parts[:-1]),
        "file_name": parts[-1] if parts else sl.path,
        "extension": _extension(sl.path),
        "language": sl.language,
        "content_type": infer_content_type(sl.path, sl.language),
        "source_kind": infer_source_kind(sl.path, sl.language),
        "start_line": int(sl.start_line),
        "end_line": int(sl.end_line),
        "line_count": max(0, int(sl.end_line) - int(sl.start_line) + 1),
        "token_count": _estimate_tokens(sl.text),
        "tokens": list(sl.tokens),
        "symbol_hints": infer_symbol_hints(sl.text, sl.language),
        "framework_hints": framework_hints(sl.path, sl.text),
        "parent_id": parent_id,
        "parent_start_line": int(parent_start_line or 0),
        "parent_end_line": int(parent_end_line or 0),
        "parent_token_count": int(parent_token_count or 0),
        "dedupe_key": _stable_hash(f"{repo_id}|{sl.path}|{sl.start_line}|{sl.end_line}|{sl.text[:1200]}"),
    }
    if extra:
        meta.update(dict(extra))
    return meta


def _line_map(slices: list[CodeSlice]) -> dict[int, str]:
    lines: dict[int, str] = {}
    for sl in sorted(slices, key=lambda x: (x.start_line, x.end_line)):
        for offset, line in enumerate(sl.text.splitlines()):
            line_no = int(sl.start_line) + offset
            lines.setdefault(line_no, line)
    return lines


def _slice_overlap(sl: CodeSlice, start_line: int, end_line: int) -> int:
    return max(0, min(int(sl.end_line), end_line) - max(int(sl.start_line), start_line) + 1)


def build_parent_chunks(
    slices: Iterable[CodeSlice],
    *,
    repo_id: str = "",
    parent_max_lines: int = 240,
    parent_overlap_lines: int = 40,
) -> dict[str, ParentChunk]:
    grouped: dict[str, list[CodeSlice]] = {}
    for sl in slices:
        grouped.setdefault(sl.path, []).append(sl)

    parents: dict[str, ParentChunk] = {}
    max_lines = max(int(parent_max_lines), 40)
    overlap = min(max(int(parent_overlap_lines), 0), max_lines - 1)
    step = max(max_lines - overlap, 1)

    for path, rows in sorted(grouped.items()):
        rows = sorted(rows, key=lambda x: (x.start_line, x.end_line))
        line_map = _line_map(rows)
        if not line_map:
            continue
        min_line, max_line_no = min(line_map), max(line_map)
        for start in range(min_line, max_line_no + 1, step):
            end = min(start + max_lines - 1, max_line_no)
            text_lines = [line_map[i] for i in range(start, end + 1) if i in line_map]
            text = "\n".join(text_lines).strip()
            if not text:
                continue
            child_ids = [sl.slice_id for sl in rows if _slice_overlap(sl, start, end) > 0]
            parent_id = f"parent:{_stable_hash(f'{repo_id}|{path}|{start}|{end}|{text[:1800]}', length=16)}"
            sample = rows[0]
            meta = {
                "schema": SCHEMA_VERSION,
                "schema_version": 1,
                "granularity": "parent",
                "repo_id": repo_id,
                "parent_id": parent_id,
                "path": path,
                "path_parts": _path_parts(path),
                "module_path": "/".join(_path_parts(path)[:-1]),
                "file_name": _path_parts(path)[-1] if _path_parts(path) else path,
                "extension": _extension(path),
                "language": sample.language,
                "content_type": infer_content_type(path, sample.language),
                "source_kind": infer_source_kind(path, sample.language),
                "start_line": start,
                "end_line": end,
                "line_count": end - start + 1,
                "token_count": _estimate_tokens(text),
                "child_count": len(child_ids),
                "symbol_hints": infer_symbol_hints(text, sample.language),
                "framework_hints": framework_hints(path, text),
                "dedupe_key": _stable_hash(f"parent|{repo_id}|{path}|{start}|{end}|{text[:1800]}"),
            }
            parents[parent_id] = ParentChunk(parent_id=parent_id, text=text, metadata=meta, child_ids=child_ids)
            if end >= max_line_no:
                break
    return parents


def _assign_parent(sl: CodeSlice, parents: Mapping[str, ParentChunk]) -> ParentChunk | None:
    best: tuple[int, int, str, ParentChunk] | None = None
    for parent in parents.values():
        if str(parent.metadata.get("path", "")) != sl.path:
            continue
        overlap = _slice_overlap(sl, int(parent.metadata.get("start_line", 0)), int(parent.metadata.get("end_line", 0)))
        if overlap <= 0:
            continue
        width = int(parent.metadata.get("line_count", 0) or 0)
        key = (overlap, -width, parent.parent_id, parent)
        if best is None or key[:3] > best[:3]:
            best = key
    return best[3] if best else None


def build_hierarchical_vector_index(
    slices: Iterable[CodeSlice],
    *,
    repo_id: str = "",
    parent_max_lines: int = 240,
    parent_overlap_lines: int = 40,
    dimensions: int = 256,
    use_openai: bool = False,
    client: Any | None = None,
    model: str = "text-embedding-3-small",
    use_sentence_transformer: bool = False,
    sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    st_batch_size: int = 32,
    use_faiss: bool = False,
    use_faiss_hnsw: bool = False,
    faiss_hnsw_min_vectors: int = 256,
    faiss_hnsw_m: int = 32,
    faiss_hnsw_ef_construct: int = 64,
    faiss_hnsw_ef_search: int = 64,
) -> tuple[VectorIndex, dict[str, ParentChunk], dict[str, Any]]:
    slices_list = list(slices)
    parents = build_parent_chunks(
        slices_list,
        repo_id=repo_id,
        parent_max_lines=parent_max_lines,
        parent_overlap_lines=parent_overlap_lines,
    )
    index = build_vector_index(
        slices_list,
        dimensions=dimensions,
        use_openai=use_openai,
        client=client,
        model=model,
        use_sentence_transformer=use_sentence_transformer and not use_openai,
        sentence_transformer_model=sentence_transformer_model,
        st_batch_size=st_batch_size,
        use_faiss=use_faiss,
        use_faiss_hnsw=use_faiss_hnsw,
        faiss_hnsw_min_vectors=faiss_hnsw_min_vectors,
        faiss_hnsw_m=faiss_hnsw_m,
        faiss_hnsw_ef_construct=faiss_hnsw_ef_construct,
        faiss_hnsw_ef_search=faiss_hnsw_ef_search,
    )
    by_id = {sl.slice_id: sl for sl in slices_list}
    enhanced_records: list[VectorRecord] = []
    for record in index.records:
        sl = by_id.get(record.record_id)
        if not sl:
            enhanced_records.append(record)
            continue
        parent = _assign_parent(sl, parents)
        if parent:
            metadata = build_rag_metadata(
                sl,
                parent_id=parent.parent_id,
                repo_id=repo_id,
                parent_start_line=int(parent.metadata.get("start_line", 0)),
                parent_end_line=int(parent.metadata.get("end_line", 0)),
                parent_token_count=int(parent.metadata.get("token_count", 0)),
            )
        else:
            metadata = build_rag_metadata(sl, repo_id=repo_id)
        enhanced_records.append(
            VectorRecord(
                record_id=record.record_id,
                text=record.text,
                metadata=metadata,
                vector=list(record.vector),
            )
        )
    index = VectorIndex(
        enhanced_records,
        dimensions=index.dimensions,
        use_openai=index.use_openai,
        client=index.client,
        model=index.model,
        use_sentence_transformer=index.use_sentence_transformer,
        sentence_transformer_model=index.sentence_transformer_model,
        use_faiss=index.use_faiss,
        use_faiss_hnsw=index.use_faiss_hnsw,
        faiss_hnsw_min_vectors=index.faiss_hnsw_min_vectors,
        faiss_hnsw_m=index.faiss_hnsw_m,
        faiss_hnsw_ef_construct=index.faiss_hnsw_ef_construct,
        faiss_hnsw_ef_search=index.faiss_hnsw_ef_search,
    )
    meta = {
        "schema": SCHEMA_VERSION,
        "repo_id": repo_id,
        "child_records": len(index.records),
        "parent_chunks": len(parents),
        "parent_max_lines": max(int(parent_max_lines), 40),
        "parent_overlap_lines": min(max(int(parent_overlap_lines), 0), max(int(parent_max_lines), 40) - 1),
        "metadata_fields": sorted({key for record in index.records for key in record.metadata.keys()}),
    }
    setattr(index, "parent_chunks", parents)
    setattr(index, "hierarchy_meta", meta)
    return index, parents, meta


def save_parent_chunks_jsonl(parents: Mapping[str, ParentChunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for parent_id in sorted(parents):
            f.write(json.dumps(parents[parent_id].to_dict(), ensure_ascii=False) + "\n")


def load_parent_chunks_jsonl(path: Path) -> dict[str, ParentChunk]:
    if not path.exists():
        return {}
    out: dict[str, ParentChunk] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            parent = ParentChunk(
                parent_id=str(raw.get("parent_id", "")),
                text=str(raw.get("text", "")),
                metadata=dict(raw.get("metadata") or {}),
                child_ids=[str(x) for x in raw.get("child_ids", [])],
            )
            if parent.parent_id:
                out[parent.parent_id] = parent
    return out


def save_hierarchy_artifacts(output_dir: Path, parents: Mapping[str, ParentChunk], meta: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    save_parent_chunks_jsonl(parents, output_dir / PARENT_CHUNKS_FILE)
    (output_dir / HIERARCHY_META_FILE).write_text(json.dumps(dict(meta), ensure_ascii=False, indent=2), encoding="utf-8")


def expand_evidence_small_to_big(
    evidence: list[tuple[float, VectorRecord]],
    parents: Mapping[str, ParentChunk],
    *,
    parent_top_k: int = 4,
) -> list[tuple[float, VectorRecord]]:
    grouped: dict[str, dict[str, Any]] = {}
    for score, child in evidence:
        parent_id = str(child.metadata.get("parent_id", "") or "")
        if not parent_id or parent_id not in parents:
            parent_id = child.record_id
            parent = ParentChunk(
                parent_id=parent_id,
                text=child.text,
                metadata={**dict(child.metadata), "granularity": "parent", "parent_id": parent_id},
                child_ids=[child.record_id],
            )
        else:
            parent = parents[parent_id]
        row = grouped.setdefault(
            parent_id,
            {
                "parent": parent,
                "max_score": float(score),
                "sum_score": 0.0,
                "children": [],
            },
        )
        row["max_score"] = max(float(row["max_score"]), float(score))
        row["sum_score"] = float(row["sum_score"]) + float(score)
        row["children"].append(
            {
                "record_id": child.record_id,
                "score": float(score),
                "path": child.metadata.get("path", ""),
                "start_line": child.metadata.get("start_line"),
                "end_line": child.metadata.get("end_line"),
                "tokens": list(child.metadata.get("tokens", []))[:20],
            }
        )
    ranked: list[SmallToBigSearchResult] = []
    for row in grouped.values():
        children = sorted(row["children"], key=lambda x: float(x.get("score", 0.0)), reverse=True)
        score = float(row["max_score"]) + min(len(children), 5) * 0.015 + min(float(row["sum_score"]), 1.0) * 0.02
        ranked.append(SmallToBigSearchResult(score=score, parent=row["parent"], child_hits=children[:8]))
    ranked.sort(key=lambda x: x.score, reverse=True)
    return [(hit.score, hit.to_record()) for hit in ranked[: max(1, int(parent_top_k))]]


def small_to_big_search(
    child_index: VectorIndex,
    parents: Mapping[str, ParentChunk],
    query: str,
    *,
    top_k: int = 4,
    child_fetch_k: int = 16,
) -> list[tuple[float, VectorRecord]]:
    child_hits = child_index.search(query, top_k=max(int(child_fetch_k), int(top_k)))
    return expand_evidence_small_to_big(child_hits, parents, parent_top_k=top_k)
