"""Typed contracts shared by the research chain and its support modules."""

from __future__ import annotations

from typing import Any, TypedDict


class SolutionScoreBreakdown(TypedDict):
    keyword_overlap: float
    keyword_points: float
    semantic_similarity: float
    semantic_points: float
    evidence_bonus: float
    feedback_bonus: float
    keyword_weight: float
    semantic_weight: float
    hybrid_score: float


class RetrievalFeedbackPolicy(TypedDict):
    keyword_weight: float
    semantic_weight: float
    min_semantic_similarity: float
    semantic_candidate_multiplier: int
    manifest_limit: int
    reason: str
    history_samples: int
    low_score_samples: int
    no_solution_hit_rate: float


class SolutionHit(TypedDict):
    source: str
    score: float
    retrieval_mode: str
    score_breakdown: SolutionScoreBreakdown
    manifest: str
    run_dir: str
    run_id: str
    goal: str
    stack: str
    template: str
    retrieval_tags: list[str]
    artifact_hints: list[str]
    matched_tokens: list[str]
    backup_path: str
    backup_preview: str
    acceptance_status: str
    accepted_by: str
    accepted_count: int
    last_accepted_at: str
    feedback_scope: str


class RAGHint(TypedDict, total=False):
    path: str
    line_start: int
    line_end: int
    score: float
    overlap_tokens: list[str]
    line_overlap_tokens: list[str]
    size_bytes: int
    truncated: bool
    preview: str
    source: str
    source_run: str
    source_dir: str
    confidence: float
    retrieval_mode: str


class WebResult(TypedDict):
    title: str
    url: str
    snippet: str
    source: str


class ResearchCachePayload(TypedDict):
    answer: str
    solution_hits: list[SolutionHit]
    rag_hints: list[RAGHint]
    rag_summary: dict[str, Any]
    web_results: list[WebResult]
    solution_retrieval: dict[str, Any]
    evidence_policy: dict[str, Any]
    llm_trace: dict[str, Any]


class SourceConfidenceEntry(TypedDict):
    score: float
    basis: str
    history_samples: int
    successes: int


class SourceConfidenceProfile(TypedDict):
    solution_library: SourceConfidenceEntry
    local_rag: SourceConfidenceEntry
    web: SourceConfidenceEntry


class ConflictDetail(TypedDict):
    type: str
    left_source: str
    right_source: str
    field: str
    left_values: list[str]
    right_values: list[str]
    mismatch_values: list[str]
    requires_manual_review: bool


class EvidencePolicy(TypedDict):
    source_order: list[str]
    decision: str
    local_evidence: int
    web_evidence: int
    conflicts: list[dict[str, Any]]
    conflict_details: list[ConflictDetail]
    source_confidence: SourceConfidenceProfile
    decision_rationale: str
    rules: list[str]
