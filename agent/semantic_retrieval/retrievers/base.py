from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

from agent.semantic_retrieval.schemas import CandidateEvidence, NeedSlot, TaskSemanticFrame

_WORD_RE = re.compile(r"[A-Za-z0-9_./:-]+|[\u4e00-\u9fff]{2,}")


def normalize_text(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(str(text or "")) if len(m.group(0).strip()) >= 2}


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("\n".join(parts).encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def lexical_score(queries: Sequence[str], text: str) -> float:
    """Small deterministic retrieval score used by MVP retrievers.

    It intentionally stays simple and local: exact phrase hits get weight, token
    overlap prevents completely unrelated evidence from leaking in. This is not
    the final ranking score; NecessityReranker owns the final decision.
    """
    haystack = normalize_text(text)
    if not haystack:
        return 0.0
    query_tokens: set[str] = set()
    exact_hits = 0
    for query in queries:
        q = normalize_text(query)
        if not q:
            continue
        if q in haystack:
            exact_hits += 1
        query_tokens.update(tokenize(q))
    if not query_tokens:
        return 0.0
    text_tokens = tokenize(haystack)
    overlap = len(query_tokens & text_tokens)
    jaccard = overlap / max(len(query_tokens | text_tokens), 1)
    phrase_score = min(exact_hits / max(len(queries), 1), 1.0)
    token_score = min(overlap / max(min(len(query_tokens), 12), 1), 1.0)
    return min(0.45 * phrase_score + 0.45 * token_score + 0.10 * jaccard, 1.0)


def slot_text(slot: NeedSlot) -> str:
    return " ".join([slot.slot_id, slot.slot_type, slot.name, slot.description, *slot.query_terms])


class BaseRetriever(ABC):
    name: str = "base"

    @abstractmethod
    def retrieve(
        self,
        slots: Sequence[NeedSlot],
        queries_by_slot: Mapping[str, Sequence[str]],
        frame: TaskSemanticFrame | None = None,
    ) -> list[CandidateEvidence]:
        raise NotImplementedError


def merge_evidence(candidates: Sequence[CandidateEvidence]) -> list[CandidateEvidence]:
    by_id: dict[str, CandidateEvidence] = {}
    for candidate in candidates:
        existing = by_id.get(candidate.evidence_id)
        if existing is None:
            by_id[candidate.evidence_id] = candidate
            continue
        matched = tuple(dict.fromkeys([*existing.matched_slot_ids, *candidate.matched_slot_ids]))
        existing.matched_slot_ids = matched
        existing.raw_similarity_score = max(existing.raw_similarity_score, candidate.raw_similarity_score)
        existing.metadata.update(candidate.metadata)
    return list(by_id.values())


def evidence_from_text(
    *,
    source_type: str,
    title: str,
    content: str,
    matched_slot_ids: Sequence[str],
    raw_similarity_score: float,
    verification_level: str = "unknown",
    source_ref: str = "",
    metadata: dict[str, Any] | None = None,
) -> CandidateEvidence:
    return CandidateEvidence(
        evidence_id=stable_id(source_type, title, source_ref, content[:256]),
        source_type=source_type,  # type: ignore[arg-type]
        title=title,
        content=content,
        matched_slot_ids=tuple(dict.fromkeys(matched_slot_ids)),
        raw_similarity_score=max(0.0, min(float(raw_similarity_score), 1.0)),
        verification_level=verification_level,  # type: ignore[arg-type]
        source_ref=source_ref,
        metadata=dict(metadata or {}),
    )
