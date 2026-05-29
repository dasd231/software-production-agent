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


def _rate(numerator: float, denominator: float) -> float:
    return round(float(numerator) / max(float(denominator), 1.0), 4)


def build_training_scorecard(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Build an interview/audit-friendly scorecard for local small-model runs.

    The scorecard intentionally separates "trained" from "promotable". A small
    model can train successfully while still being blocked by sample size,
    validation gap, false-shortcut risk, or governance leakage.
    """

    results = manifest.get("results", {}) if isinstance(manifest.get("results"), Mapping) else {}
    quality = manifest.get("quality_evaluation", {}) if isinstance(manifest.get("quality_evaluation"), Mapping) else {}
    rows: list[dict[str, Any]] = []
    for key, target in (
        ("middle_model", "middle_model_rule_acceleration"),
        ("github_evaluator", "github_corpus_quality_evaluator"),
    ):
        model = results.get(key, {}) if isinstance(results.get(key), Mapping) else {}
        metrics = model.get("metrics", {}) if isinstance(model.get("metrics"), Mapping) else {}
        validation = (
            model.get("validation_metrics", {})
            if isinstance(model.get("validation_metrics"), Mapping)
            else {}
        )
        confusion = metrics.get("confusion", {}) if isinstance(metrics.get("confusion"), Mapping) else {}
        validation_confusion = (
            validation.get("confusion", {})
            if isinstance(validation.get("confusion"), Mapping)
            else {}
        )
        accuracy = float(metrics.get("accuracy", 0) or 0)
        validation_accuracy = float(validation.get("accuracy", 0) or 0)
        validation_gap = round(max(accuracy - validation_accuracy, 0.0), 4)
        if key == "middle_model":
            # label 1 = must run expensive rules; FN means model would shortcut
            # when deterministic rules were actually required.
            critical_error_rate = _rate(confusion.get("fn", 0), sum(confusion.values()))
            critical_name = "false_shortcut_rate"
        else:
            # label 1 = can train/distill; FP means a bad repo leaks into train.
            critical_error_rate = _rate(confusion.get("fp", 0), sum(confusion.values()))
            critical_name = "bad_repo_leak_rate"
        quality_row = (
            quality.get("evaluations", {}).get(key, {})
            if isinstance(quality.get("evaluations"), Mapping)
            else {}
        )
        blocked_reasons = list(quality_row.get("reasons", [])) if isinstance(quality_row.get("reasons"), list) else []
        if validation_gap > 0.15:
            blocked_reasons.append(f"validation_gap {validation_gap:.3f} > 0.150")
        if key == "middle_model" and critical_error_rate > 0.05:
            blocked_reasons.append(f"{critical_name} {critical_error_rate:.3f} > 0.050")
        if key == "github_evaluator" and critical_error_rate > 0.03:
            blocked_reasons.append(f"{critical_name} {critical_error_rate:.3f} > 0.030")

        rows.append(
            {
                "model_key": key,
                "target": target,
                "status": model.get("status", "missing"),
                "training_examples": int(model.get("training_examples", metrics.get("example_count", 0)) or 0),
                "train_accuracy": accuracy,
                "validation_accuracy": validation_accuracy,
                "validation_gap": validation_gap,
                critical_name: critical_error_rate,
                "train_confusion": dict(confusion),
                "validation_confusion": dict(validation_confusion),
                "promotion_gate": "shadow_only" if blocked_reasons else "candidate_for_shadow_or_canary",
                "blocked_reasons": blocked_reasons,
            }
        )

    overall_blocked = [reason for row in rows for reason in row["blocked_reasons"]]
    return {
        "schema": "local_training_scorecard.v1",
        "overall_gate": "blocked" if overall_blocked else "candidate",
        "models": rows,
        "server_training_readiness": {
            "sft_export_allowed": True,
            "server_lora_allowed": not overall_blocked,
            "hard_gates_remain_rule_based": True,
            "required_before_promotion": [
                "holdout_by_domain",
                "recent_time_slice",
                "shadow_inference_log",
                "rollback_artifact",
                "human_spot_check",
            ],
        },
    }
