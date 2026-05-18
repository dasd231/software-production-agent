"""Persistent feedback ledgers for research quality and accepted solutions."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from agent.chains.research_types import (
    RAGHint,
    RetrievalFeedbackPolicy,
    SolutionHit,
    SourceConfidenceEntry,
    SourceConfidenceProfile,
    WebResult,
)

RESEARCH_FEEDBACK_SCHEMA = "research_feedback_event.v1"
SOLUTION_ACCEPTANCE_SCHEMA = "solution_acceptance_event.v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _feedback_dir(workspace: Path) -> Path:
    return workspace / ".agent_feedback"


def _append_jsonl(path: Path, row: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def append_research_feedback(
    workspace: Path,
    *,
    query: str,
    evaluation: dict[str, Any],
    trace: dict[str, Any],
    solution_hits: list[SolutionHit],
    rag_hints: list[RAGHint],
    web_results: list[WebResult],
) -> Path:
    """Persist one research synthesis outcome for later offline review."""

    summary = evaluation.get("summary") if isinstance(evaluation.get("summary"), dict) else {}
    row = {
        "schema": RESEARCH_FEEDBACK_SCHEMA,
        "created_at": _now(),
        "query": query,
        "evaluation_score": evaluation.get("overall_score"),
        "evaluation_grade": evaluation.get("grade"),
        "solution_hit_count": len(solution_hits),
        "rag_hit_count": len(rag_hints),
        "web_hit_count": len(web_results),
        "llm_ok": bool(trace.get("llm_ok", False)),
        "labels_missing": list(summary.get("labels_missing", [])) if isinstance(summary.get("labels_missing"), list) else [],
        "evidence_decision": (
            (trace.get("evidence_policy") or {}).get("decision")
            if isinstance(trace.get("evidence_policy"), dict)
            else ""
        ),
    }
    return _append_jsonl(_feedback_dir(workspace) / "research_feedback.jsonl", row)


def append_solution_acceptance_feedback(
    workspace: Path,
    *,
    published_dir: Path,
    manifest: dict[str, Any],
) -> Path:
    """Persist the user/operator acceptance event that promoted a run into the library."""

    row = {
        "schema": SOLUTION_ACCEPTANCE_SCHEMA,
        "created_at": _now(),
        "source_workspace": str(workspace),
        "published_dir": str(published_dir),
        "template": str(manifest.get("template", "") or ""),
        "acceptance_status": str(manifest.get("acceptance_status", "") or ""),
        "accepted_at": str(manifest.get("accepted_at", "") or ""),
        "accepted_by": str(manifest.get("accepted_by", "") or ""),
        "training_eligible": bool(manifest.get("training_eligible", False)),
    }
    return _append_jsonl(_feedback_dir(workspace) / "solution_acceptance.jsonl", row)


def build_solution_acceptance_index(roots: Iterable[Path]) -> dict[str, dict[str, dict[str, Any]]]:
    """Build transparent acceptance aggregates for later retrieval reranking."""

    rows = _load_jsonl(_iter_feedback_files(roots, "solution_acceptance.jsonl"))
    by_published_dir: dict[str, dict[str, Any]] = {}
    by_template: dict[str, dict[str, Any]] = {}

    def _update(bucket: dict[str, dict[str, Any]], key: str, row: dict[str, Any]) -> None:
        if not key:
            return
        item = bucket.setdefault(
            key,
            {
                "accepted_count": 0,
                "last_accepted_at": "",
                "accepted_by": [],
            },
        )
        item["accepted_count"] = int(item.get("accepted_count", 0) or 0) + 1
        accepted_at = str(row.get("accepted_at", "") or row.get("created_at", "") or "")
        if accepted_at and accepted_at > str(item.get("last_accepted_at", "") or ""):
            item["last_accepted_at"] = accepted_at
        accepted_by = str(row.get("accepted_by", "") or "")
        people = [str(x) for x in item.get("accepted_by", []) if str(x)]
        if accepted_by and accepted_by not in people:
            people.append(accepted_by)
        item["accepted_by"] = people

    for row in rows:
        published_dir = str(row.get("published_dir", "") or "")
        if published_dir:
            try:
                published_dir = str(Path(published_dir).resolve())
            except OSError:
                pass
        _update(by_published_dir, published_dir, row)
        _update(by_template, str(row.get("template", "") or ""), row)
    return {
        "by_published_dir": by_published_dir,
        "by_template": by_template,
    }


def _iter_feedback_files(roots: Iterable[Path], name: str) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for raw_root in roots:
        root = Path(raw_root)
        if not root.exists():
            continue
        candidates = [root] if root.name == name and root.is_file() else list(root.rglob(name))
        for path in candidates:
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            files.append(path)
    return files


def _load_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(raw, dict):
                rows.append(raw)
    return rows


def _score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _low_score_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if int(row.get("solution_hit_count", 0) or 0) <= 0:
        reasons.append("no_solution_hit")
    if int(row.get("rag_hit_count", 0) or 0) <= 0:
        reasons.append("no_rag_hit")
    if row.get("labels_missing"):
        reasons.append("citation_gap")
    if str(row.get("evidence_decision", "")) == "web_only_requires_verification":
        reasons.append("web_only")
    if row.get("llm_ok") is False:
        reasons.append("llm_not_used_or_failed")
    return reasons


def _research_rows(roots: Iterable[Path]) -> list[dict[str, Any]]:
    return _load_jsonl(_iter_feedback_files(roots, "research_feedback.jsonl"))


def build_retrieval_feedback_policy(
    roots: Iterable[Path],
    *,
    low_score_threshold: float = 6.5,
) -> RetrievalFeedbackPolicy:
    """Turn historical misses into transparent, bounded retrieval adjustments."""

    rows = _research_rows(roots)
    low_rows = [row for row in rows if _score(row.get("evaluation_score")) < low_score_threshold]
    miss_rows = [row for row in low_rows if int(row.get("solution_hit_count", 0) or 0) <= 0]
    miss_rate = round(len(miss_rows) / len(low_rows), 4) if low_rows else 0.0
    keyword_weight = 0.72
    semantic_weight = 0.28
    min_semantic_similarity = 0.18
    semantic_candidate_multiplier = 3
    manifest_limit = 120
    reason = "baseline"
    if len(low_rows) >= 3 and miss_rate >= 0.5:
        keyword_weight = 0.58
        semantic_weight = 0.42
        min_semantic_similarity = 0.12
        semantic_candidate_multiplier = 5
        manifest_limit = 240
        reason = "high_solution_miss_rate"
    elif len(low_rows) >= 3 and miss_rate >= 0.25:
        keyword_weight = 0.66
        semantic_weight = 0.34
        min_semantic_similarity = 0.15
        semantic_candidate_multiplier = 4
        manifest_limit = 180
        reason = "moderate_solution_miss_rate"
    return {
        "keyword_weight": keyword_weight,
        "semantic_weight": semantic_weight,
        "min_semantic_similarity": min_semantic_similarity,
        "semantic_candidate_multiplier": semantic_candidate_multiplier,
        "manifest_limit": manifest_limit,
        "reason": reason,
        "history_samples": len(rows),
        "low_score_samples": len(low_rows),
        "no_solution_hit_rate": miss_rate,
    }


def _source_confidence_entry(
    rows: list[dict[str, Any]],
    *,
    count_key: str,
    prior: float,
    threshold: float,
    basis: str,
) -> SourceConfidenceEntry:
    relevant = [row for row in rows if int(row.get(count_key, 0) or 0) > 0]
    successes = sum(1 for row in relevant if _score(row.get("evaluation_score")) >= threshold)
    # Keep small histories from swinging the platform wildly: two pseudo-observations
    # encode the hand-authored prior, then real outcomes take over gradually.
    score = ((prior * 2.0) + successes) / (2.0 + len(relevant))
    return {
        "score": round(score, 4),
        "basis": basis if relevant else "prior_only",
        "history_samples": len(relevant),
        "successes": successes,
    }


def build_source_confidence_profile(
    roots: Iterable[Path],
    *,
    success_threshold: float = 6.5,
) -> SourceConfidenceProfile:
    rows = _research_rows(roots)
    return {
        "solution_library": _source_confidence_entry(
            rows,
            count_key="solution_hit_count",
            prior=0.95,
            threshold=success_threshold,
            basis="historical_success_rate_with_prior",
        ),
        "local_rag": _source_confidence_entry(
            rows,
            count_key="rag_hit_count",
            prior=0.9,
            threshold=success_threshold,
            basis="historical_success_rate_with_prior",
        ),
        "web": _source_confidence_entry(
            rows,
            count_key="web_hit_count",
            prior=0.65,
            threshold=success_threshold,
            basis="historical_success_rate_with_prior",
        ),
    }


def build_research_feedback_report(
    roots: Iterable[Path],
    *,
    low_score_threshold: float = 6.5,
) -> dict[str, Any]:
    """Summarize persisted feedback into an operator-facing offline review report."""

    research_rows = _research_rows(roots)
    acceptance_rows = _load_jsonl(_iter_feedback_files(roots, "solution_acceptance.jsonl"))
    low_rows = [row for row in research_rows if _score(row.get("evaluation_score")) < low_score_threshold]
    reason_counts: Counter[str] = Counter()
    for row in low_rows:
        reason_counts.update(_low_score_reasons(row))
    event_count = len(research_rows)
    solution_hit_rate = (
        round(sum(1 for row in research_rows if int(row.get("solution_hit_count", 0) or 0) > 0) / event_count, 4)
        if event_count
        else 0.0
    )
    recommendations: list[dict[str, str]] = []
    if reason_counts.get("no_solution_hit", 0):
        recommendations.append(
            {
                "id": "review_solution_recall",
                "why": "低分查询里存在未命中正式方案库的样本。",
                "action": "复盘这些 query，补充验收方案或调优方案库混合召回权重。",
            }
        )
    if reason_counts.get("no_rag_hit", 0):
        recommendations.append(
            {
                "id": "review_local_rag",
                "why": "低分查询里存在本地/RAG 证据缺失。",
                "action": "检查 workspace 索引覆盖和 learning store 是否过旧。",
            }
        )
    if reason_counts.get("citation_gap", 0):
        recommendations.append(
            {
                "id": "tighten_citation_policy",
                "why": "部分答案没有覆盖应有的证据标签。",
                "action": "继续压实综合 prompt，并把缺失标签样本加入回归集。",
            }
        )
    if reason_counts.get("web_only", 0):
        recommendations.append(
            {
                "id": "curate_local_assets",
                "why": "部分问题仍只能依赖 Web。",
                "action": "优先把高频 Web-only 问题沉淀为本地知识或验收方案。",
            }
        )
    retrieval_policy = build_retrieval_feedback_policy(roots, low_score_threshold=low_score_threshold)
    source_confidence = build_source_confidence_profile(roots, success_threshold=low_score_threshold)
    return {
        "schema": "research_feedback_report.v1",
        "summary": {
            "research_events": event_count,
            "accepted_solutions": len(acceptance_rows),
            "low_score_threshold": low_score_threshold,
            "low_score_events": len(low_rows),
            "solution_hit_rate": solution_hit_rate,
        },
        "low_score_reason_counts": dict(sorted(reason_counts.items())),
        "low_score_queries": [
            {
                "query": str(row.get("query", "")),
                "evaluation_score": row.get("evaluation_score"),
                "evaluation_grade": row.get("evaluation_grade"),
                "reasons": _low_score_reasons(row),
            }
            for row in low_rows[:20]
        ],
        "retrieval_policy": retrieval_policy,
        "source_confidence": source_confidence,
        "recommendations": recommendations,
    }
