"""Persistent semantic index for accepted solution-library assets."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.learning.schemas import VectorRecord
from agent.learning.vector_store import VectorIndex, encode_texts_sentence_transformer, vectorize_text
from agent.solution_library.manifest import is_solution_library_ready, normalise_solution_manifest


@dataclass(frozen=True)
class SolutionEmbeddingConfig:
    backend: str = "hash"
    sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    dimensions: int = 256
    st_batch_size: int = 32
    use_faiss: bool = False

    @staticmethod
    def from_env() -> "SolutionEmbeddingConfig":
        backend = str(os.environ.get("AGENT_SOLUTION_EMBEDDING_BACKEND", "hash") or "hash").strip().lower()
        if backend not in {"hash", "sentence_transformer"}:
            backend = "hash"
        try:
            dimensions = max(int(os.environ.get("AGENT_SOLUTION_EMBEDDING_DIMENSIONS", "256")), 8)
        except ValueError:
            dimensions = 256
        try:
            batch_size = max(int(os.environ.get("AGENT_SOLUTION_ST_BATCH_SIZE", "32")), 1)
        except ValueError:
            batch_size = 32
        return SolutionEmbeddingConfig(
            backend=backend,
            sentence_transformer_model=str(
                os.environ.get(
                    "AGENT_SOLUTION_ST_MODEL",
                    "sentence-transformers/all-MiniLM-L6-v2",
                )
            ),
            dimensions=dimensions,
            st_batch_size=batch_size,
            use_faiss=str(os.environ.get("AGENT_SOLUTION_USE_FAISS", "")).strip().lower() in {"1", "true", "yes"},
        )


def _safe_read(path: Path, max_chars: int = 5000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except OSError:
        return ""


def _accepted_documents(manifest_paths: list[Path]) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for manifest_path in manifest_paths:
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict) or not is_solution_library_ready(raw):
            continue
        manifest = normalise_solution_manifest(raw)
        run_dir = manifest_path.parent
        backup = run_dir / "docs" / "SOLUTION_BACKUP.md"
        backup_text = _safe_read(backup)
        tags = manifest.get("retrieval_tags") if isinstance(manifest.get("retrieval_tags"), list) else []
        text = "\n".join(
            [
                str(manifest.get("goal", "")),
                str(manifest.get("stack", "")),
                str(manifest.get("template", "")),
                " ".join(str(x) for x in tags),
                backup_text,
            ]
        ).strip()
        if not text:
            continue
        docs.append(
            {
                "manifest": str(manifest_path),
                "run_dir": str(run_dir),
                "backup_path": str(backup) if backup.exists() else "",
                "template": str(manifest.get("template", "")),
                "text": text,
            }
        )
    return docs


def _fingerprint(manifest_paths: list[Path], docs: list[dict[str, str]], config: SolutionEmbeddingConfig) -> str:
    parts: list[dict[str, Any]] = [
        {
            "backend": config.backend,
            "model": config.sentence_transformer_model,
            "dimensions": config.dimensions,
        }
    ]
    docs_by_manifest = {doc["manifest"]: doc for doc in docs}
    for path in sorted(manifest_paths, key=lambda p: str(p)):
        try:
            stat = path.stat()
        except OSError:
            continue
        doc = docs_by_manifest.get(str(path), {})
        backup_raw = str(doc.get("backup_path", "") or "")
        backup_path = Path(backup_raw) if backup_raw else None
        try:
            backup_stat = backup_path.stat() if backup_path else None
        except OSError:
            backup_stat = None
        parts.append(
            {
                "manifest": str(path),
                "manifest_mtime_ns": int(stat.st_mtime_ns),
                "manifest_size": int(stat.st_size),
                "backup": str(backup_path) if backup_path else "",
                "backup_mtime_ns": int(backup_stat.st_mtime_ns) if backup_stat else 0,
                "backup_size": int(backup_stat.st_size) if backup_stat else 0,
            }
        )
    body = json.dumps(parts, ensure_ascii=False, sort_keys=True)
    return hashlib.blake2b(body.encode("utf-8"), digest_size=16).hexdigest()


def _index_dir(workspace: Path) -> Path:
    return workspace / ".agent_cache" / "solution_semantic"


def _build_records(
    docs: list[dict[str, str]],
    config: SolutionEmbeddingConfig,
) -> tuple[list[VectorRecord], str, str]:
    if not docs:
        return [], config.backend, ""
    effective_backend = config.backend
    fallback_reason = ""
    texts = [doc["text"] for doc in docs]
    vectors: list[list[float]]
    if config.backend == "sentence_transformer":
        try:
            vectors = encode_texts_sentence_transformer(
                texts,
                config.sentence_transformer_model,
                batch_size=config.st_batch_size,
            )
        except Exception as exc:
            effective_backend = "hash"
            fallback_reason = f"{type(exc).__name__}: {str(exc)[:160]}"
            vectors = [vectorize_text(text, dimensions=config.dimensions) for text in texts]
    else:
        vectors = [vectorize_text(text, dimensions=config.dimensions) for text in texts]
    records = [
        VectorRecord(
            record_id=doc["manifest"],
            text=doc["text"],
            metadata={
                "manifest": doc["manifest"],
                "run_dir": doc["run_dir"],
                "backup_path": doc["backup_path"],
                "template": doc["template"],
            },
            vector=vector,
        )
        for doc, vector in zip(docs, vectors)
    ]
    return records, effective_backend, fallback_reason


def ensure_solution_semantic_index(
    workspace: Path,
    manifest_paths: list[Path],
    *,
    config: SolutionEmbeddingConfig | None = None,
) -> tuple[VectorIndex, dict[str, Any]]:
    """Load or rebuild a persistent index for the accepted solution set."""

    cfg = config or SolutionEmbeddingConfig.from_env()
    docs = _accepted_documents(manifest_paths)
    fp = _fingerprint(manifest_paths, docs, cfg)
    out = _index_dir(workspace)
    index_path = out / "vector_index.jsonl"
    meta_path = out / "vector_meta.json"
    try:
        raw_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw_meta = {}
    if (
        isinstance(raw_meta, dict)
        and raw_meta.get("fingerprint") == fp
        and index_path.exists()
    ):
        index = VectorIndex.load_jsonl(index_path)
        return index, {
            "status": "reused",
            "path": str(index_path),
            "record_count": len(index.records),
            "fingerprint": fp,
            "backend_requested": str(raw_meta.get("backend_requested", cfg.backend)),
            "backend_effective": str(raw_meta.get("backend_effective", cfg.backend)),
            "fallback_reason": str(raw_meta.get("fallback_reason", "")),
        }

    records, effective_backend, fallback_reason = _build_records(docs, cfg)
    use_st = effective_backend == "sentence_transformer" and bool(records)
    dimensions = len(records[0].vector) if records else cfg.dimensions
    index = VectorIndex(
        records,
        dimensions=dimensions,
        use_sentence_transformer=use_st,
        sentence_transformer_model=cfg.sentence_transformer_model,
        use_faiss=cfg.use_faiss,
    )
    out.mkdir(parents=True, exist_ok=True)
    index.save_jsonl(index_path)
    meta = {
        **index.to_meta_dict(),
        "fingerprint": fp,
        "record_count": len(records),
        "backend_requested": cfg.backend,
        "backend_effective": effective_backend,
        "fallback_reason": fallback_reason,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return index, {
        "status": "built",
        "path": str(index_path),
        "record_count": len(records),
        "fingerprint": fp,
        "backend_requested": cfg.backend,
        "backend_effective": effective_backend,
        "fallback_reason": fallback_reason,
    }
