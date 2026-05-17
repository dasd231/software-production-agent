"""Dataset governance checks before fine-tuning."""

from __future__ import annotations

import re
from typing import Any

from agent.evaluation.schemas import Metric, MetricReport


SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("generic_secret", re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{12,}")),
)


def _scan_text(text: str) -> list[str]:
    hits: list[str] = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            hits.append(name)
    return hits


def evaluate_dataset_governance(examples: list[dict[str, Any]]) -> MetricReport:
    total = len(examples)
    secret_hits: dict[str, int] = {}
    with_citations = 0
    duplicate_keys: set[str] = set()
    duplicate_count = 0
    for example in examples:
        text = "\n".join(
            [
                str(example.get("instruction", "")),
                str(example.get("input", "")),
                str(example.get("output", "")),
            ]
        )
        for hit in _scan_text(text):
            secret_hits[hit] = secret_hits.get(hit, 0) + 1
        if example.get("citations"):
            with_citations += 1
        key = f"{example.get('instruction')}|{example.get('input')}|{example.get('output')}"
        if key in duplicate_keys:
            duplicate_count += 1
        duplicate_keys.add(key)
    citation_rate = with_citations / total if total else 0.0
    duplicate_rate = duplicate_count / total if total else 0.0
    secret_count = sum(secret_hits.values())
    metrics = (
        Metric("secret_scan", secret_count, 10.0 if secret_count == 0 else 0.0, weight=2.0, status="ok" if secret_count == 0 else "blocked"),
        Metric("citation_required_rate", round(citation_rate, 4), citation_rate * 10.0, weight=1.5),
        Metric("duplicate_rate", round(duplicate_rate, 4), (1.0 - duplicate_rate) * 10.0, weight=1.0),
        Metric("manual_review_required", True, 8.0, weight=0.4, status="required", detail="license/privacy review remains an operator gate"),
    )
    return MetricReport(
        stage="training.dataset_governance",
        metrics=metrics,
        summary={
            "examples": total,
            "secret_hits": secret_hits,
            "with_citations": with_citations,
            "duplicates": duplicate_count,
        },
    )
