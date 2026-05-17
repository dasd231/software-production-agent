"""Unified RAG retrieval for workspace snippets plus optional learning stores."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.evaluation.rag import evaluate_unified_rag
from agent.learning.rag_qa import answer_question
from agent.learning.store import LearningStoreError, load_learning_cards
from agent.learning.vector_store import VectorIndex
from agent.rag.local_index import retrieve_snippets


@dataclass(frozen=True)
class UnifiedRAGResult:
    hints: list[dict[str, Any]]
    summary: dict[str, Any]


_LearningCacheValue = tuple[tuple[int, int, int, int], VectorIndex, list[Any]]
_LEARNING_STORE_CACHE: dict[str, _LearningCacheValue] = {}


def _round_ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 3)


def _fingerprint(index_path: Path, cards_path: Path) -> tuple[int, int, int, int]:
    index_stat = index_path.stat()
    cards_stat = cards_path.stat()
    return (
        int(index_stat.st_mtime_ns),
        int(index_stat.st_size),
        int(cards_stat.st_mtime_ns),
        int(cards_stat.st_size),
    )


def _load_learning_store(output_dir: Path) -> tuple[VectorIndex, list[Any]]:
    out = output_dir.resolve()
    index_path = out / "vector_index.jsonl"
    cards_path = out / "knowledge_cards.json"
    if not index_path.exists():
        raise LearningStoreError(f"missing vector_index.jsonl: {index_path}")
    if not cards_path.exists():
        raise LearningStoreError(f"missing knowledge_cards.json: {cards_path}")
    fp = _fingerprint(index_path, cards_path)
    key = str(out)
    cached = _LEARNING_STORE_CACHE.get(key)
    if cached and cached[0] == fp:
        return cached[1], cached[2]
    index = VectorIndex.load_jsonl(index_path)
    cards = load_learning_cards(out)
    _LEARNING_STORE_CACHE[key] = (fp, index, cards)
    return index, cards


def _source_counts(hints: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hint in hints:
        source = str(hint.get("source", "local_workspace") or "local_workspace")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _query_tokens(query: str) -> set[str]:
    return {part.lower() for part in query.replace("_", " ").split() if len(part) >= 2}


def _safe_score(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _learning_hint_from_evidence(
    evidence: dict[str, Any],
    *,
    query: str,
    output_dir: Path,
    confidence: float,
    trace: dict[str, Any],
) -> dict[str, Any]:
    preview = str(evidence.get("preview", "") or "")
    tokens = sorted(tok for tok in _query_tokens(query) if tok in preview.lower())
    path = str(evidence.get("path", "") or "")
    return {
        "path": path,
        "line_start": int(evidence.get("start_line") or 0),
        "line_end": int(evidence.get("end_line") or 0),
        "score": _safe_score(evidence.get("score")),
        "overlap_tokens": tokens[:12],
        "line_overlap_tokens": tokens[:12],
        "size_bytes": len(preview.encode("utf-8")),
        "truncated": len(preview) >= 360,
        "preview": preview,
        "source": "learning_run",
        "source_run": output_dir.name,
        "source_dir": str(output_dir),
        "confidence": confidence,
        "retrieval_mode": str(trace.get("mode", "")),
    }


def _retrieve_learning_hints(
    query: str,
    *,
    learning_dirs: tuple[str, ...],
    top_k: int,
    use_bm25: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    hints: list[dict[str, Any]] = []
    stores: list[dict[str, Any]] = []
    if not query.strip() or not learning_dirs:
        return hints, stores
    for raw_dir in learning_dirs:
        t0 = time.perf_counter()
        output_dir = Path(raw_dir).expanduser().resolve()
        store_summary: dict[str, Any] = {
            "dir": str(output_dir),
            "ok": False,
            "hits": 0,
        }
        try:
            index, cards = _load_learning_store(output_dir)
            answer = answer_question(
                query,
                index,
                cards,
                top_k=top_k,
                use_bm25=use_bm25,
                use_generative=False,
            )
            confidence = _safe_score(answer.get("confidence"))
            trace = answer.get("trace") if isinstance(answer.get("trace"), dict) else {}
            evidence = answer.get("evidence") if isinstance(answer.get("evidence"), list) else []
            for row in evidence[:top_k]:
                if isinstance(row, dict):
                    hints.append(
                        _learning_hint_from_evidence(
                            row,
                            query=query,
                            output_dir=output_dir,
                            confidence=confidence,
                            trace=trace,
                        )
                    )
            store_summary.update(
                {
                    "ok": True,
                    "hits": len(evidence[:top_k]),
                    "records": len(index.records),
                    "cards": len(cards),
                    "mode": str(trace.get("mode", "")),
                    "confidence": confidence,
                }
            )
        except Exception as exc:
            store_summary["error"] = str(exc)[:240]
        finally:
            store_summary["elapsed_ms"] = _round_ms(t0)
            stores.append(store_summary)
    return hints, stores


def _mark_local_hints(hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for hint in hints:
        row = dict(hint)
        row.setdefault("source", "local_workspace")
        out.append(row)
    return out


def _interleave(local_hints: list[dict[str, Any]], learning_hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    max_len = max(len(local_hints), len(learning_hints))
    for i in range(max_len):
        if i < len(local_hints):
            out.append(local_hints[i])
        if i < len(learning_hints):
            out.append(learning_hints[i])
    return out


def retrieve_unified_snippets(
    workspace: Path,
    query: str,
    *,
    top_k: int = 3,
    learning_dirs: tuple[str, ...] = (),
    learning_top_k: int = 2,
    use_learning_bm25: bool = True,
) -> UnifiedRAGResult:
    """Retrieve workspace evidence and optional offline learning-run evidence.

    The default path stays identical to local RAG. Learning stores are additive and
    fail closed: a malformed or missing store is recorded in the summary but never
    blocks the agent loop.
    """

    t0 = time.perf_counter()
    local_hints = _mark_local_hints(
        retrieve_snippets(
            workspace,
            query,
            top_k=max(int(top_k), 1),
        )
    )
    local_ms = _round_ms(t0)
    learning_t0 = time.perf_counter()
    learning_hints, stores = _retrieve_learning_hints(
        query,
        learning_dirs=tuple(str(x) for x in learning_dirs if str(x).strip()),
        top_k=max(int(learning_top_k), 1),
        use_bm25=bool(use_learning_bm25),
    )
    learning_ms = _round_ms(learning_t0)
    hints = _interleave(local_hints, learning_hints) if learning_hints else local_hints
    summary = {
        "local": {
            "enabled": True,
            "hits": len(local_hints),
            "elapsed_ms": local_ms,
        },
        "learning": {
            "enabled": bool(learning_dirs),
            "hits": len(learning_hints),
            "elapsed_ms": learning_ms,
            "stores": stores,
        },
        "total_hits": len(hints),
        "sources": _source_counts(hints),
    }
    summary["evaluation"] = evaluate_unified_rag(summary, hints).to_dict()
    return UnifiedRAGResult(hints=hints, summary=summary)
