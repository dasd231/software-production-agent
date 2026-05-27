from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_DEFAULT_THRESHOLDS = {
    "middle_model": {"min_examples": 50, "min_accuracy": 0.72, "max_shortcut_escape_rate": 0.05},
    "github_evaluator": {"min_examples": 80, "min_accuracy": 0.7, "min_license_pass_rate": 0.98},
}


def build_training_quality_plan() -> dict[str, Any]:
    """Quality and promotion plan for the two local/server small models."""

    return {
        "schema": "model_training_quality_plan.v1",
        "principle": "No model is promoted because it trained successfully; it is promoted only when labels, gates, drift monitors, and rollback evidence are present.",
        "models": [
            {
                "target": "middle_model_rule_acceleration",
                "purpose": "Predict when expensive rule/search/graph algorithms can be safely skipped or must run.",
                "training_source": "accepted/rejected workflow traces + human satisfaction + quality_delta + latency_saved_ms",
                "label_contract": "1 means run expensive rules; 0 means shortcut is allowed",
                "hard_gates": [
                    "high-risk or security-sensitive actions always execute rule fallback",
                    "shortcut is forbidden when must_have NeedSlot coverage is weak",
                    "quality_delta must be non-negative on accepted shortcuts",
                ],
                "metrics": ["accuracy", "false_skip_rate", "latency_saved_ms", "quality_delta", "human_override_rate"],
                "promotion": ["local_cpu_baseline", "shadow_inference", "limited_shortcut", "server_distillation_or_lora", "canary", "rollback_ready"],
            },
            {
                "target": "github_corpus_quality_evaluator",
                "purpose": "Score GitHub repositories for crawl, PatternCard extraction, distillation pool, or quarantine.",
                "training_source": "GitHub crawl metadata + license/governance checks + downstream retrieval usefulness labels",
                "label_contract": "1 means train_now/distill_pool; 0 means observe/quarantine",
                "hard_gates": [
                    "license/governance failure cannot be overridden by popularity score",
                    "repository must pass malware/secret scanning before training route",
                    "downstream utility must be measured on held-out software-production tasks",
                ],
                "metrics": ["precision_at_train_now", "bad_repo_leak_rate", "novelty", "coverage_gain", "license_pass_rate"],
                "promotion": ["local_cpu_baseline", "offline_ranking_eval", "crawl_shadow_route", "human_spot_check", "server_batch_training", "rollback_ready"],
            },
        ],
        "dataset_quality": {
            "required_splits": ["train", "validation", "holdout_by_domain", "recent_time_slice"],
            "anti_leakage": [
                "repositories from the same org cannot straddle train and holdout when evaluating generalization",
                "Agent-generated tests cannot be the only quality label",
                "human satisfaction is positive feedback but not equal to correctness for risky changes",
            ],
            "minimum_evidence": [
                "raw trace or repo id",
                "features used by model",
                "label source",
                "timestamp",
                "license/governance status for corpus rows",
                "coverage/report id for semantic retrieval rows",
            ],
        },
        "online_quality_loop": [
            "every inference writes feature vector + decision + fallback result",
            "low-confidence decisions are sampled for human review",
            "model drift is checked by domain, tech_stack, and task complexity bucket",
            "promotion requires rollback artifact and previous model comparison",
        ],
        "thresholds": _DEFAULT_THRESHOLDS,
    }


def evaluate_training_quality(manifest: Mapping[str, Any], thresholds: Mapping[str, Mapping[str, float]] | None = None) -> dict[str, Any]:
    thresholds = thresholds or _DEFAULT_THRESHOLDS
    results = manifest.get("results", {}) if isinstance(manifest.get("results"), Mapping) else {}
    evaluations: dict[str, Any] = {}
    overall_ok = True
    for model_key in ("middle_model", "github_evaluator"):
        model = results.get(model_key, {}) if isinstance(results.get(model_key), Mapping) else {}
        metrics = model.get("metrics", {}) if isinstance(model.get("metrics"), Mapping) else {}
        min_examples = float(thresholds.get(model_key, {}).get("min_examples", 0))
        min_accuracy = float(thresholds.get(model_key, {}).get("min_accuracy", 0))
        examples = float(model.get("training_examples", metrics.get("example_count", 0)) or 0)
        accuracy = float(metrics.get("accuracy", 0) or 0)
        status = str(model.get("status", "missing"))
        reasons: list[str] = []
        if status != "trained":
            reasons.append(f"status={status}")
        if examples < min_examples:
            reasons.append(f"training_examples {examples:g} < {min_examples:g}")
        if accuracy < min_accuracy:
            reasons.append(f"accuracy {accuracy:.3f} < {min_accuracy:.3f}")
        ok = not reasons
        overall_ok = overall_ok and ok
        evaluations[model_key] = {
            "ok": ok,
            "status": "promotable" if ok else "blocked",
            "training_examples": examples,
            "accuracy": accuracy,
            "reasons": reasons,
        }
    return {
        "schema": "model_training_quality_evaluation.v1",
        "ok": overall_ok,
        "evaluations": evaluations,
        "next_steps": [
            "collect labels until minimum examples are satisfied",
            "run holdout evaluation by domain and tech stack",
            "only enable server training after hard gates pass locally",
        ]
        if not overall_ok
        else ["eligible for shadow inference", "prepare rollback artifact", "compare against previous model"],
    }
