"""Local-first evidence arbitration for research synthesis."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from agent.chains.research_types import RAGHint, SolutionHit, WebResult

_VERSION_RE = re.compile(r"\b(?:v|version\s*)?(\d+\.\d+(?:\.\d+)?)\b", re.IGNORECASE)


def _versions(rows: Sequence[Mapping[str, Any]], fields: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for row in rows:
        text = " ".join(str(row.get(field, "") or "") for field in fields)
        found.update(match.group(1) for match in _VERSION_RE.finditer(text))
    return found


def arbitrate_evidence(
    *,
    solution_hits: list[SolutionHit],
    rag_hints: list[RAGHint],
    web_results: list[WebResult],
) -> dict[str, Any]:
    local_count = len(solution_hits) + len(rag_hints)
    web_count = len(web_results)
    source_order = ["solution_library", "local_rag", "web"]
    decision = "local_first"
    if local_count == 0 and web_count:
        decision = "web_only_requires_verification"
    elif local_count and web_count:
        decision = "web_supplemental"
    local_versions = _versions(solution_hits + rag_hints, ("stack", "goal", "preview", "backup_preview"))
    web_versions = _versions(web_results, ("title", "snippet", "url"))
    conflicts = sorted(local_versions ^ web_versions) if local_versions and web_versions and local_versions != web_versions else []
    conflict_details: list[dict[str, Any]] = []
    if conflicts:
        conflict_details.append(
            {
                "type": "version_mismatch",
                "left_source": "local_evidence",
                "right_source": "web",
                "field": "version",
                "left_values": sorted(local_versions),
                "right_values": sorted(web_versions),
                "mismatch_values": conflicts,
                "requires_manual_review": True,
            }
        )
    source_confidence = {
        "solution_library": {
            "score": 0.95 if solution_hits else 0.0,
            "basis": "accepted_or_curated_local_asset" if solution_hits else "no_evidence",
            "history_samples": 0,
        },
        "local_rag": {
            "score": 0.9 if rag_hints else 0.0,
            "basis": "workspace_or_learning_store_evidence" if rag_hints else "no_evidence",
            "history_samples": 0,
        },
        "web": {
            "score": 0.65 if web_results else 0.0,
            "basis": "external_supplement_requires_verification" if web_results else "no_evidence",
            "history_samples": 0,
        },
    }
    rationale = {
        "local_first": "只发现本地证据，直接按正式方案库优先。",
        "web_only_requires_verification": "没有本地证据，只能先用 Web，但进入实现前必须复核。",
        "web_supplemental": "本地证据存在，Web 只作外部补充，不覆盖本地事实。",
    }[decision]
    return {
        "source_order": source_order,
        "decision": decision,
        "local_evidence": local_count,
        "web_evidence": web_count,
        "conflicts": [{"type": "version_mismatch", "values": conflicts}] if conflicts else [],
        "conflict_details": conflict_details,
        "source_confidence": source_confidence,
        "decision_rationale": rationale,
        "rules": [
            "solution_library outranks local RAG when both are relevant",
            "local RAG outranks Web for existing project facts",
            "Web is supplemental for external or fast-changing facts",
            "conflicts must be surfaced instead of silently merged",
        ],
    }
