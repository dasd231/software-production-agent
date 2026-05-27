from __future__ import annotations

import hashlib
import math
from typing import Any

MIDDLE_FEATURES = (
    "confidence",
    "margin",
    "risk_signal",
    "candidate_count",
    "latency_saved_ms",
    "quality_delta",
    "must_have_coverage",
    "guard_violation_rate",
    "patch_risk",
    "human_override_signal",
)

GITHUB_FEATURES = (
    "lexical_relevance",
    "repo_quality",
    "freshness",
    "governance",
    "novelty",
    "downstream_utility",
    "test_signal",
    "ci_signal",
    "license_signal",
    "architecture_depth",
    "security_signal",
)

_RISK_MAP = {
    "none": 0.0,
    "safe": 0.05,
    "low": 0.15,
    "medium": 0.55,
    "high": 0.85,
    "critical": 1.0,
}

_LABEL_POSITIVE = {"good", "train", "train_now", "accept", "accepted", "yes", "true", "1", "promote"}
_LABEL_NEGATIVE = {"bad", "reject", "rejected", "quarantine", "no", "false", "0", "block"}


def stable_id(prefix: str, payload: Any) -> str:
    text = repr(payload).encode("utf-8", errors="ignore")
    return f"{prefix}_{hashlib.sha1(text).hexdigest()[:12]}"


def bounded(value: Any, *, default: float = 0.0, upper: float = 1.0) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, str):
        mapped = _RISK_MAP.get(value.strip().lower())
        if mapped is not None:
            return mapped
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    if upper <= 1.0 and number > upper:
        number = number / 100.0
    return max(0.0, min(number, upper))


def signed_unit(value: Any, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(-1.0, min(number, 1.0))


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def extract_middle_features(trace: dict[str, Any]) -> dict[str, float]:
    """Feature contract for the rule-acceleration model.

    Label meaning is handled separately: 1 means the expensive deterministic
    rule/search/graph path must run; 0 means a shortcut may be allowed.
    """

    decision = _first_mapping(trace.get("decision"), trace.get("middle_model_decision"))
    labels = _first_mapping(trace.get("labels"), trace.get("human_labels"))
    features = _first_mapping(trace.get("features"), trace.get("metrics"))
    coverage = _first_mapping(trace.get("coverage_report"), features.get("coverage_report"))
    guard = _first_mapping(trace.get("guard_report"), features.get("guard_report"))
    patch = _first_mapping(trace.get("patch_proposal"), features.get("patch_proposal"))
    ranked = trace.get("ranked_candidates") if isinstance(trace.get("ranked_candidates"), list) else []

    violations = guard.get("violations") if isinstance(guard.get("violations"), list) else []
    risk_value = decision.get("risk_signal", features.get("risk_signal", features.get("risk_score", features.get("risk"))))
    patch_risk = patch.get("risk_score", patch.get("risk_level", features.get("patch_risk", 0.0)))

    return {
        "confidence": bounded(decision.get("confidence"), upper=1.0),
        "margin": bounded(decision.get("margin"), upper=1.0),
        "risk_signal": bounded(risk_value, upper=1.0),
        "candidate_count": min(len(ranked) / 8.0, 1.0),
        "latency_saved_ms": min(bounded(labels.get("latency_saved_ms"), upper=10000.0) / 1000.0, 1.0),
        "quality_delta": signed_unit(labels.get("quality_delta", 0.0)),
        "must_have_coverage": bounded(coverage.get("must_have_coverage_rate", coverage.get("must_have", 0.0)), upper=1.0),
        "guard_violation_rate": min(len(violations) / 5.0, 1.0),
        "patch_risk": bounded(patch_risk, upper=1.0),
        "human_override_signal": bounded(labels.get("human_override", labels.get("human_override_signal", False)), upper=1.0),
    }


def extract_middle_label(trace: dict[str, Any]) -> tuple[int, str] | None:
    decision = _first_mapping(trace.get("decision"), trace.get("middle_model_decision"))
    labels = _first_mapping(trace.get("labels"), trace.get("human_labels"))
    guard = _first_mapping(trace.get("guard_report"))
    coverage = _first_mapping(trace.get("coverage_report"))

    if labels.get("shortcut_success") is False:
        return 1, "shortcut_failed"
    if labels.get("human_override") is True:
        return 1, "human_override"
    if labels.get("final_accepted") is False:
        return 1, "rejected_outcome"
    if guard.get("ok") is False:
        return 1, "guard_violation"
    if coverage.get("has_missing_must_have") is True:
        return 1, "missing_must_have"
    should_run = labels.get("should_run_expensive_rules", decision.get("should_run_expensive_rules"))
    if isinstance(should_run, bool):
        return int(should_run), "explicit_should_run_expensive_rules"
    return None


def extract_github_features(row: dict[str, Any]) -> dict[str, float]:
    scores = row.get("scores") if isinstance(row.get("scores"), dict) else row
    checks = row.get("checks") if isinstance(row.get("checks"), dict) else {}
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}

    def score(name: str) -> float:
        return bounded(scores.get(name), upper=10.0) / 10.0

    has_tests = checks.get("has_tests", metadata.get("has_tests", scores.get("test_signal", False)))
    has_ci = checks.get("has_ci", metadata.get("has_ci", scores.get("ci_signal", False)))
    license_ok = checks.get("license_ok", metadata.get("license_ok", scores.get("license_signal", False)))
    security = scores.get("security_signal", checks.get("secret_scan_passed", metadata.get("security_signal", 0.0)))

    return {
        "lexical_relevance": score("lexical_relevance"),
        "repo_quality": score("repo_quality"),
        "freshness": score("freshness"),
        "governance": score("governance"),
        "novelty": score("novelty"),
        "downstream_utility": score("downstream_utility"),
        "test_signal": bounded(has_tests, upper=1.0),
        "ci_signal": bounded(has_ci, upper=1.0),
        "license_signal": bounded(license_ok, upper=1.0),
        "architecture_depth": score("architecture_depth"),
        "security_signal": bounded(security, upper=1.0),
    }


def extract_github_label(row: dict[str, Any]) -> tuple[int, str]:
    routes = {str(route).strip().lower() for route in row.get("routes", []) if str(route).strip()}
    raw_label = str(row.get("label", "")).strip().lower()
    checks = row.get("checks") if isinstance(row.get("checks"), dict) else {}
    if checks.get("license_ok") is False or checks.get("secret_scan_passed") is False:
        return 0, "hard_gate_governance_or_security"
    if "train_now" in routes or "distill_pool" in routes or raw_label in _LABEL_POSITIVE:
        return 1, "explicit_positive_route"
    if "quarantine" in routes or "reject" in routes or raw_label in _LABEL_NEGATIVE:
        return 0, "explicit_negative_route"
    score = bounded(row.get("score", row.get("total_score", 0.0)), upper=10.0)
    return int(score >= 7.0), "score_threshold"
