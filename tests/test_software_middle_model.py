from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, run_action, run_action_guarded
from agent.core.protocol import parse_and_validate_action_line
from agent.software_middle_model import MiddleModelInput, build_software_middle_model_plan, decide_with_middle_model


def test_software_middle_model_plan_is_cpu_first_and_independent() -> None:
    plan = build_software_middle_model_plan()

    assert plan["schema"] == "software_middle_model_plan.v1"
    assert plan["safety_policy"]["default_backend"] == "deterministic_cpu_fallback"
    assert "does not launch GPU training by default" in plan["positioning"]["non_goals"]
    assert plan["interfaces"]["decision_action"] == "software_middle_model_decide"


def test_middle_model_shortcuts_high_confidence_low_risk_candidates() -> None:
    decision = decide_with_middle_model(
        MiddleModelInput(
            task="evidence_selection",
            features={"risk": "low"},
            candidates=(
                {"id": "fast_good", "quality_score": 0.94, "rule_cost_ms": 20},
                {"id": "slow_weaker", "quality_score": 0.70, "rule_cost_ms": 500},
            ),
            confidence_threshold=0.78,
            margin_threshold=0.12,
            rule_budget_ms=250,
        )
    )

    assert decision["schema"] == "software_middle_model_decision.v1"
    assert decision["decision"]["recommended_mode"] == "small_model_shortcut"
    assert decision["decision"]["should_run_expensive_rules"] is False
    assert decision["decision"]["selected_candidate_id"] == "fast_good"
    assert decision["ranked_candidates"][0]["id"] == "fast_good"


def test_middle_model_falls_back_for_high_risk_tasks() -> None:
    decision = decide_with_middle_model(
        {
            "task": "security_sensitive_rule",
            "features": {"security_sensitive": True},
            "candidates": [{"id": "apparently_good", "quality_score": 0.99, "rule_cost_ms": 10}],
        }
    )

    assert decision["decision"]["recommended_mode"] == "run_expensive_rules"
    assert decision["decision"]["should_run_expensive_rules"] is True
    assert decision["decision"]["reason"] == "high_risk_requires_rule_verification"


def test_software_middle_model_actions_dispatch(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    plan = run_action(ws, {"type": "action", "action": "software_middle_model_plan", "args": {}})
    decision = run_action(
        ws,
        {
            "type": "action",
            "action": "software_middle_model_decide",
            "args": {
                "task": "repo_routing",
                "features": {"risk": "low"},
                "candidates": [
                    {"id": "train_now", "quality_score": 0.9, "rule_cost_ms": 25},
                    {"id": "manual_review", "quality_score": 0.66, "rule_cost_ms": 400},
                ],
            },
        },
    )

    assert plan["ok"] is True
    assert plan["plan"]["schema"] == "software_middle_model_plan.v1"
    assert decision["ok"] is True
    assert decision["decision"]["decision"]["selected_candidate_id"] == "train_now"


def test_software_middle_model_protocol_and_guarded_permissions(tmp_path: Path) -> None:
    parsed = parse_and_validate_action_line(
        '{"type":"action","action":"software_middle_model_decide","args":{"task":"x","candidates":[]}}'
    )
    assert parsed["action"] == "software_middle_model_decide"

    ws = tmp_path / "ws"
    ws.mkdir()
    allowed = run_action_guarded(
        ws,
        {"type": "action", "action": "software_middle_model_plan", "args": {}},
        limits=ExecutionLimits(granted_permissions=frozenset({"model:read"})),
    )
    blocked = run_action_guarded(
        ws,
        {"type": "action", "action": "software_middle_model_decide", "args": {"task": "x", "candidates": []}},
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )

    assert allowed["ok"] is True
    assert blocked["ok"] is False
    assert blocked["error_code"] == "PERMISSION_DENIED"
