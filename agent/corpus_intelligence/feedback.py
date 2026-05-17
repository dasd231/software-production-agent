"""Feedback loop contracts for corpus resampling and downstream learning."""

from __future__ import annotations

from collections import Counter
from typing import Any


def _safe_rows(ranking: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ranking.get("rows") if isinstance(ranking.get("rows"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def build_corpus_feedback_report(
    *,
    ranking: dict[str, Any],
    downstream_metrics: dict[str, float] | None = None,
    target_train_now_rate: float = 0.35,
) -> dict[str, Any]:
    """Summarize intake quality and convert downstream signal into resampling advice."""

    rows = _safe_rows(ranking)
    downstream = downstream_metrics or {}
    route_counts: Counter[str] = Counter()
    shape_counts: Counter[str] = Counter()
    gated_counts: Counter[str] = Counter()
    for row in rows:
        route_counts.update(str(route) for route in row.get("routes", []) if str(route))
        shape_counts.update([str(row.get("shape", "unknown") or "unknown")])
        gated_counts.update(str(gate) for gate in row.get("gates", []) if str(gate))
    total = len(rows)
    train_now_rate = route_counts.get("train_now", 0) / total if total else 0.0
    quarantine_rate = route_counts.get("quarantine", 0) / total if total else 0.0
    shape_total = sum(shape_counts.values())
    max_shape_share = max(shape_counts.values(), default=0) / shape_total if shape_total else 0.0

    actions: list[dict[str, Any]] = []
    if train_now_rate < float(target_train_now_rate):
        actions.append(
            {
                "id": "increase_precision",
                "reason": "train_now_rate_below_target",
                "suggestion": "tighten seed queries and favor historically productive web facets",
            }
        )
    if quarantine_rate > 0.20:
        actions.append(
            {
                "id": "tighten_governance_pre_filter",
                "reason": "quarantine_rate_high",
                "suggestion": "push license allowlist and provenance gates earlier in discovery",
            }
        )
    if max_shape_share > 0.70:
        actions.append(
            {
                "id": "increase_exploration",
                "reason": "architecture_distribution_too_concentrated",
                "suggestion": "raise novelty weight and allocate more query budget to underrepresented shapes",
            }
        )
    if float(downstream.get("recall_at_5_delta", 0.0) or 0.0) < 0:
        actions.append(
            {
                "id": "oversample_evidence_rich_repos",
                "reason": "retrieval_quality_regressed",
                "suggestion": "increase weight for docs/tests/entrypoints and reduce low-evidence repos",
            }
        )
    if float(downstream.get("citation_precision_delta", 0.0) or 0.0) < 0:
        actions.append(
            {
                "id": "raise_grounding_gate",
                "reason": "citation_precision_regressed",
                "suggestion": "require stronger evidence coverage before sending repos to teacher supervision",
            }
        )
    return {
        "schema": "corpus_feedback_report.v1",
        "summary": {
            "candidates": total,
            "train_now_rate": round(train_now_rate, 4),
            "quarantine_rate": round(quarantine_rate, 4),
            "max_shape_share": round(max_shape_share, 4),
            "route_counts": dict(route_counts),
            "shape_counts": dict(shape_counts),
            "gated_counts": dict(gated_counts),
        },
        "downstream_metrics": {str(key): float(value) for key, value in downstream.items()},
        "recommended_actions": actions,
    }
