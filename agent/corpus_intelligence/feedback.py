"""Feedback loop contracts for corpus resampling and downstream learning."""

from __future__ import annotations

from collections import Counter
from typing import Any

from agent.corpus_intelligence.ranking import DEFAULT_WEIGHTS
from agent.corpus_intelligence.types import CorpusStrategy


_EVIDENCE_TAGS = ("docs", "tests", "entrypoints", "package_manifest", "frontend_backend_pair")


def _safe_rows(ranking: dict[str, Any]) -> list[dict[str, Any]]:
    rows = ranking.get("rows") if isinstance(ranking.get("rows"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _bounded(value: float) -> float:
    return max(0.0, min(round(float(value), 4), 10.0))


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    positive = {key: max(float(value), 0.0) for key, value in weights.items()}
    total = sum(positive.values())
    if total <= 0:
        return DEFAULT_WEIGHTS.to_dict()
    return {key: round(value / total, 4) for key, value in positive.items()}


def _route_value(row: dict[str, Any]) -> float:
    routes = {str(route) for route in row.get("routes", []) if str(route)}
    if "train_now" in routes:
        return 8.5
    if "distill_pool" in routes:
        return 7.0
    if "benchmark_holdout" in routes:
        return 6.5
    if "observe" in routes:
        return 4.5
    if "quarantine" in routes:
        return 2.0
    return 5.0


def _tag_utility(rows: list[dict[str, Any]]) -> dict[str, float]:
    values_by_tag: dict[str, list[float]] = {}
    for row in rows:
        value = _route_value(row)
        for tag in row.get("tags", []):
            tag_s = str(tag).strip()
            if tag_s:
                values_by_tag.setdefault(tag_s, []).append(value)
    return {
        tag: _bounded(sum(values) / len(values))
        for tag, values in values_by_tag.items()
        if values
    }


def _top_tags(utility: dict[str, float], *, minimum: float, limit: int = 4) -> list[str]:
    rows = [(tag, value) for tag, value in utility.items() if value >= minimum]
    rows.sort(key=lambda item: (-item[1], item[0]))
    return [tag for tag, _ in rows[:limit]]


def build_corpus_strategy(
    *,
    ranking: dict[str, Any],
    downstream_metrics: dict[str, float] | None = None,
    target_train_now_rate: float = 0.35,
) -> CorpusStrategy:
    """Turn intake + downstream signal into an executable next-round policy."""

    rows = _safe_rows(ranking)
    downstream = downstream_metrics or {}
    route_counts: Counter[str] = Counter()
    shape_counts: Counter[str] = Counter()
    for row in rows:
        route_counts.update(str(route) for route in row.get("routes", []) if str(route))
        shape_counts.update([str(row.get("shape", "unknown") or "unknown")])
    total = len(rows)
    train_now_rate = route_counts.get("train_now", 0) / total if total else 0.0
    shape_total = sum(shape_counts.values())
    max_shape_share = max(shape_counts.values(), default=0) / shape_total if shape_total else 0.0

    weights = DEFAULT_WEIGHTS.to_dict()
    kind_adjustments = {"seed": 0.0, "web_expansion": 0.0, "strategy_expansion": 0.0}
    tag_utility = _tag_utility(rows)
    promoted_facets = _top_tags(tag_utility, minimum=6.5)
    suppressed_facets = [
        tag
        for tag, value in sorted(tag_utility.items(), key=lambda item: (item[1], item[0]))
        if value <= 3.0
    ][:4]
    reasons: list[str] = []
    modes: list[str] = []
    routing = {"min_quality_delta": 0.0, "grounding_required": False}

    if train_now_rate < float(target_train_now_rate):
        modes.append("precision")
        reasons.append("train_now_rate_below_target")
        kind_adjustments["seed"] += 1.5
        kind_adjustments["web_expansion"] -= 0.5
        weights["lexical_relevance"] += 0.02
        weights["repo_quality"] += 0.04
        weights["governance"] += 0.02
    if max_shape_share > 0.70:
        modes.append("exploration")
        reasons.append("architecture_distribution_too_concentrated")
        kind_adjustments["web_expansion"] += 0.8
        kind_adjustments["strategy_expansion"] += 1.0
        weights["novelty"] += 0.08
    if float(downstream.get("recall_at_5_delta", 0.0) or 0.0) < 0:
        modes.append("retrieval_repair")
        reasons.append("retrieval_quality_regressed")
        weights["repo_quality"] += 0.04
        weights["downstream_utility"] += 0.05
        for tag in _EVIDENCE_TAGS:
            tag_utility[tag] = max(float(tag_utility.get(tag, 0.0)), 8.0)
            if tag not in promoted_facets:
                promoted_facets.append(tag)
    if float(downstream.get("citation_precision_delta", 0.0) or 0.0) < 0:
        modes.append("grounding_repair")
        reasons.append("citation_precision_regressed")
        weights["governance"] += 0.03
        routing["min_quality_delta"] = 0.4
        routing["grounding_required"] = True
        for tag in _EVIDENCE_TAGS:
            tag_utility[tag] = max(float(tag_utility.get(tag, 0.0)), 8.5)
            if tag not in promoted_facets:
                promoted_facets.append(tag)

    promoted_unique = list(dict.fromkeys(str(tag) for tag in promoted_facets if str(tag).strip()))[:8]
    suppressed_unique = [
        tag
        for tag in dict.fromkeys(str(tag) for tag in suppressed_facets if str(tag).strip())
        if tag not in promoted_unique
    ][:4]
    return {
        "schema": "corpus_strategy.v1",
        "mode": "+".join(dict.fromkeys(modes)) if modes else "balanced",
        "query": {
            "kind_score_adjustments": {key: round(value, 4) for key, value in kind_adjustments.items()},
            "promoted_facets": promoted_unique,
            "suppressed_facets": suppressed_unique,
        },
        "ranking": {
            "weights": _normalize_weights(weights),
            "tag_utility": {key: _bounded(value) for key, value in sorted(tag_utility.items())},
        },
        "routing": routing,
        "reasons": reasons,
    }


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
    strategy = build_corpus_strategy(
        ranking=ranking,
        downstream_metrics=downstream,
        target_train_now_rate=target_train_now_rate,
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
        "strategy": strategy,
    }
