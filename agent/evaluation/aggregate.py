"""Aggregate multiple metric reports into a run-level quality report."""

from __future__ import annotations

from typing import Any

from agent.evaluation.schemas import Metric, MetricReport


def _score(report: dict[str, Any]) -> float:
    try:
        return float(report.get("overall_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def aggregate_metric_reports(reports: list[dict[str, Any]], *, stage: str = "run.aggregate") -> MetricReport:
    valid = [report for report in reports if isinstance(report, dict) and report.get("schema") == "metric_report.v1"]
    scores = [_score(report) for report in valid]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0
    risk_count = sum(1 for report in valid if str(report.get("grade", "")) == "risk")
    watch_count = sum(1 for report in valid if str(report.get("grade", "")) == "watch")
    metrics = (
        Metric("report_count", len(valid), 10.0 if valid else 0.0, weight=1.0),
        Metric("average_score", avg_score, avg_score, weight=2.0),
        Metric("risk_count", risk_count, 10.0 if risk_count == 0 else max(0.0, 10.0 - risk_count * 3.0), weight=1.2),
        Metric("watch_count", watch_count, 10.0 if watch_count == 0 else max(0.0, 10.0 - watch_count * 1.5), weight=0.8),
    )
    return MetricReport(
        stage=stage,
        metrics=metrics,
        summary={
            "reports": len(valid),
            "average_score": avg_score,
            "grades": [str(report.get("grade", "")) for report in valid],
            "stages": [str(report.get("stage", "")) for report in valid],
        },
    )
