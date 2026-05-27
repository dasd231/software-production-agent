from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Callable, Literal

START = "__start__"
END = "__end__"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    INTERRUPTED = "interrupted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class WorkflowState:
    run_id: str
    goal: str
    data: dict[str, Any] = field(default_factory=dict)
    status: WorkflowStatus = WorkflowStatus.PENDING
    current_node: str = START
    step_index: int = 0
    error: str | None = None
    created_at: float = field(default_factory=time)
    updated_at: float = field(default_factory=time)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.updated_at = time()

    def merge(self, updates: dict[str, Any]) -> None:
        self.data.update(updates)
        self.updated_at = time()


@dataclass(slots=True)
class NodeResult:
    updates: dict[str, Any] = field(default_factory=dict)
    score: float | None = None
    confidence: float | None = None
    cost: float = 0.0
    interrupt: bool = False
    message: str = ""


@dataclass(slots=True)
class WorkflowTraceEvent:
    run_id: str
    step_index: int
    node: str
    status: Literal["ok", "error", "interrupt"]
    started_at: float
    ended_at: float
    latency_ms: float
    route_key: str | None = None
    route_choice: str | None = None
    score: float | None = None
    confidence: float | None = None
    cost: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def reward(self) -> float:
        quality = self.score if self.score is not None else 0.5
        confidence_bonus = 0.1 * (self.confidence if self.confidence is not None else 0.0)
        latency_penalty = min(self.latency_ms / 10_000.0, 0.5)
        cost_penalty = min(self.cost, 0.5)
        failure_penalty = 1.0 if self.status == "error" else 0.0
        return quality + confidence_bonus - latency_penalty - cost_penalty - failure_penalty


@dataclass(slots=True)
class RouteStats:
    route_key: str
    route_choice: str
    count: int = 0
    avg_reward: float = 0.0
    avg_score: float = 0.0
    avg_latency_ms: float = 0.0
    error_count: int = 0

    def update(self, event: WorkflowTraceEvent) -> None:
        self.count += 1
        alpha = 1 / self.count
        self.avg_reward = (1 - alpha) * self.avg_reward + alpha * event.reward
        self.avg_score = (1 - alpha) * self.avg_score + alpha * (event.score or 0.0)
        self.avg_latency_ms = (1 - alpha) * self.avg_latency_ms + alpha * event.latency_ms
        if event.status == "error":
            self.error_count += 1


@dataclass(slots=True)
class WorkflowPolicy:
    """Versionable workflow policy.

    Route weights are deliberately separated from node code. This is the key
    LangGraph-second-modification idea: graph topology stays stable while routing
    policy can be optimized from traces and rolled out like config.
    """

    route_weights: dict[str, dict[str, float]] = field(default_factory=dict)
    max_steps: int = 24
    min_confidence: float = 0.72
    max_repairs: int = 1
    exploration_rate: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    skill_runtime_enabled: bool = False
    skill_required_skill_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    skill_explicit_scope: dict[str, tuple[str, ...]] = field(default_factory=dict)
    skill_fail_closed: bool = True

    def candidates(self, route_key: str) -> dict[str, float]:
        return self.route_weights.get(route_key, {})


GraphNode = Callable[[WorkflowState], NodeResult]
Router = Callable[[WorkflowState, NodeResult, WorkflowPolicy], str]
