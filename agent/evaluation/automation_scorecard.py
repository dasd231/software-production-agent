"""Automation scorecard for competition / paper / hiring scrutiny.

The goal is not to produce flattering metrics. The scorecard makes denominator
rules, evidence requirements and death thresholds explicit so the system can
survive adversarial review instead of optimizing vanity numbers.
"""

from __future__ import annotations

from typing import Any


def _metric(
    dimension: str,
    name: str,
    claim_risk: str,
    required_evidence: list[str],
    death_threshold: str,
    denominator_rule: str = "all_entered_demands",
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "name": name,
        "claim_risk": claim_risk,
        "required_evidence": required_evidence,
        "death_threshold": death_threshold,
        "denominator_rule": denominator_rule,
    }


def build_automation_scorecard(
    *,
    demand_count: int = 10,
    observation_days: int = 30,
    include_agent_failures: bool = True,
    third_party_review: bool = True,
) -> dict[str, Any]:
    metrics = [
        _metric(
            "delivery_efficiency",
            "demand_turnaround_time",
            "mixing simple CRUD and complex distributed tasks hides failure",
            ["P0-P3 complexity-bucketed DTR distribution", "manual-transfer list with reasons"],
            "complex P2/P3 DTR > 3 days without bucket explanation",
        ),
        _metric(
            "delivery_efficiency",
            "first_pass_ci_rate",
            "CI may only mean compile, not business correctness",
            ["CI definition including unit tests + type check + lint", "random failed-sample analysis"],
            "< 30% or CI excludes tests",
        ),
        _metric(
            "delivery_efficiency",
            "loop_count",
            "human silent fixes can hide Agent loops",
            ["per-loop diff", "actor attribution", "termination decision log"],
            "median > 3 loops",
        ),
        _metric(
            "output_quality",
            "defect_escape_rate",
            "short observation windows make zero-defect claims meaningless",
            [f"production defect attribution over >= {observation_days} days", "Agent-authored code denominator"],
            "observation << 7 days or denominator excludes Agent code",
        ),
        _metric(
            "output_quality",
            "test_coverage_delta",
            "Agent-written tests can be self-grading",
            ["coverage diff", ">=10% blind human review of assertion usefulness"],
            "invalid-test rate > 20%",
        ),
        _metric(
            "chain_reliability",
            "end_to_end_success_rate",
            "hard tasks may be routed to humans and vanish from denominator",
            ["full demand funnel: entered -> attempted -> failed -> manual/terminated"],
            "manual-transfer rate > 30% without explanation",
        ),
        _metric(
            "chain_reliability",
            "hallucination_pollution_rate",
            "runtime hallucinations may not appear at compile time",
            ["undeclared dependency import counts", "runtime stack traces caused by hallucinated API"],
            "runtime hallucination not measured",
        ),
        _metric(
            "cost_benefit",
            "per_demand_total_cost",
            "token/GPU/human review/context switching/rework can be omitted",
            ["token cost", "GPU cost", "human review time", "context switching", "rework cost"],
            "hidden costs omitted",
        ),
        _metric(
            "observability_control",
            "decision_traceability",
            "self-generated citations are not evidence",
            ["query -> retrieval -> citation -> final decision trace", "human-verifiable citations"],
            "citations point to Agent-generated content only",
        ),
        _metric(
            "observability_control",
            "human_intervention_depth",
            "a click-confirm and core rewrite are both counted as intervention",
            ["L1 confirmation / L2 patch / L3 rewrite distribution", "time spent by tier"],
            "L3 rewrite share > 15%",
        ),
        _metric(
            "knowledge_assets",
            "solution_reuse_rate",
            "retrieval hit may mean stale copy-paste",
            ["asset age distribution", "validity checks", "defect attribution after reuse"],
            "no expiry/validity management",
        ),
        _metric(
            "north_star",
            "effective_automation_rate",
            "automation may only cover trivial templates",
            ["complexity-bucketed automation rate", "P2/P3 unattended share"],
            "only P0 automated and P2+ is zero",
        ),
    ]
    anti_cheat = [
        {
            "name": "denominator_integrity",
            "required": include_agent_failures,
            "rule": "all rates include tasks the Agent failed and transferred to humans",
        },
        {
            "name": "test_validity_review",
            "required": third_party_review,
            "rule": "Agent-authored tests require third-party blind usefulness review",
        },
        {
            "name": "full_cost_accounting",
            "required": True,
            "rule": "cost includes token + compute + human review + context switching + rework",
        },
    ]
    return {
        "schema": "automation_scorecard.v1",
        "experiment": {
            "minimum_real_demands": max(1, int(demand_count)),
            "observation_days": max(1, int(observation_days)),
            "recording_required": True,
            "complexity_buckets": ["P0_template", "P1_local_feature", "P2_cross_module", "P3_distributed_or_data"],
            "comparison_baseline": "same demand pool, comparable engineer level, blind third-party review",
        },
        "metrics": metrics,
        "anti_cheat_rules": anti_cheat,
        "evidence_artifacts": [
            ".agent_events.jsonl",
            "CI logs",
            "git diffs with actor attribution",
            "production defect tracker",
            "cost ledger",
            "human blind-review sheet",
            "solution-library reuse ledger",
        ],
        "release_gate": {
            "paper_ready": "scorecard has >=10 real demands, >=30 observation days, and no anti-cheat failure",
            "competition_demo_ready": "scorecard has recorded traces and at least one P2/P3 successful demand",
            "hiring_ready": "candidate can explain failed cases and denominator rules, not just wins",
        },
    }


def evaluate_scorecard_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a sparse evidence payload against anti-cheat gates."""

    findings: list[dict[str, str]] = []
    if not bool(evidence.get("includes_agent_failures", False)):
        findings.append(
            {
                "severity": "error",
                "code": "survivorship_bias",
                "message": "Rates exclude Agent failures/transfers; denominator is invalid.",
            }
        )
    if not bool(evidence.get("ci_includes_tests", False)):
        findings.append(
            {
                "severity": "error",
                "code": "weak_ci_definition",
                "message": "First-pass CI rate is invalid unless CI includes tests.",
            }
        )
    if not bool(evidence.get("third_party_test_review", False)):
        findings.append(
            {
                "severity": "warning",
                "code": "self_graded_tests",
                "message": "Agent-authored tests need blind usefulness review.",
            }
        )
    if not bool(evidence.get("cost_includes_human_review", False)):
        findings.append(
            {
                "severity": "warning",
                "code": "hidden_human_cost",
                "message": "Cost model omits human review/context-switching cost.",
            }
        )
    try:
        transfer_rate = float(evidence.get("manual_transfer_rate", 0.0) or 0.0)
    except (TypeError, ValueError):
        transfer_rate = 0.0
    if transfer_rate > 0.30:
        findings.append(
            {
                "severity": "warning",
                "code": "high_manual_transfer_rate",
                "message": "Manual transfer rate exceeds 30%; explain complexity distribution.",
            }
        )
    try:
        l3_rewrite_rate = float(evidence.get("l3_rewrite_rate", 0.0) or 0.0)
    except (TypeError, ValueError):
        l3_rewrite_rate = 0.0
    if l3_rewrite_rate > 0.15:
        findings.append(
            {
                "severity": "error",
                "code": "core_rewrite_dependency",
                "message": "L3 rewrite share exceeds 15%; claimed automation is not effective.",
            }
        )
    return {
        "schema": "automation_scorecard_evidence_review.v1",
        "ok": not any(item["severity"] == "error" for item in findings),
        "findings": findings,
    }

