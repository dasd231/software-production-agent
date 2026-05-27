from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.evaluation.automation_scorecard import build_automation_scorecard, evaluate_scorecard_evidence


def test_automation_scorecard_contains_adversarial_metrics_and_anti_cheat_rules() -> None:
    scorecard = build_automation_scorecard(demand_count=12, observation_days=45)

    assert scorecard["experiment"]["minimum_real_demands"] == 12
    assert scorecard["experiment"]["observation_days"] == 45
    names = {metric["name"] for metric in scorecard["metrics"]}
    assert {"demand_turnaround_time", "first_pass_ci_rate", "effective_automation_rate"} <= names
    anti_cheat = {item["name"] for item in scorecard["anti_cheat_rules"]}
    assert {"denominator_integrity", "test_validity_review", "full_cost_accounting"} <= anti_cheat


def test_scorecard_evidence_review_flags_denominator_and_rewrite_failures() -> None:
    review = evaluate_scorecard_evidence(
        {
            "includes_agent_failures": False,
            "ci_includes_tests": False,
            "third_party_test_review": False,
            "cost_includes_human_review": False,
            "manual_transfer_rate": 0.4,
            "l3_rewrite_rate": 0.2,
        }
    )

    assert review["ok"] is False
    codes = {finding["code"] for finding in review["findings"]}
    assert {"survivorship_bias", "weak_ci_definition", "core_rewrite_dependency"} <= codes


def test_automation_scorecard_action_writes_file_and_respects_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"automation_scorecard_plan","args":'
        '{"demand_count":10,"observation_days":30,"output_path":"plans/scorecard.json"}}'
    )
    result = run_action(tmp_path, action)
    assert result["ok"] is True
    assert result["summary"]["metric_count"] >= 10
    assert (tmp_path / "plans" / "scorecard.json").exists()

    denied = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "PERMISSION_DENIED"

    allowed = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"evaluation:plan", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"

