"""Program plan for the software middle-layer small model."""

from __future__ import annotations

from typing import Any


def build_software_middle_model_plan(target: str = "rule_acceleration") -> dict[str, Any]:
    """Return an implementation roadmap for the independent middle model module."""

    return {
        "schema": "software_middle_model_plan.v1",
        "target": target,
        "positioning": {
            "name": "Software Middle-Layer Small Model",
            "purpose": "learn to prioritize or shortcut expensive rule algorithms in software-production workflows",
            "non_goals": [
                "does not replace safety-critical verification rules",
                "does not launch GPU training by default",
                "does not couple directly to a single LLM provider",
            ],
        },
        "interfaces": {
            "plan_action": "software_middle_model_plan",
            "decision_action": "software_middle_model_decide",
            "python_api": "agent.software_middle_model.decide_with_middle_model",
            "input_contract": {
                "task": "string",
                "features": "object with task/risk/context signals",
                "candidates": "array of candidate rules/routes/actions with score/cost metadata",
                "confidence_threshold": "0..1 shortcut threshold",
                "rule_budget_ms": "budget used to normalize expensive-rule latency",
            },
            "output_contract": {
                "decision": "recommended_mode, should_run_expensive_rules, selected_candidate_id, confidence, reason",
                "ranked_candidates": "stable ranked list for downstream inspection",
                "backend": "current fallback or future small-model backend metadata",
            },
        },
        "training_loop": {
            "data_sources": [
                "rule execution traces",
                "accepted/rejected shortcut decisions",
                "latency and cost measurements",
                "user satisfaction on final outcomes",
                "benchmark failures requiring full rule verification",
            ],
            "labels": [
                "selected_candidate_id",
                "should_run_expensive_rules",
                "shortcut_success",
                "latency_saved_ms",
                "quality_delta",
            ],
            "first_models": [
                "logistic regression / linear ranker",
                "LightGBM-style tabular ranker",
                "tiny transformer over normalized decision records",
            ],
        },
        "safety_policy": {
            "default_backend": "deterministic_cpu_fallback",
            "fallback": "run_expensive_rules",
            "high_risk_features": ["safety_critical", "security_sensitive", "requires_exactness", "risk=high"],
            "audit": "always emit confidence, margin, reason, and ranked candidates",
        },
        "integration_points": [
            "research evidence selection",
            "GitHub corpus candidate routing",
            "project benchmark triage",
            "model routing/admission pre-checks",
            "slow rule chains where exact verification can be deferred",
        ],
        "milestones": [
            {"id": "m0", "name": "interface scaffold", "status": "done_in_this_module"},
            {"id": "m1", "name": "trace collection", "status": "next"},
            {"id": "m2", "name": "offline small-model training", "status": "planned"},
            {"id": "m3", "name": "shadow-mode evaluation", "status": "planned"},
            {"id": "m4", "name": "guarded online shortcut", "status": "planned"},
        ],
    }
