"""Quality review for generated knowledge cards."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from agent.evaluation.schemas import Metric, MetricReport, clamp_score
from agent.learning.schemas import KnowledgeCard


_SPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip().lower())


def _summary_score(summary: str) -> float:
    n = len(summary.strip())
    if 40 <= n <= 700:
        return 10.0
    if 20 <= n < 40:
        return 6.5
    if 700 < n <= 1200:
        return 7.0
    if n > 0:
        return 4.0
    return 0.0


def review_cards(
    cards: list[KnowledgeCard],
    *,
    known_paths: set[str],
) -> tuple[list[KnowledgeCard], list[dict[str, Any]], MetricReport]:
    accepted: list[KnowledgeCard] = []
    decisions: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    cited = 0
    valid_cited = 0
    complete = 0
    duplicate_count = 0

    for card in cards:
        blockers: list[str] = []
        warnings: list[str] = []
        source_paths = [str(path) for path in card.source_paths if str(path).strip()]
        valid_paths = [path for path in source_paths if path in known_paths]
        fp_payload = _normalise(card.title + "\n" + card.summary)
        fingerprint = hashlib.blake2b(fp_payload.encode("utf-8"), digest_size=12).hexdigest()
        duplicate = bool(fp_payload and fingerprint in fingerprints)

        if not card.title.strip():
            blockers.append("missing_title")
        if not card.summary.strip():
            blockers.append("missing_summary")
        if not source_paths:
            blockers.append("missing_citations")
        if source_paths and not valid_paths:
            blockers.append("invalid_citations")
        if duplicate:
            blockers.append("duplicate_card")
            duplicate_count += 1
        if not card.questions:
            warnings.append("missing_questions")
        if len(card.summary.strip()) < 40:
            warnings.append("short_summary")

        if source_paths:
            cited += 1
        if valid_paths:
            valid_cited += 1
        if card.title.strip() and card.summary.strip() and card.tags and card.questions and valid_paths:
            complete += 1
        if fp_payload:
            fingerprints.add(fingerprint)

        source_score = 10.0 if valid_paths else 4.0 if source_paths else 0.0
        completeness_score = (
            (2.0 if card.title.strip() else 0.0)
            + (2.0 if card.summary.strip() else 0.0)
            + (2.0 if card.tags else 0.0)
            + (2.0 if card.questions else 0.0)
            + (2.0 if valid_paths else 0.0)
        )
        score = clamp_score(_summary_score(card.summary) * 0.35 + source_score * 0.40 + completeness_score * 0.25)
        eligible = not blockers
        if eligible:
            accepted.append(card)
        decisions.append(
            {
                "title": card.title,
                "eligible": eligible,
                "decision": "accepted" if eligible else "rejected",
                "reasons": ["passed_card_review"] if eligible else blockers,
                "warnings": warnings,
                "score": score,
                "valid_sources": valid_paths,
            }
        )

    total = len(cards)
    accepted_count = len(accepted)
    duplicate_rate = duplicate_count / total if total else 0.0
    metrics = (
        Metric("card_count", total, 10.0 if total >= 3 else 4.0 if total else 0.0, weight=0.8),
        Metric("accepted_rate", round(accepted_count / total, 4) if total else 0.0, 10.0 * accepted_count / total if total else 0.0, weight=1.2),
        Metric("citation_coverage_rate", round(cited / total, 4) if total else 0.0, 10.0 * cited / total if total else 0.0, weight=1.5),
        Metric("citation_validity_rate", round(valid_cited / total, 4) if total else 0.0, 10.0 * valid_cited / total if total else 0.0, weight=1.5),
        Metric("complete_card_rate", round(complete / total, 4) if total else 0.0, 10.0 * complete / total if total else 0.0, weight=1.0),
        Metric("duplicate_rate", round(duplicate_rate, 4), (1.0 - duplicate_rate) * 10.0, weight=1.0),
    )
    report = MetricReport(
        stage="learning.card_quality",
        metrics=metrics,
        summary={
            "cards": total,
            "accepted": accepted_count,
            "rejected": total - accepted_count,
            "duplicates": duplicate_count,
        },
    )
    return accepted, decisions, report
