"""Evaluation for research synthesis over solution library, RAG, Web and LLM."""

from __future__ import annotations

import re
from typing import Any

from agent.chains.research_types import RAGHint, SolutionHit, WebResult
from agent.evaluation.schemas import Metric, MetricReport


def _citation_rate(answer: str, prefixes: tuple[str, ...], counts: dict[str, int]) -> tuple[float, list[str], list[str]]:
    expected: list[str] = []
    for prefix in prefixes:
        for i in range(1, int(counts.get(prefix, 0)) + 1):
            expected.append(f"{prefix}{i}")
    if not expected:
        return 1.0, [], []
    found = set(re.findall(r"\[([SRW]\d+)\]", answer, flags=re.IGNORECASE))
    found = {item.upper() for item in found}
    missing = [item for item in expected if item not in found]
    return (len(expected) - len(missing)) / len(expected), sorted(found), missing


def _local_first_score(answer: str) -> float:
    s_pos = answer.find("[S")
    r_pos = answer.find("[R")
    w_pos = answer.find("[W")
    local_positions = [pos for pos in (s_pos, r_pos) if pos >= 0]
    if w_pos < 0:
        return 10.0
    if local_positions and min(local_positions) < w_pos:
        return 10.0
    return 4.0


def evaluate_research_synthesis(
    *,
    query: str,
    answer: str,
    solution_hits: list[SolutionHit],
    rag_hints: list[RAGHint],
    web_results: list[WebResult],
    trace: dict[str, Any],
) -> MetricReport:
    counts = {"S": len(solution_hits), "R": len(rag_hints), "W": len(web_results)}
    citation_rate, found, missing = _citation_rate(answer, ("S", "R", "W"), counts)
    web_enabled = bool(trace.get("web_enabled"))
    use_llm = ("llm_provider" in trace) or ("llm_error" in trace)
    llm_ok = bool(trace.get("llm_ok"))
    metrics = (
        Metric("solution_hit_count", counts["S"], 10.0 if counts["S"] else 0.0, weight=1.8),
        Metric("rag_hit_count", counts["R"], 10.0 if counts["R"] else 0.0, weight=1.8),
        Metric("web_hit_count", counts["W"], 10.0 if counts["W"] else 4.0 if not web_enabled else 0.0, weight=0.7),
        Metric("citation_label_coverage", round(citation_rate, 4), citation_rate * 10.0, weight=1.5, status="ok" if not missing else "missing_labels"),
        Metric("local_first", True, _local_first_score(answer), weight=1.0),
        Metric(
            "llm_synthesis",
            llm_ok if use_llm else "not_requested",
            10.0 if (llm_ok or not use_llm) else 3.0,
            weight=0.6,
            status="ok" if llm_ok else "not_requested" if not use_llm else "failed",
        ),
    )
    return MetricReport(
        stage="research.synthesis",
        metrics=metrics,
        summary={
            "query": query,
            "expected_labels": counts,
            "labels_found": found,
            "labels_missing": missing,
            "web_enabled": web_enabled,
            "llm_ok": llm_ok,
        },
    )
