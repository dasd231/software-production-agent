"""Decision schema for the software middle-layer small model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_NUMERIC_KEYS = (
    "score",
    "quality_score",
    "confidence",
    "priority",
    "historical_success_rate",
    "hit_rate",
    "precision",
    "recall",
)
_COST_KEYS = ("cost_ms", "latency_ms", "rule_cost_ms", "estimated_ms")
_RISK_KEYS = ("risk", "risk_score", "safety_risk", "blast_radius")


@dataclass(frozen=True)
class MiddleModelInput:
    """Input for ranking/shortcutting expensive rule algorithms.

    The current implementation is deterministic and CPU-only.  A trained small
    model can later consume the same fields and preserve the return contract.
    """

    task: str
    candidates: tuple[dict[str, Any], ...] = ()
    features: dict[str, Any] = field(default_factory=dict)
    confidence_threshold: float = 0.78
    margin_threshold: float = 0.12
    rule_budget_ms: int = 250
    max_candidates: int = 8
    model_hint: str = "software-middle-small-model"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MiddleModelInput":
        candidates_raw = data.get("candidates", [])
        candidates = tuple(dict(item) for item in candidates_raw if isinstance(item, dict)) if isinstance(candidates_raw, list) else ()
        features = dict(data.get("features", {})) if isinstance(data.get("features"), dict) else {}
        return cls(
            task=str(data.get("task", "") or "software_rule_acceleration"),
            candidates=candidates,
            features=features,
            confidence_threshold=_finite_float(data.get("confidence_threshold", 0.78), default=0.78, lower=0.0, upper=1.0),
            margin_threshold=_finite_float(data.get("margin_threshold", 0.12), default=0.12, lower=0.0, upper=1.0),
            rule_budget_ms=max(int(data.get("rule_budget_ms", 250) or 250), 0),
            max_candidates=max(int(data.get("max_candidates", 8) or 8), 1),
            model_hint=str(data.get("model_hint", "software-middle-small-model") or "software-middle-small-model"),
        )


def _finite_float(value: Any, *, default: float, lower: float, upper: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number < lower or number > upper:
        return default
    return number


def numeric_signal(record: dict[str, Any], keys: tuple[str, ...] = _NUMERIC_KEYS) -> float:
    """Return the strongest normalized quality-like signal in a record."""

    best = 0.0
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            number = float(value)
            if number > 1.0:
                number = number / 100.0
            best = max(best, max(0.0, min(number, 1.0)))
    return best


def cost_signal(record: dict[str, Any], *, budget_ms: int) -> float:
    """Normalize candidate cost into 0..1 where 1 means too expensive."""

    budget = max(float(budget_ms), 1.0)
    raw = 0.0
    for key in _COST_KEYS:
        value = record.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            raw = max(raw, float(value))
    return max(0.0, min(raw / budget, 1.0))


def risk_signal(features: dict[str, Any]) -> float:
    """Estimate whether expensive rules should still verify the decision."""

    if bool(features.get("safety_critical") or features.get("requires_exactness") or features.get("security_sensitive")):
        return 1.0
    best = 0.0
    for key in _RISK_KEYS:
        value = features.get(key)
        if isinstance(value, str):
            lowered = value.lower()
            if lowered in {"high", "critical", "unsafe"}:
                best = max(best, 1.0)
            elif lowered in {"medium", "moderate"}:
                best = max(best, 0.55)
            elif lowered in {"low", "safe"}:
                best = max(best, 0.15)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            number = float(value)
            if number > 1.0:
                number = number / 100.0
            best = max(best, max(0.0, min(number, 1.0)))
    return best
