from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from agent.local_training.feature_extraction import extract_github_features, extract_middle_features
from agent.local_training.schemas import LocalPrediction, resolve_artifact_path


def _sigmoid(value: float) -> float:
    if value >= 40:
        return 1.0
    if value <= -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def load_local_model(path_or_dir: Path, *, target: str) -> dict[str, Any]:
    filename = "middle_model_local.json" if target in {"middle", "middle_model"} else "github_evaluator_local.json"
    path = resolve_artifact_path(path_or_dir, filename)
    return json.loads(path.read_text(encoding="utf-8"))


def predict_probability(model: dict[str, Any], features: dict[str, float]) -> float:
    names = tuple(str(name) for name in model.get("feature_names", []))
    weights = model.get("weights") if isinstance(model.get("weights"), dict) else {}
    bias = float(model.get("bias", 0.0) or 0.0)
    z = bias + sum(float(weights.get(name, 0.0) or 0.0) * float(features.get(name, 0.0) or 0.0) for name in names)
    return _sigmoid(z)


def _risk_hard_gates(features: dict[str, float], row: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if features.get("risk_signal", 0.0) >= 0.8 or features.get("patch_risk", 0.0) >= 0.8:
        reasons.append("high_risk_forces_expensive_rules")
    if features.get("must_have_coverage", 1.0) < 0.8:
        reasons.append("weak_must_have_coverage_forces_expensive_rules")
    if features.get("guard_violation_rate", 0.0) > 0.0:
        reasons.append("guard_violation_forces_expensive_rules")
    text = json.dumps(row, ensure_ascii=False).lower()
    if any(token in text for token in ("secret", "password", "auth", "payment", "delete", "deploy")):
        reasons.append("sensitive_surface_forces_expensive_rules")
    return bool(reasons), tuple(reasons)


def classify_middle_decision(model: dict[str, Any], trace: dict[str, Any], *, threshold: float | None = None) -> dict[str, Any]:
    features = extract_middle_features(trace)
    hard, reasons = _risk_hard_gates(features, trace)
    use_threshold = float(threshold if threshold is not None else model.get("threshold", 0.5) or 0.5)
    prob = predict_probability(model, features)
    label = int(prob >= use_threshold or hard)
    decision = "run_expensive_rules" if label else "shortcut_allowed"
    return LocalPrediction(
        target="middle_model_rule_acceleration",
        probability=round(prob, 6),
        label=label,
        threshold=use_threshold,
        decision=decision,
        features=features,
        hard_gate_triggered=hard,
        hard_gate_reasons=reasons,
    ).to_dict()


def _github_hard_gates(row: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    checks = row.get("checks") if isinstance(row.get("checks"), dict) else {}
    reasons: list[str] = []
    if checks.get("license_ok") is False:
        reasons.append("license_failure_forces_quarantine")
    if checks.get("secret_scan_passed") is False:
        reasons.append("secret_scan_failure_forces_quarantine")
    if checks.get("malware_scan_passed") is False:
        reasons.append("malware_scan_failure_forces_quarantine")
    return bool(reasons), tuple(reasons)


def score_github_repo(model: dict[str, Any], row: dict[str, Any], *, threshold: float | None = None) -> dict[str, Any]:
    features = extract_github_features(row)
    hard, reasons = _github_hard_gates(row)
    use_threshold = float(threshold if threshold is not None else model.get("threshold", 0.5) or 0.5)
    prob = predict_probability(model, features)
    label = int(prob >= use_threshold and not hard)
    decision = "train_now_or_distill_pool" if label else "observe_or_quarantine"
    return LocalPrediction(
        target="github_corpus_quality_evaluator",
        probability=round(prob, 6),
        label=label,
        threshold=use_threshold,
        decision=decision,
        features=features,
        hard_gate_triggered=hard,
        hard_gate_reasons=reasons,
    ).to_dict()
