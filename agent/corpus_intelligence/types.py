"""Typed contracts for the GitHub corpus control plane."""

from __future__ import annotations

from typing import TypedDict


class QueryStrategy(TypedDict, total=False):
    """How the next discovery round should alter query generation."""

    kind_score_adjustments: dict[str, float]
    promoted_facets: list[str]
    suppressed_facets: list[str]


class RankingStrategy(TypedDict, total=False):
    """How the next ranking round should alter scoring."""

    weights: dict[str, float]
    tag_utility: dict[str, float]


class RoutingStrategy(TypedDict, total=False):
    """How the next routing round should alter admission thresholds."""

    min_quality_delta: float
    grounding_required: bool


class CorpusStrategy(TypedDict):
    """Machine-consumable feedback output for the next crawl round."""

    schema: str
    mode: str
    query: QueryStrategy
    ranking: RankingStrategy
    routing: RoutingStrategy
    reasons: list[str]
