from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Iterable

from agent.workflow.schema import RouteStats, WorkflowPolicy, WorkflowTraceEvent


@dataclass(slots=True)
class WorkflowFinding:
    severity: str
    title: str
    detail: str
    action: str


@dataclass(slots=True)
class WorkflowOptimizationReport:
    route_stats: dict[tuple[str, str], RouteStats]
    findings: list[WorkflowFinding] = field(default_factory=list)
    proposed_policy: WorkflowPolicy | None = None

    def to_dict(self) -> dict:
        return {
            "route_stats": {
                f"{key[0]}->{key[1]}": {
                    "count": stat.count,
                    "avg_reward": round(stat.avg_reward, 4),
                    "avg_score": round(stat.avg_score, 4),
                    "avg_latency_ms": round(stat.avg_latency_ms, 3),
                    "error_count": stat.error_count,
                }
                for key, stat in self.route_stats.items()
            },
            "findings": [asdict(finding) for finding in self.findings],
            "proposed_policy": {
                "route_weights": self.proposed_policy.route_weights,
                "metadata": self.proposed_policy.metadata,
            }
            if self.proposed_policy
            else None,
        }


class WorkflowOptimizer:
    """Trace-driven optimizer for project workflow route policies."""

    def __init__(self, *, min_samples_per_route: int = 2, underperform_threshold: float = 0.35) -> None:
        self.min_samples_per_route = min_samples_per_route
        self.underperform_threshold = underperform_threshold

    def analyze(
        self,
        events: Iterable[WorkflowTraceEvent],
        base_policy: WorkflowPolicy,
    ) -> WorkflowOptimizationReport:
        route_stats: dict[tuple[str, str], RouteStats] = {}
        for event in events:
            if not event.route_key or not event.route_choice:
                continue
            key = (event.route_key, event.route_choice)
            route_stats.setdefault(
                key,
                RouteStats(route_key=event.route_key, route_choice=event.route_choice),
            ).update(event)
        findings = self._find_route_issues(route_stats)
        proposed = self._propose_policy(route_stats, base_policy)
        return WorkflowOptimizationReport(route_stats=route_stats, findings=findings, proposed_policy=proposed)

    def _find_route_issues(self, route_stats: dict[tuple[str, str], RouteStats]) -> list[WorkflowFinding]:
        findings: list[WorkflowFinding] = []
        grouped: dict[str, list[RouteStats]] = defaultdict(list)
        for stat in route_stats.values():
            grouped[stat.route_key].append(stat)
        for route_key, stats in grouped.items():
            eligible = [s for s in stats if s.count >= self.min_samples_per_route]
            if len(eligible) >= 2:
                best = max(eligible, key=lambda s: s.avg_reward)
                worst = min(eligible, key=lambda s: s.avg_reward)
                if best.avg_reward - worst.avg_reward > 0.15:
                    findings.append(
                        WorkflowFinding(
                            severity="medium",
                            title=f"route {route_key} has a stronger branch",
                            detail=f"best={best.route_choice}:{best.avg_reward:.3f}, worst={worst.route_choice}:{worst.avg_reward:.3f}",
                            action=f"increase {best.route_choice} weight and canary rollout",
                        )
                    )
            for stat in eligible:
                if stat.avg_reward < self.underperform_threshold:
                    findings.append(
                        WorkflowFinding(
                            severity="high",
                            title=f"route choice {stat.route_choice} underperforms",
                            detail=f"avg_reward={stat.avg_reward:.3f}, count={stat.count}",
                            action="gate this branch behind human review or disable for low-risk tasks",
                        )
                    )
        return findings

    def _propose_policy(
        self,
        route_stats: dict[tuple[str, str], RouteStats],
        base_policy: WorkflowPolicy,
    ) -> WorkflowPolicy:
        proposed = WorkflowPolicy(
            route_weights={key: dict(value) for key, value in base_policy.route_weights.items()},
            max_steps=base_policy.max_steps,
            min_confidence=base_policy.min_confidence,
            max_repairs=base_policy.max_repairs,
            exploration_rate=base_policy.exploration_rate,
            metadata=dict(base_policy.metadata),
        )
        grouped: dict[str, list[RouteStats]] = defaultdict(list)
        for stat in route_stats.values():
            if stat.count >= self.min_samples_per_route:
                grouped[stat.route_key].append(stat)

        for route_key, stats in grouped.items():
            prior = {choice: 0.05 for choice in proposed.route_weights.get(route_key, {})}
            if not stats:
                continue
            min_reward = min(stat.avg_reward for stat in stats)
            for stat in stats:
                prior[stat.route_choice] = max(0.05, stat.avg_reward - min_reward + 0.1)
            total = sum(prior.values())
            if total > 0:
                proposed.route_weights[route_key] = {
                    choice: round(value / total, 4) for choice, value in sorted(prior.items())
                }
        proposed.metadata["optimized_by"] = "agent.workflow.WorkflowOptimizer"
        return proposed
