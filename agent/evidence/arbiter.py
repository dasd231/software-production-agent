"""Local-first evidence arbitration for research synthesis."""

from __future__ import annotations

import re
from typing import Any


_VERSION_RE = re.compile(r"\b(?:v|version\s*)?(\d+\.\d+(?:\.\d+)?)\b", re.IGNORECASE)


def _versions(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> set[str]:
    found: set[str] = set()
    for row in rows:
        text = " ".join(str(row.get(field, "") or "") for field in fields)
        found.update(match.group(1) for match in _VERSION_RE.finditer(text))
    return found


def arbitrate_evidence(
    *,
    solution_hits: list[dict[str, Any]],
    rag_hints: list[dict[str, Any]],
    web_results: list[dict[str, Any]],
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
    return {
        "source_order": source_order,
        "decision": decision,
        "local_evidence": local_count,
        "web_evidence": web_count,
        "conflicts": [{"type": "version_mismatch", "values": conflicts}] if conflicts else [],
        "rules": [
            "solution_library outranks local RAG when both are relevant",
            "local RAG outranks Web for existing project facts",
            "Web is supplemental for external or fast-changing facts",
            "conflicts must be surfaced instead of silently merged",
        ],
    }
