"""动态阶段系统 — 禁止固定流水线；阶段为数据结构，由 Planner/Agent 选用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StageId(str, Enum):
    PLANNING = "planning"
    DESIGN = "design"
    CODING = "coding"
    TESTING = "testing"
    FIXING = "fixing"
    REVIEW = "review"
    QA = "qa"
    SHIP = "ship"
    INVESTIGATE = "investigate"


@dataclass
class DynamicStage:
    """单阶段载荷：可被 Agent 任意排序、跳过或重复（非写死 DAG）。"""

    stage: str
    tasks: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "tasks": list(self.tasks), "meta": dict(self.meta)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DynamicStage:
        return cls(
            stage=str(d["stage"]),
            tasks=[str(t) for t in d.get("tasks", [])],
            meta=dict(d.get("meta", {})),
        )


def default_stage_catalog() -> list[str]:
    return [s.value for s in StageId]


def suggest_stage_after_error(current: str) -> str:
    """内置启发：出错后优先进入 fixing（仍可由 Agent 覆盖）。"""
    if current in (StageId.CODING.value, StageId.TESTING.value):
        return StageId.FIXING.value
    return current
