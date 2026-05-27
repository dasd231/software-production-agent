from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent.workflow.optimizer import WorkflowOptimizationReport


@dataclass(slots=True)
class CanaryGuardrail:
    metric: str
    operator: str
    threshold: float
    action: str
    reason: str


@dataclass(slots=True)
class CanaryPlan:
    candidate_policy_version: str
    initial_traffic_percent: float
    max_traffic_percent: float
    promotion_steps: list[float]
    guardrails: list[CanaryGuardrail] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_policy_version": self.candidate_policy_version,
            "initial_traffic_percent": self.initial_traffic_percent,
            "max_traffic_percent": self.max_traffic_percent,
            "promotion_steps": self.promotion_steps,
            "guardrails": [asdict(item) for item in self.guardrails],
            "notes": self.notes,
        }


def build_canary_plan(
    report: WorkflowOptimizationReport,
    *,
    candidate_policy_version: str,
) -> CanaryPlan:
    """Build a conservative rollout plan for an optimized workflow policy.

    Workflow self-optimization is risky: a policy can overfit small traces or amplify
    bad feedback. The default plan therefore starts tiny and promotes only if quality,
    error, and latency guardrails hold.
    """

    high_findings = [finding for finding in report.findings if finding.severity == "high"]
    medium_findings = [finding for finding in report.findings if finding.severity == "medium"]
    if high_findings:
        initial = 2.0
        max_traffic = 20.0
        notes = ["High-risk findings detected; start with shadow or tiny canary traffic."]
    elif medium_findings:
        initial = 5.0
        max_traffic = 40.0
        notes = ["Medium route differences detected; use guarded canary before promotion."]
    else:
        initial = 10.0
        max_traffic = 50.0
        notes = ["No serious findings; still avoid direct full rollout for adaptive policies."]

    guardrails = [
        CanaryGuardrail(
            metric="workflow_success_rate_delta",
            operator=">=",
            threshold=-0.02,
            action="rollback",
            reason="candidate must not reduce success rate by more than 2 percentage points",
        ),
        CanaryGuardrail(
            metric="avg_reward_delta",
            operator=">=",
            threshold=-0.05,
            action="rollback",
            reason="reward regression means the optimizer may be overfitting or mis-scored",
        ),
        CanaryGuardrail(
            metric="p95_latency_delta_percent",
            operator="<=",
            threshold=20.0,
            action="pause",
            reason="adaptive route must not cause unacceptable latency expansion",
        ),
        CanaryGuardrail(
            metric="human_interrupt_rate_delta_percent",
            operator="<=",
            threshold=10.0,
            action="pause",
            reason="too many human gates indicates low confidence routing",
        ),
    ]
    return CanaryPlan(
        candidate_policy_version=candidate_policy_version,
        initial_traffic_percent=initial,
        max_traffic_percent=max_traffic,
        promotion_steps=[initial, min(max_traffic, initial * 2), max_traffic],
        guardrails=guardrails,
        notes=notes
        + [
            "Keep baseline policy available for immediate rollback.",
            "Do not train on canary feedback until the canary passes guardrails.",
            "Segment results by task_type/stage/action to avoid Simpson's paradox.",
        ],
    )
