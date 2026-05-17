"""Evaluation for unified local/learning RAG retrieval."""

from __future__ import annotations

from typing import Any

from agent.evaluation.schemas import Metric, MetricReport, clamp_score


def _latency_score(elapsed_ms: float) -> float:
    if elapsed_ms <= 500:
        return 10.0
    if elapsed_ms <= 2000:
        return 7.0
    if elapsed_ms <= 5000:
        return 4.0
    return 2.0


def evaluate_unified_rag(summary: dict[str, Any], hints: list[dict[str, Any]]) -> MetricReport:
    local = summary.get("local") if isinstance(summary.get("local"), dict) else {}
    learning = summary.get("learning") if isinstance(summary.get("learning"), dict) else {}
    sources = summary.get("sources") if isinstance(summary.get("sources"), dict) else {}
    total_hits = int(summary.get("total_hits") or len(hints))
    local_hits = int(local.get("hits") or 0)
    learning_hits = int(learning.get("hits") or 0)
    stores = learning.get("stores") if isinstance(learning.get("stores"), list) else []
    learning_enabled = bool(learning.get("enabled"))
    ok_stores = sum(1 for store in stores if isinstance(store, dict) and store.get("ok"))
    store_health = ok_stores / len(stores) if stores else 1.0
    elapsed_ms = float(local.get("elapsed_ms") or 0.0) + float(learning.get("elapsed_ms") or 0.0)
    truncated_count = sum(1 for hint in hints if hint.get("truncated"))
    truncated_ratio = truncated_count / len(hints) if hints else 0.0
    confidence_values = [float(hint.get("confidence")) for hint in hints if isinstance(hint.get("confidence"), (int, float))]
    avg_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
    metrics = (
        Metric("total_hits", total_hits, 10.0 if total_hits else 0.0, weight=2.0, status="ok" if total_hits else "empty"),
        Metric("local_hits", local_hits, 10.0 if local_hits else 0.0, weight=1.5),
        Metric("learning_hits", learning_hits, 10.0 if learning_hits else 6.0 if not learning_enabled else 0.0, weight=0.8),
        Metric("learning_store_health", round(store_health, 4), store_health * 10.0, weight=1.0 if learning_enabled else 0.0),
        Metric("source_diversity", len(sources), min(max(len(sources), 1), 3) / 3.0 * 10.0 if total_hits else 0.0, weight=0.6),
        Metric("retrieval_latency_ms", round(elapsed_ms, 3), _latency_score(elapsed_ms), weight=0.8),
        Metric("truncation_rate", round(truncated_ratio, 4), (1.0 - truncated_ratio) * 10.0, weight=0.5),
        Metric("learning_confidence", round(avg_confidence, 4) if avg_confidence is not None else None, clamp_score((avg_confidence or 0.0) * 10.0), weight=0.4 if avg_confidence is not None else 0.0),
    )
    return MetricReport(
        stage="rag.unified_retrieval",
        metrics=metrics,
        summary={
            "total_hits": total_hits,
            "sources": dict(sources),
            "learning_enabled": learning_enabled,
            "store_count": len(stores),
        },
    )
