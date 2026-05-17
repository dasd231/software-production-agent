"""Evaluation for fine-tuning dataset preparation."""

from __future__ import annotations

import json
from typing import Any

from agent.core.protocol import ProtocolError, validate_action_dict
from agent.evaluation.schemas import Metric, MetricReport, clamp_score


def _task_counts(examples: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for example in examples:
        task = str(example.get("task_type", "unknown") or "unknown")
        counts[task] = counts.get(task, 0) + 1
    return counts


def _example_count_score(count: int) -> float:
    if count >= 1000:
        return 10.0
    if count >= 100:
        return 8.5
    if count >= 10:
        return 6.5
    if count >= 1:
        return 4.0
    return 0.0


def _output_length_score(avg_chars: float) -> float:
    if avg_chars <= 0:
        return 0.0
    if avg_chars < 40:
        return 4.0
    if avg_chars < 120:
        return 7.0
    if avg_chars <= 6000:
        return 10.0
    return clamp_score(10.0 - ((avg_chars - 6000.0) / 1200.0))


def _protocol_stats(examples: list[dict[str, Any]]) -> tuple[int, float, int]:
    protocol_rows = [ex for ex in examples if str(ex.get("task_type", "")) == "action_protocol_sft"]
    if not protocol_rows:
        return 0, 1.0, 0
    valid = 0
    actions: set[str] = set()
    for row in protocol_rows:
        try:
            raw = json.loads(str(row.get("output", "") or ""))
            if not isinstance(raw, dict):
                continue
            parsed = validate_action_dict(raw)
        except (json.JSONDecodeError, ProtocolError):
            continue
        valid += 1
        actions.add(str(parsed.get("action", "")))
    return len(protocol_rows), valid / len(protocol_rows), len({action for action in actions if action})


def evaluate_training_dataset(
    examples: list[dict[str, Any]],
    rejected: dict[str, int],
    *,
    dataset_format: str,
    train_count: int,
    eval_count: int,
) -> MetricReport:
    total_kept = len(examples)
    rejected_count = sum(int(v) for v in rejected.values())
    raw_count = total_kept + rejected_count
    task_counts = _task_counts(examples)
    citation_count = sum(1 for example in examples if example.get("citations"))
    citation_rate = citation_count / total_kept if total_kept else 0.0
    rejection_rate = rejected_count / raw_count if raw_count else 0.0
    avg_output_chars = (
        sum(len(str(example.get("output", "") or "")) for example in examples) / total_kept
        if total_kept
        else 0.0
    )
    protocol_count, protocol_validity, protocol_action_coverage = _protocol_stats(examples)
    task_shares = {
        task: (count / total_kept if total_kept else 0.0)
        for task, count in task_counts.items()
    }
    min_task_share = min(task_shares.values()) if task_shares else 0.0
    valid_rows = sum(1 for example in examples if str(example.get("instruction", "")).strip() and str(example.get("output", "")).strip())
    format_validity = valid_rows / total_kept if total_kept else 0.0
    split_ok = True if total_kept <= 1 else bool(train_count > 0 and eval_count > 0)
    metrics = (
        Metric("example_count", total_kept, _example_count_score(total_kept), weight=1.2),
        Metric("citation_rate", round(citation_rate, 4), citation_rate * 10.0, weight=1.6),
        Metric("task_diversity", len(task_counts), min(len(task_counts), 3) / 3.0 * 10.0, weight=1.0),
        Metric(
            "min_task_share",
            round(min_task_share, 4),
            min(min_task_share / 0.05, 1.0) * 10.0 if task_counts else 0.0,
            weight=0.8,
            status="ok" if min_task_share >= 0.05 else "watch",
            detail="minimum share among present task types",
        ),
        Metric("average_output_chars", round(avg_output_chars, 2), _output_length_score(avg_output_chars), weight=0.8),
        Metric("rejection_rate", round(rejection_rate, 4), (1.0 - rejection_rate) * 10.0, weight=1.0, status="ok" if rejection_rate <= 0.25 else "watch"),
        Metric("train_eval_split", {"train": train_count, "eval": eval_count}, 10.0 if split_ok else 6.0, weight=0.8, status="ok" if split_ok else "train_only"),
        Metric("format_validity", round(format_validity, 4), format_validity * 10.0, weight=1.4),
        Metric(
            "protocol_validity_rate",
            round(protocol_validity, 4),
            protocol_validity * 10.0,
            weight=1.0,
            status="ok" if protocol_count else "not_applicable",
        ),
        Metric(
            "protocol_action_coverage",
            protocol_action_coverage,
            min(protocol_action_coverage, 10) / 10.0 * 10.0 if protocol_count else 10.0,
            weight=0.8,
            status="ok" if protocol_count else "not_applicable",
        ),
    )
    return MetricReport(
        stage="training.dataset_prepare",
        metrics=metrics,
        summary={
            "dataset_format": dataset_format,
            "by_task_type": task_counts,
            "with_citations": citation_count,
            "rejected": dict(rejected),
            "raw_examples": raw_count,
            "protocol_examples": protocol_count,
            "protocol_action_coverage": protocol_action_coverage,
            "task_shares": {task: round(share, 4) for task, share in task_shares.items()},
        },
    )


def training_quality_summary(report: MetricReport) -> dict[str, Any]:
    summary = dict(report.summary)
    citation_metric = report.metric("citation_rate")
    summary.update(
        {
            "citation_rate": citation_metric.value if citation_metric else 0.0,
            "evaluation_score": report.overall_score,
            "evaluation_grade": report.grade,
        }
    )
    return summary
