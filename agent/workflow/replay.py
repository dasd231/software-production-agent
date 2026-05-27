from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable

from agent.workflow.schema import WorkflowPolicy, WorkflowTraceEvent


@dataclass(slots=True)
class RouteReplayMetric:
    route_key: str
    observed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    observed_avg_reward: float = 0.0
    accepted_avg_reward: float = 0.0
    best_choice: str = ""
    candidate_top_choice: str = ""
    coverage: float = 0.0


@dataclass(slots=True)
class ReplayRisk:
    severity: str
    title: str
    detail: str
    mitigation: str


@dataclass(slots=True)
class ReplayReport:
    total_events: int
    routed_events: int
    accepted_events: int
    rejected_events: int
    estimated_reward_observed: float
    estimated_reward_candidate: float
    coverage: float
    route_metrics: list[RouteReplayMetric] = field(default_factory=list)
    risks: list[ReplayRisk] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_events": self.total_events,
            "routed_events": self.routed_events,
            "accepted_events": self.accepted_events,
            "rejected_events": self.rejected_events,
            "estimated_reward_observed": round(self.estimated_reward_observed, 4),
            "estimated_reward_candidate": round(self.estimated_reward_candidate, 4),
            "coverage": round(self.coverage, 4),
            "route_metrics": [asdict(x) for x in self.route_metrics],
            "risks": [asdict(x) for x in self.risks],
            "limitations": self.limitations,
        }

    def to_markdown(self) -> str:
        lines = ["# Workflow Replay Report", ""]
        lines.append(f"- total_events: `{self.total_events}`")
        lines.append(f"- routed_events: `{self.routed_events}`")
        lines.append(f"- accepted_events: `{self.accepted_events}`")
        lines.append(f"- rejected_events: `{self.rejected_events}`")
        lines.append(f"- coverage: `{self.coverage:.2%}`")
        lines.append(f"- estimated_reward_observed: `{self.estimated_reward_observed:.4f}`")
        lines.append(f"- estimated_reward_candidate: `{self.estimated_reward_candidate:.4f}`")
        lines.append("")
        lines.append("## Route metrics")
        for metric in self.route_metrics:
            lines.append(
                f"- `{metric.route_key}` observed={metric.observed_count}, accepted={metric.accepted_count}, "
                f"coverage={metric.coverage:.2%}, observed_reward={metric.observed_avg_reward:.3f}, "
                f"accepted_reward={metric.accepted_avg_reward:.3f}, candidate_top=`{metric.candidate_top_choice}`, "
                f"best_observed=`{metric.best_choice}`"
            )
        lines.append("")
        lines.append("## Risks")
        if not self.risks:
            lines.append("- No major replay risk detected, but offline replay is still not causal proof.")
        for risk in self.risks:
            lines.append(f"- **{risk.severity}** {risk.title}: {risk.detail} → {risk.mitigation}")
        lines.append("")
        lines.append("## Limitations")
        lines.extend(f"- {item}" for item in self.limitations)
        return "\n".join(lines) + "\n"


def _top_choice(policy: WorkflowPolicy, route_key: str) -> str:
    choices = policy.route_weights.get(route_key, {})
    if not choices:
        return ""
    return max(sorted(choices), key=lambda key: (float(choices[key]), key))


def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def replay_logged_policy(
    events: Iterable[WorkflowTraceEvent],
    *,
    candidate_policy: WorkflowPolicy,
) -> ReplayReport:
    """Conservative logged-policy replay.

    This is not a causal counterfactual estimator. It only evaluates events whose
    observed route choice matches the candidate policy's current top choice. That
    makes it conservative and honest for interviews: useful for screening bad
    policies, not sufficient to prove a policy is globally optimal.
    """

    rows = list(events)
    routed = [event for event in rows if event.route_key and event.route_choice]
    accepted: list[WorkflowTraceEvent] = []
    rejected: list[WorkflowTraceEvent] = []
    by_route: dict[str, list[WorkflowTraceEvent]] = {}
    for event in routed:
        by_route.setdefault(str(event.route_key), []).append(event)
        if event.route_choice == _top_choice(candidate_policy, str(event.route_key)):
            accepted.append(event)
        else:
            rejected.append(event)

    route_metrics: list[RouteReplayMetric] = []
    risks: list[ReplayRisk] = []
    for route_key, route_events in sorted(by_route.items()):
        top = _top_choice(candidate_policy, route_key)
        accepted_route = [event for event in route_events if event.route_choice == top]
        choice_rewards: dict[str, list[float]] = {}
        for event in route_events:
            choice_rewards.setdefault(str(event.route_choice), []).append(event.reward)
        best_choice = ""
        if choice_rewards:
            best_choice = max(sorted(choice_rewards), key=lambda choice: (_avg(choice_rewards[choice]), choice))
        metric = RouteReplayMetric(
            route_key=route_key,
            observed_count=len(route_events),
            accepted_count=len(accepted_route),
            rejected_count=len(route_events) - len(accepted_route),
            observed_avg_reward=_avg([event.reward for event in route_events]),
            accepted_avg_reward=_avg([event.reward for event in accepted_route]),
            best_choice=best_choice,
            candidate_top_choice=top,
            coverage=(len(accepted_route) / len(route_events)) if route_events else 0.0,
        )
        route_metrics.append(metric)
        if top and best_choice and top != best_choice and len(route_events) >= 2:
            risks.append(
                ReplayRisk(
                    severity="medium",
                    title=f"Candidate top choice differs from observed best for {route_key}",
                    detail=f"candidate={top}, observed_best={best_choice}",
                    mitigation="increase exploration sample size or gate policy behind smaller canary",
                )
            )
        if metric.coverage < 0.25 and len(route_events) >= 4:
            risks.append(
                ReplayRisk(
                    severity="high",
                    title=f"Low replay coverage for {route_key}",
                    detail=f"coverage={metric.coverage:.2%}; candidate chooses routes rarely observed in logs",
                    mitigation="run shadow evaluation or exploration before promotion",
                )
            )

    coverage = len(accepted) / len(routed) if routed else 0.0
    if routed and coverage < 0.3:
        risks.append(
            ReplayRisk(
                severity="high",
                title="Low global replay coverage",
                detail=f"only {coverage:.2%} routed events match candidate top choices",
                mitigation="do not promote; collect more exploration traces or use tiny canary",
            )
        )

    limitations = [
        "Logged replay only scores branches that were actually observed; it cannot prove unobserved routes are better.",
        "Rewards depend on current heuristic reward design and can be biased by sparse or delayed feedback.",
        "Coverage must be checked before using replay results as promotion evidence.",
        "Use canary guardrails before production promotion even when replay looks positive.",
    ]
    return ReplayReport(
        total_events=len(rows),
        routed_events=len(routed),
        accepted_events=len(accepted),
        rejected_events=len(rejected),
        estimated_reward_observed=_avg([event.reward for event in routed]),
        estimated_reward_candidate=_avg([event.reward for event in accepted]),
        coverage=coverage,
        route_metrics=route_metrics,
        risks=risks,
        limitations=limitations,
    )
