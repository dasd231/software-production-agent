"""Discovery, ranking and routing primitives for GitHub corpus intake."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


_STOPWORDS = {
    "a",
    "an",
    "and",
    "api",
    "app",
    "for",
    "from",
    "github",
    "how",
    "in",
    "of",
    "on",
    "project",
    "repo",
    "repository",
    "the",
    "to",
    "with",
}


@dataclass(frozen=True)
class RankingWeights:
    """Transparent v1 weights for corpus candidate recommendation."""

    lexical_relevance: float = 0.22
    repo_quality: float = 0.24
    freshness: float = 0.10
    governance: float = 0.14
    novelty: float = 0.14
    downstream_utility: float = 0.16

    def to_dict(self) -> dict[str, float]:
        return {
            "lexical_relevance": self.lexical_relevance,
            "repo_quality": self.repo_quality,
            "freshness": self.freshness,
            "governance": self.governance,
            "novelty": self.novelty,
            "downstream_utility": self.downstream_utility,
        }


DEFAULT_WEIGHTS = RankingWeights()


def _tokens(text: str) -> list[str]:
    return [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}", str(text or ""))
        if token.lower() not in _STOPWORDS
    ]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _bounded(value: float) -> float:
    return max(0.0, min(round(float(value), 4), 10.0))


def _query_facets(seed_queries: list[str], web_results: list[dict[str, Any]]) -> list[str]:
    counts: Counter[str] = Counter()
    for query in seed_queries:
        counts.update(_tokens(query))
    for row in web_results:
        if not isinstance(row, dict):
            continue
        counts.update(_tokens(str(row.get("title", ""))))
        counts.update(_tokens(str(row.get("snippet", ""))))
    return [
        token
        for token, _ in counts.most_common()
        if token not in {part for query in seed_queries for part in _tokens(query)}
    ]


def build_github_query_plan(
    *,
    seed_queries: list[str] | tuple[str, ...],
    web_results: list[dict[str, Any]] | None = None,
    max_queries: int = 12,
) -> dict[str, Any]:
    """Build a diverse GitHub query plan from operator seeds plus WebSearch hints.

    v1 is intentionally transparent:
    - keep seed queries as exploitation arms;
    - derive facet terms from WebSearch titles/snippets;
    - greedily keep queries that add lexical diversity (MMR-style, not ML-heavy).
    """

    normalized_seeds = [str(query).strip() for query in seed_queries if str(query).strip()]
    web_rows = [row for row in (web_results or []) if isinstance(row, dict)]
    facets = _query_facets(normalized_seeds, web_rows)
    candidates: list[dict[str, Any]] = []
    for query in normalized_seeds:
        candidates.append(
            {
                "query": query,
                "kind": "seed",
                "source": "operator",
                "base_score": 10.0,
                "tokens": sorted(set(_tokens(query))),
            }
        )
    for seed in normalized_seeds:
        for facet in facets[: max(int(max_queries), 1)]:
            query = f"{seed} {facet}".strip()
            candidates.append(
                {
                    "query": query,
                    "kind": "web_expansion",
                    "source": "web_search",
                    "base_score": 7.5,
                    "tokens": sorted(set(_tokens(query))),
                    "facet": facet,
                }
            )

    selected: list[dict[str, Any]] = []
    seen_queries: set[str] = set()
    pool = [row for row in candidates if row["query"].lower() not in seen_queries]
    while pool and len(selected) < max(int(max_queries), 1):
        best_row: dict[str, Any] | None = None
        best_score = -math.inf
        for row in pool:
            token_set = set(row["tokens"])
            redundancy = max((_jaccard(token_set, set(item["tokens"])) for item in selected), default=0.0)
            score = float(row["base_score"]) - redundancy * 3.0
            if score > best_score:
                best_row = row
                best_score = score
        assert best_row is not None
        best_row = dict(best_row)
        best_row["selection_score"] = round(best_score, 4)
        selected.append(best_row)
        seen_queries.add(best_row["query"].lower())
        pool = [row for row in pool if row["query"].lower() not in seen_queries]

    return {
        "schema": "github_query_plan.v1",
        "algorithm": {
            "name": "seed_plus_web_facets_with_mmr_style_diversification",
            "seed_queries": len(normalized_seeds),
            "web_results": len(web_rows),
            "facet_count": len(facets),
        },
        "queries": [{key: value for key, value in row.items() if key != "tokens"} for row in selected],
    }


def _parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _freshness_score(repo: dict[str, Any], *, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    actual = _parse_dt(str(repo.get("pushed_at", "") or repo.get("updated_at", "")))
    if actual is None:
        return 3.0
    age_days = max((now - actual).days, 0)
    if age_days <= 30:
        return 10.0
    if age_days <= 180:
        return 8.0
    if age_days <= 365:
        return 6.0
    if age_days <= 730:
        return 4.0
    return 2.0


def _lexical_relevance_score(query: str, profile: dict[str, Any], web_terms: set[str]) -> float:
    repo = profile.get("repo") if isinstance(profile.get("repo"), dict) else {}
    arch = profile.get("architecture") if isinstance(profile.get("architecture"), dict) else {}
    text = " ".join(
        [
            query,
            str(repo.get("full_name", "")),
            str(repo.get("description", "")),
            " ".join(str(item) for item in repo.get("topics", []) if str(item)),
            " ".join(str(item) for item in arch.get("tags", []) if str(item)),
        ]
    )
    query_tokens = set(_tokens(query))
    repo_tokens = set(_tokens(text))
    direct = len(query_tokens & repo_tokens) / len(query_tokens) if query_tokens else 0.0
    web_alignment = len(web_terms & repo_tokens) / len(web_terms) if web_terms else 0.0
    return _bounded((direct * 0.75 + web_alignment * 0.25) * 10.0)


def _governance_score(repo: dict[str, Any], allowed_licenses: set[str]) -> tuple[float, list[str]]:
    license_id = str(repo.get("license_spdx", "") or "").strip()
    gates: list[str] = []
    if not license_id:
        gates.append("missing_license")
        return 0.0, gates
    if license_id.upper() == "LOCAL":
        return 10.0, gates
    if allowed_licenses and license_id.lower() not in allowed_licenses:
        gates.append("license_not_allowlisted")
        return 1.0, gates
    return 10.0, gates


def _novelty_scores(profiles: list[dict[str, Any]], seen_full_names: set[str]) -> dict[str, float]:
    shape_counts: Counter[str] = Counter()
    for profile in profiles:
        arch = profile.get("architecture") if isinstance(profile.get("architecture"), dict) else {}
        shape_counts[str(arch.get("shape", "unknown") or "unknown")] += 1
    max_count = max(shape_counts.values(), default=1)
    out: dict[str, float] = {}
    for profile in profiles:
        repo = profile.get("repo") if isinstance(profile.get("repo"), dict) else {}
        arch = profile.get("architecture") if isinstance(profile.get("architecture"), dict) else {}
        full_name = str(repo.get("full_name", "") or "")
        shape = str(arch.get("shape", "unknown") or "unknown")
        duplicate_penalty = 0.0 if full_name and full_name not in seen_full_names else 5.0
        inverse_frequency = 10.0 * (1.0 - ((shape_counts.get(shape, 1) - 1) / max_count))
        out[full_name] = _bounded(inverse_frequency - duplicate_penalty)
    return out


def _downstream_score(tags: list[str], feedback_by_tag: dict[str, float]) -> float:
    values = [
        float(feedback_by_tag[tag])
        for tag in tags
        if tag in feedback_by_tag and isinstance(feedback_by_tag[tag], (int, float))
    ]
    if not values:
        return 5.0
    return _bounded(sum(values) / len(values))


def _route_row(
    *,
    score: float,
    quality: float,
    novelty: float,
    gates: list[str],
    min_quality: float,
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    if gates:
        return ["quarantine"], gates
    routes: list[str] = []
    if quality >= max(min_quality, 7.0) and score >= 7.0:
        routes.append("train_now")
        reasons.append("high_score_high_quality")
    if quality >= min_quality and score >= 6.2:
        routes.append("distill_pool")
        reasons.append("suitable_for_teacher_supervision")
    if quality >= 7.5 and novelty >= 7.0:
        routes.append("benchmark_holdout")
        reasons.append("high_quality_novel_slice")
    if not routes:
        routes.append("observe")
        reasons.append("insufficient_current_priority")
    return routes, reasons


def rank_repo_profiles(
    *,
    query: str,
    profiles: list[dict[str, Any]],
    web_results: list[dict[str, Any]] | None = None,
    feedback_by_tag: dict[str, float] | None = None,
    seen_full_names: set[str] | None = None,
    allowed_licenses: set[str] | None = None,
    min_quality: float = 6.5,
    weights: RankingWeights = DEFAULT_WEIGHTS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rank profiled repositories and explain their downstream routing."""

    feedback = feedback_by_tag or {}
    seen = seen_full_names or set()
    allow = {item.lower() for item in (allowed_licenses or set()) if str(item).strip()}
    web_terms = {
        token
        for row in (web_results or [])
        if isinstance(row, dict)
        for token in _tokens(f"{row.get('title', '')} {row.get('snippet', '')}")
    }
    novelty_scores = _novelty_scores(profiles, seen)
    rows: list[dict[str, Any]] = []
    for profile in profiles:
        repo = profile.get("repo") if isinstance(profile.get("repo"), dict) else {}
        quality = profile.get("quality") if isinstance(profile.get("quality"), dict) else {}
        arch = profile.get("architecture") if isinstance(profile.get("architecture"), dict) else {}
        tags = [str(item) for item in profile.get("training_tags", []) if str(item)]
        if not tags:
            tags = [str(item) for item in arch.get("tags", []) if str(item)]
        full_name = str(repo.get("full_name", "") or "")
        governance, gates = _governance_score(repo, allow)
        quality_score = _bounded(float(quality.get("score", 0.0) or 0.0))
        novelty = novelty_scores.get(full_name, 0.0)
        components = {
            "lexical_relevance": _lexical_relevance_score(query, profile, web_terms),
            "repo_quality": quality_score,
            "freshness": _bounded(_freshness_score(repo, now=now)),
            "governance": _bounded(governance),
            "novelty": novelty,
            "downstream_utility": _downstream_score(tags, feedback),
        }
        if quality_score < min_quality:
            gates.append("below_quality_threshold")
        weighted_score = sum(components[name] * weight for name, weight in weights.to_dict().items())
        score = _bounded(weighted_score)
        routes, route_reasons = _route_row(
            score=score,
            quality=quality_score,
            novelty=novelty,
            gates=gates,
            min_quality=min_quality,
        )
        rows.append(
            {
                "repo": full_name,
                "score": score,
                "components": components,
                "routes": routes,
                "route_reasons": route_reasons,
                "gates": gates,
                "tags": tags,
                "shape": str(arch.get("shape", "unknown") or "unknown"),
            }
        )
    rows.sort(key=lambda row: (-float(row["score"]), str(row["repo"])))
    route_counts: Counter[str] = Counter()
    for row in rows:
        route_counts.update(str(route) for route in row["routes"])
    return {
        "schema": "github_repo_ranking.v1",
        "algorithm": {
            "name": "transparent_multi_objective_ranker",
            "weights": weights.to_dict(),
            "hard_gates": ["missing_license", "license_not_allowlisted", "below_quality_threshold"],
        },
        "summary": {
            "candidates": len(rows),
            "route_counts": dict(route_counts),
        },
        "rows": rows,
    }
