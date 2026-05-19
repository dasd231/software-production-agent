"""CPU-only middle-layer decision helper for expensive software rules."""

from __future__ import annotations

from typing import Any

from .schema import MiddleModelInput, cost_signal, numeric_signal, risk_signal


def _candidate_id(candidate: dict[str, Any], index: int) -> str:
    for key in ("id", "name", "rule", "route", "label"):
        value = str(candidate.get(key, "") or "").strip()
        if value:
            return value
    return f"candidate-{index + 1}"


def _score_candidate(candidate: dict[str, Any], *, budget_ms: int) -> dict[str, Any]:
    quality = numeric_signal(candidate)
    cost = cost_signal(candidate, budget_ms=budget_ms)
    # Cheap, high-quality candidates should surface first.  Cost penalty is
    # intentionally mild so high-quality candidates are not over-pruned.
    score = max(0.0, min(1.0, quality * 0.82 + (1.0 - cost) * 0.18))
    confidence = max(quality, score * 0.92)
    return {
        "quality_signal": round(quality, 4),
        "cost_signal": round(cost, 4),
        "score": round(score, 4),
        "confidence": round(max(0.0, min(confidence, 1.0)), 4),
    }


def decide_with_middle_model(model_input: MiddleModelInput | dict[str, Any]) -> dict[str, Any]:
    """Rank candidates and decide whether slow rules can be skipped.

    The function is side-effect-free and intentionally deterministic.  It is the
    stable seam for a future trained small model: keep the input/output contract,
    replace the scorer/backend when the small model is ready.
    """

    inp = model_input if isinstance(model_input, MiddleModelInput) else MiddleModelInput.from_dict(model_input)
    ranked: list[dict[str, Any]] = []
    for index, candidate in enumerate(inp.candidates[: inp.max_candidates]):
        scored = _score_candidate(candidate, budget_ms=inp.rule_budget_ms)
        ranked.append(
            {
                "id": _candidate_id(candidate, index),
                "rank": 0,
                "input": candidate,
                **scored,
            }
        )
    ranked.sort(key=lambda item: (float(item["score"]), float(item["confidence"])), reverse=True)
    for index, item in enumerate(ranked):
        item["rank"] = index + 1

    top = ranked[0] if ranked else None
    runner = ranked[1] if len(ranked) > 1 else None
    top_confidence = float(top.get("confidence", 0.0)) if top else 0.0
    margin = top_confidence - (float(runner.get("confidence", 0.0)) if runner else 0.0)
    risk = risk_signal(inp.features)
    should_run_expensive_rules = (
        not top
        or risk >= 0.65
        or top_confidence < inp.confidence_threshold
        or (runner is not None and margin < inp.margin_threshold)
    )
    if not top:
        recommended_mode = "run_expensive_rules"
        reason = "no_candidates"
    elif risk >= 0.65:
        recommended_mode = "run_expensive_rules"
        reason = "high_risk_requires_rule_verification"
    elif top_confidence < inp.confidence_threshold:
        recommended_mode = "hybrid_verify_top_k"
        reason = "middle_model_confidence_below_threshold"
    elif runner is not None and margin < inp.margin_threshold:
        recommended_mode = "hybrid_verify_top_k"
        reason = "top_candidate_margin_too_small"
    else:
        recommended_mode = "small_model_shortcut"
        reason = "high_confidence_low_risk_shortcut"

    return {
        "schema": "software_middle_model_decision.v1",
        "task": inp.task,
        "model_hint": inp.model_hint,
        "backend": {
            "type": "deterministic_cpu_fallback",
            "replaceable_by": "trained_small_model",
            "heavy_compute": False,
        },
        "decision": {
            "recommended_mode": recommended_mode,
            "should_run_expensive_rules": should_run_expensive_rules,
            "selected_candidate_id": str(top.get("id", "")) if top else "",
            "confidence": round(top_confidence, 4),
            "margin": round(max(margin, 0.0), 4),
            "risk_signal": round(risk, 4),
            "reason": reason,
        },
        "ranked_candidates": ranked,
        "thresholds": {
            "confidence_threshold": inp.confidence_threshold,
            "margin_threshold": inp.margin_threshold,
            "rule_budget_ms": inp.rule_budget_ms,
            "max_candidates": inp.max_candidates,
        },
        "next_steps": [
            "log accepted/rejected shortcuts as supervised examples",
            "train a small classifier/ranker when enough labeled decisions accumulate",
            "keep expensive rules as fallback for high-risk or low-confidence cases",
        ],
    }
