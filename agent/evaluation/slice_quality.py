"""Quality review for retrievable knowledge slices."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from agent.evaluation.schemas import Metric, MetricReport, clamp_score
from agent.learning.schemas import CodeSlice


_SPACE_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip().lower())


def _length_score(text: str) -> float:
    n = len(text.strip())
    if n <= 0:
        return 0.0
    if 80 <= n <= 2400:
        return 10.0
    if 30 <= n < 80:
        return 6.5
    if 2400 < n <= 4200:
        return 7.0
    return 4.0


def _density_score(sl: CodeSlice) -> float:
    token_count = len(sl.tokens)
    if token_count >= 12:
        return 10.0
    if token_count >= 6:
        return 8.0
    if token_count >= 3:
        return 6.5
    if token_count >= 1:
        return 4.0
    return 0.0


def _metadata_score(sl: CodeSlice) -> float:
    score = 0.0
    score += 2.5 if sl.path else 0.0
    score += 2.5 if sl.language else 0.0
    score += 2.5 if int(sl.start_line) >= 1 else 0.0
    score += 2.5 if int(sl.end_line) >= int(sl.start_line) else 0.0
    return score


def review_slices(slices: list[CodeSlice]) -> tuple[list[CodeSlice], list[dict[str, Any]], MetricReport]:
    accepted: list[CodeSlice] = []
    decisions: list[dict[str, Any]] = []
    fingerprints: set[str] = set()
    duplicate_count = 0
    metadata_ok = 0
    nonempty = 0
    dense = 0

    for sl in slices:
        blockers: list[str] = []
        warnings: list[str] = []
        text = str(sl.text or "")
        normalised = _normalise(text)
        fingerprint = hashlib.blake2b(normalised.encode("utf-8"), digest_size=12).hexdigest()
        duplicate = bool(normalised and fingerprint in fingerprints)

        if not normalised:
            blockers.append("empty_slice")
        if not sl.path or int(sl.start_line) < 1 or int(sl.end_line) < int(sl.start_line):
            blockers.append("invalid_location")
        if duplicate:
            blockers.append("duplicate_slice")
            duplicate_count += 1
        if len(sl.tokens) < 3:
            warnings.append("low_token_density")

        if normalised:
            fingerprints.add(fingerprint)
            nonempty += 1
        if _metadata_score(sl) >= 10.0:
            metadata_ok += 1
        if len(sl.tokens) >= 3:
            dense += 1

        score = clamp_score(
            (
                _length_score(text) * 0.35
                + _density_score(sl) * 0.35
                + _metadata_score(sl) * 0.30
            )
        )
        eligible = not blockers
        if eligible:
            accepted.append(sl)
        decisions.append(
            {
                "slice_id": sl.slice_id,
                "path": sl.path,
                "eligible": eligible,
                "decision": "accepted" if eligible else "rejected",
                "reasons": ["passed_slice_review"] if eligible else blockers,
                "warnings": warnings,
                "score": score,
            }
        )

    total = len(slices)
    accepted_count = len(accepted)
    duplicate_rate = duplicate_count / total if total else 0.0
    metrics = (
        Metric("slice_count", total, 10.0 if total >= 3 else 4.0 if total else 0.0, weight=0.8),
        Metric("accepted_rate", round(accepted_count / total, 4) if total else 0.0, 10.0 * accepted_count / total if total else 0.0, weight=1.2),
        Metric("nonempty_rate", round(nonempty / total, 4) if total else 0.0, 10.0 * nonempty / total if total else 0.0, weight=1.0),
        Metric("metadata_complete_rate", round(metadata_ok / total, 4) if total else 0.0, 10.0 * metadata_ok / total if total else 0.0, weight=1.2),
        Metric("density_ready_rate", round(dense / total, 4) if total else 0.0, 10.0 * dense / total if total else 0.0, weight=1.0),
        Metric("duplicate_rate", round(duplicate_rate, 4), (1.0 - duplicate_rate) * 10.0, weight=1.1),
    )
    report = MetricReport(
        stage="learning.slice_quality",
        metrics=metrics,
        summary={
            "slices": total,
            "accepted": accepted_count,
            "rejected": total - accepted_count,
            "duplicates": duplicate_count,
        },
    )
    return accepted, decisions, report
