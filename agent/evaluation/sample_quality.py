"""Quality review for training examples before local-model fine-tuning."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.core.protocol import ProtocolError, validate_action_dict
from agent.evaluation.schemas import Metric, MetricReport, clamp_score


EVIDENCE_REQUIRED_TASKS = {
    "knowledge_card_qa",
    "code_explanation",
    "rag_grounded_answer",
    "solution_reuse_sft",
}

REJECTION_PRIORITY = (
    "invalid_action_protocol",
    "missing_required_citations",
    "short_instruction",
    "short_output",
    "oversized_output",
    "duplicate",
    "max_examples_limit",
)


def _is_strict_action_protocol(output: str) -> bool:
    try:
        raw = json.loads(output)
    except json.JSONDecodeError:
        return False
    if not isinstance(raw, dict):
        return False
    try:
        validate_action_dict(raw)
    except ProtocolError:
        return False
    return True


def _stable_key(example: dict[str, Any]) -> str:
    h = hashlib.blake2b(digest_size=12)
    for key in ("instruction", "input", "output"):
        h.update(str(example.get(key, "") or "").strip().encode("utf-8", errors="ignore"))
        h.update(b"\0")
    return h.hexdigest()


def review_training_examples(
    examples: list[dict[str, Any]],
    *,
    min_chars: int,
    max_examples: int,
) -> tuple[list[dict[str, Any]], dict[str, int], list[dict[str, Any]], MetricReport]:
    accepted: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    decisions: list[dict[str, Any]] = []
    seen: set[str] = set()
    evidence_required_total = 0
    evidence_required_with_citations = 0
    citation_count = 0
    duplicate_count = 0

    for example in examples:
        blockers: list[str] = []
        warnings: list[str] = []
        instruction = str(example.get("instruction", "") or "").strip()
        output = str(example.get("output", "") or "").strip()
        task_type = str(example.get("task_type", "sft") or "sft")
        citations = example.get("citations") if isinstance(example.get("citations"), list) else []
        key = _stable_key(example)

        if len(instruction) < 6:
            blockers.append("short_instruction")
        if len(output) < max(int(min_chars), 1):
            blockers.append("short_output")
        if len(output) > 12000:
            blockers.append("oversized_output")
        if key in seen:
            blockers.append("duplicate")
            duplicate_count += 1
        if task_type in EVIDENCE_REQUIRED_TASKS:
            evidence_required_total += 1
            if citations:
                evidence_required_with_citations += 1
            else:
                blockers.append("missing_required_citations")
        if task_type == "action_protocol_sft" and not _is_strict_action_protocol(output):
            blockers.append("invalid_action_protocol")
        if citations:
            citation_count += 1
        else:
            warnings.append("missing_citations")
        seen.add(key)

        eligible = not blockers and len(accepted) < max(int(max_examples), 1)
        if not blockers and len(accepted) >= max(int(max_examples), 1):
            blockers.append("max_examples_limit")
            eligible = False
        if eligible:
            accepted.append(example)
        else:
            reason = next((item for item in REJECTION_PRIORITY if item in blockers), blockers[0] if blockers else "rejected")
            rejected[reason] = rejected.get(reason, 0) + 1
        decisions.append(
            {
                "example_id": str(example.get("example_id", "")),
                "task_type": task_type,
                "eligible": eligible,
                "decision": "accepted" if eligible else "rejected",
                "reasons": ["passed_sample_review"] if eligible else blockers,
                "warnings": warnings,
            }
        )

    total = len(examples)
    accepted_count = len(accepted)
    avg_output_chars = (
        sum(len(str(example.get("output", "") or "")) for example in accepted) / accepted_count
        if accepted_count
        else 0.0
    )
    task_types = {str(example.get("task_type", "unknown") or "unknown") for example in accepted}
    duplicate_rate = duplicate_count / total if total else 0.0
    grounded_rate = evidence_required_with_citations / evidence_required_total if evidence_required_total else 1.0
    metrics = (
        Metric("accepted_rate", round(accepted_count / total, 4) if total else 0.0, 10.0 * accepted_count / total if total else 0.0, weight=1.4),
        Metric("citation_rate", round(citation_count / total, 4) if total else 0.0, 10.0 * citation_count / total if total else 0.0, weight=1.2),
        Metric("grounded_required_rate", round(grounded_rate, 4), grounded_rate * 10.0, weight=1.6),
        Metric("duplicate_rate", round(duplicate_rate, 4), (1.0 - duplicate_rate) * 10.0, weight=1.0),
        Metric("task_diversity", len(task_types), min(len(task_types), 3) / 3.0 * 10.0, weight=0.8),
        Metric("average_output_chars", round(avg_output_chars, 2), clamp_score(avg_output_chars / 12.0), weight=0.8),
    )
    report = MetricReport(
        stage="training.sample_quality",
        metrics=metrics,
        summary={
            "raw_examples": total,
            "accepted": accepted_count,
            "rejected": sum(rejected.values()),
            "rejected_by_reason": dict(rejected),
            "evidence_required": evidence_required_total,
        },
    )
    return accepted, rejected, decisions, report
