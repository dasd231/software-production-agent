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
    hybrid_score: float


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
    evidence_policy: dict[str, Any]
    llm_trace: dict[str, Any]
