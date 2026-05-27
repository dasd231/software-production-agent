from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from agent.workflow.event_bridge import load_workflow_traces_from_agent_events
from agent.workflow.schema import WorkflowTraceEvent


@dataclass(slots=True)
class RouteTrainingExample:
    example_id: str
    route_key: str
    route_choice: str
    reward: float
    quality_label: str
    features: dict[str, Any] = field(default_factory=dict)
    target: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RouteDatasetSummary:
    example_count: int
    route_key_counts: dict[str, int] = field(default_factory=dict)
    route_choice_counts: dict[str, int] = field(default_factory=dict)
    quality_counts: dict[str, int] = field(default_factory=dict)
    avg_reward: float = 0.0
    output_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "example_count": self.example_count,
            "route_key_counts": dict(sorted(self.route_key_counts.items())),
            "route_choice_counts": dict(sorted(self.route_choice_counts.items())),
            "quality_counts": dict(sorted(self.quality_counts.items())),
            "avg_reward": round(self.avg_reward, 4),
            "output_path": self.output_path,
        }

    def to_markdown(self) -> str:
        lines = ["# Route Policy Training Dataset", ""]
        lines.append(f"- example_count: `{self.example_count}`")
        lines.append(f"- avg_reward: `{self.avg_reward:.4f}`")
        if self.output_path:
            lines.append(f"- output_path: `{self.output_path}`")
        lines.append("")
        lines.append("## Route keys")
        for key, value in sorted(self.route_key_counts.items()):
            lines.append(f"- `{key}`: {value}")
        lines.append("")
        lines.append("## Quality labels")
        for key, value in sorted(self.quality_counts.items()):
            lines.append(f"- `{key}`: {value}")
        return "\n".join(lines) + "\n"


def _quality_label(reward: float) -> str:
    if reward >= 0.75:
        return "positive"
    if reward >= 0.35:
        return "neutral"
    return "negative"


def _bucket(value: float | None, *, step: float = 0.25, cap: float = 1.0) -> str:
    if value is None:
        return "unknown"
    clipped = max(0.0, min(float(value), cap))
    lo = int(clipped / step) * step
    hi = min(cap, lo + step)
    return f"{lo:.2f}-{hi:.2f}"


def _latency_bucket(latency_ms: float) -> str:
    if latency_ms <= 0:
        return "instant"
    if latency_ms < 100:
        return "lt_100ms"
    if latency_ms < 1000:
        return "lt_1s"
    if latency_ms < 10_000:
        return "lt_10s"
    return "gte_10s"


def _example_id(event: WorkflowTraceEvent) -> str:
    token = f"{event.run_id}:{event.step_index}:{event.node}:{event.route_key}:{event.route_choice}:{event.started_at:.6f}"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:16]


def _features(event: WorkflowTraceEvent) -> dict[str, Any]:
    source_kind = str(event.metadata.get("source_kind", "")) if isinstance(event.metadata, dict) else ""
    return {
        "node": event.node,
        "status": event.status,
        "source_kind": source_kind,
        "score_bucket": _bucket(event.score),
        "confidence_bucket": _bucket(event.confidence),
        "latency_bucket": _latency_bucket(float(event.latency_ms)),
        "cost_bucket": _bucket(event.cost, step=0.1, cap=0.5),
        "has_error": bool(event.error),
        "step_index": event.step_index,
    }


def build_route_training_examples(
    events: Iterable[WorkflowTraceEvent],
    *,
    min_abs_reward: float = 0.0,
) -> list[RouteTrainingExample]:
    examples: list[RouteTrainingExample] = []
    for event in events:
        if not event.route_key or not event.route_choice:
            continue
        reward = float(event.reward)
        if abs(reward) < min_abs_reward:
            continue
        label = _quality_label(reward)
        examples.append(
            RouteTrainingExample(
                example_id=_example_id(event),
                route_key=str(event.route_key),
                route_choice=str(event.route_choice),
                reward=round(reward, 6),
                quality_label=label,
                features=_features(event),
                target={
                    "task": "workflow_route_policy",
                    "label": str(event.route_choice),
                    "route_key": str(event.route_key),
                    "quality_label": label,
                    "sample_weight": round(max(0.05, min(1.0, abs(reward))), 6),
                },
            )
        )
    return examples


def summarize_route_training_examples(
    examples: Iterable[RouteTrainingExample],
    *,
    output_path: str = "",
) -> RouteDatasetSummary:
    rows = list(examples)
    route_key_counts = Counter(row.route_key for row in rows)
    route_choice_counts = Counter(row.route_choice for row in rows)
    quality_counts = Counter(row.quality_label for row in rows)
    avg_reward = sum(row.reward for row in rows) / len(rows) if rows else 0.0
    return RouteDatasetSummary(
        example_count=len(rows),
        route_key_counts=dict(route_key_counts),
        route_choice_counts=dict(route_choice_counts),
        quality_counts=dict(quality_counts),
        avg_reward=avg_reward,
        output_path=output_path,
    )


def write_route_training_dataset(
    events: Iterable[WorkflowTraceEvent],
    output_path: str | Path,
    *,
    min_abs_reward: float = 0.0,
) -> RouteDatasetSummary:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    examples = build_route_training_examples(events, min_abs_reward=min_abs_reward)
    with path.open("w", encoding="utf-8") as f:
        for example in examples:
            f.write(json.dumps(example.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")
    return summarize_route_training_examples(examples, output_path=str(path))


def write_route_training_dataset_from_agent_events(
    events_path: str | Path,
    output_path: str | Path,
    *,
    min_abs_reward: float = 0.0,
) -> RouteDatasetSummary:
    return write_route_training_dataset(
        load_workflow_traces_from_agent_events(events_path),
        output_path,
        min_abs_reward=min_abs_reward,
    )
