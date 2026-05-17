"""Small, serialisable metric primitives shared by chain evaluators."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


def clamp_score(value: float, *, lower: float = 0.0, upper: float = 10.0) -> float:
    if not math.isfinite(float(value)):
        return lower
    return round(max(lower, min(float(value), upper)), 2)


def ratio_score(value: float, *, target: float = 1.0) -> float:
    if target <= 0:
        return 0.0
    return clamp_score(float(value) / float(target) * 10.0)


@dataclass(frozen=True)
class Metric:
    name: str
    value: Any
    score: float
    weight: float = 1.0
    status: str = "ok"
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "score": clamp_score(self.score),
            "weight": round(max(float(self.weight), 0.0), 3),
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class MetricReport:
    stage: str
    metrics: tuple[Metric, ...]
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def overall_score(self) -> float:
        weighted_sum = 0.0
        total_weight = 0.0
        for metric in self.metrics:
            weight = max(float(metric.weight), 0.0)
            if weight <= 0:
                continue
            weighted_sum += clamp_score(metric.score) * weight
            total_weight += weight
        if total_weight <= 0:
            return 0.0
        return clamp_score(weighted_sum / total_weight)

    @property
    def grade(self) -> str:
        score = self.overall_score
        if score >= 8.0:
            return "excellent"
        if score >= 6.5:
            return "good"
        if score >= 4.0:
            return "watch"
        return "risk"

    def metric(self, name: str) -> Metric | None:
        for metric in self.metrics:
            if metric.name == name:
                return metric
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "metric_report.v1",
            "stage": self.stage,
            "overall_score": self.overall_score,
            "grade": self.grade,
            "summary": dict(self.summary),
            "metrics": {metric.name: metric.to_dict() for metric in self.metrics},
        }
