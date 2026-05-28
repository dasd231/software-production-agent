from __future__ import annotations

import re
from typing import Any

from agent.context_pv.placement import consistent_hash_bucket
from agent.context_pv.schema import ContextPVPolicy, ContextSlice, SlicePlacement
from agent.context_pv.slicer import estimate_tokens


def _query_terms(query: str) -> set[str]:
    return {item.lower() for item in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", query)}


def query_semantic_label(query: str) -> str:
    low = query.lower()
    if any(word in low for word in ("code", "function", "class", "api", "traceback", "error", "函数", "代码", "接口")):
        return "code"
    if any(word in low for word in ("metric", "benchmark", "指标", "对比", "表格")):
        return "table"
    if any(word in low for word in ("summary", "overview", "architecture", "摘要", "架构", "概览")):
        return "summary"
    return "prose"


def build_global_index(
    slices: list[ContextSlice],
    placements: list[SlicePlacement],
    *,
    policy: ContextPVPolicy | None = None,
) -> dict[str, Any]:
    active_policy = (policy or ContextPVPolicy()).normalized()
    by_label: dict[str, list[str]] = {}
    by_pvc: dict[str, list[str]] = {}
    token_ranges: list[dict[str, Any]] = []
    checksums: dict[str, str] = {}
    placement_by_slice = {item.slice_id: item for item in placements}

    for slice_obj in slices:
        by_label.setdefault(slice_obj.semantic_label, []).append(slice_obj.slice_id)
        placement = placement_by_slice.get(slice_obj.slice_id)
        if placement:
            by_pvc.setdefault(placement.pvc_name, []).append(slice_obj.slice_id)
        token_ranges.append(
            {
                "slice_id": slice_obj.slice_id,
                "ordinal": slice_obj.ordinal,
                "token_start": slice_obj.token_start,
                "token_end": slice_obj.token_end,
                "semantic_label": slice_obj.semantic_label,
                "critical": slice_obj.critical,
            }
        )
        checksums[slice_obj.slice_id] = slice_obj.checksum

    return {
        "schema": "context_pv.index.v1",
        "routing": {
            "type": "semantic_label_plus_consistent_hash",
            "hash_buckets_per_tier": dict(active_policy.pvc_count_per_tier),
            "query_tokenizer": "dependency_free_regex",
        },
        "by_label": by_label,
        "by_pvc": by_pvc,
        "token_ranges": token_ranges,
        "checksums": checksums,
    }


def route_query_to_slices(
    query: str,
    slices: list[ContextSlice],
    placements: list[SlicePlacement],
    *,
    policy: ContextPVPolicy | None = None,
    token_budget: int | None = None,
    route_plan: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    active_policy = (policy or ContextPVPolicy()).normalized()
    desired_label = query_semantic_label(query)
    terms = _query_terms(query)
    placement_by_slice = {item.slice_id: item for item in placements}
    routed: list[dict[str, Any]] = []

    for slice_obj in slices:
        text_low = slice_obj.text.lower()
        term_hits = sorted(term for term in terms if term in text_low)
        score = float(len(term_hits) * 4)
        reasons: list[str] = []
        if term_hits:
            reasons.append(f"term_hits={','.join(term_hits[:4])}")
        if slice_obj.semantic_label == desired_label:
            score += 5
            reasons.append(f"semantic_label={desired_label}")
        if slice_obj.critical:
            score += 1.5
            reasons.append("critical_slice")
        if slice_obj.ordinal == 0:
            score += 1
            reasons.append("entry_slice")
        if not query.strip() and slice_obj.critical:
            score += 3
            reasons.append("no_query_use_critical")

        placement = placement_by_slice.get(slice_obj.slice_id)
        if placement:
            bucket_count = active_policy.pvc_count_per_tier.get(placement.pv_tier, 1)
            query_bucket = consistent_hash_bucket(query or desired_label, bucket_count)
            pvc_bucket = int(placement.pvc_name.rsplit("-", 1)[-1]) if "-" in placement.pvc_name else -1
            if query_bucket == pvc_bucket:
                score += 0.5
                reasons.append("consistent_hash_bucket")

        if score > 0:
            routed.append(
                {
                    "slice_id": slice_obj.slice_id,
                    "ordinal": slice_obj.ordinal,
                    "score": round(score, 3),
                    "semantic_label": slice_obj.semantic_label,
                    "token_range": [slice_obj.token_start, slice_obj.token_end],
                    "pvc_name": placement.pvc_name if placement else "",
                    "pv_tier": placement.pv_tier if placement else "",
                    "estimated_tokens": estimate_tokens(slice_obj.text),
                    "reason": reasons,
                }
            )

    routed.sort(key=lambda item: (-float(item["score"]), int(item["ordinal"])))
    if not routed and slices:
        routed.append(
            {
                "slice_id": slices[0].slice_id,
                "ordinal": slices[0].ordinal,
                "score": 1.0,
                "semantic_label": slices[0].semantic_label,
                "token_range": [slices[0].token_start, slices[0].token_end],
                "pvc_name": placement_by_slice.get(slices[0].slice_id).pvc_name if placement_by_slice.get(slices[0].slice_id) else "",
                "pv_tier": placement_by_slice.get(slices[0].slice_id).pv_tier if placement_by_slice.get(slices[0].slice_id) else "",
                "estimated_tokens": estimate_tokens(slices[0].text),
                "reason": ["fallback_entry_slice"],
            }
        )
    limited = routed[: active_policy.route_top_k]
    budget = token_budget
    if budget is None and isinstance(route_plan, dict):
        context_budget = route_plan.get("context_budget") if isinstance(route_plan.get("context_budget"), dict) else {}
        raw_budget = context_budget.get("available_context_tokens")
        if isinstance(raw_budget, (int, float)):
            budget = int(raw_budget)
    if budget is None:
        for item in limited:
            item["budget_decision"] = {"included": True, "reason": "no_budget_limit"}
        return limited

    max_budget = max(int(budget), 0)
    selected: list[dict[str, Any]] = []
    used = 0
    dropped = 0
    for item in limited:
        item_tokens = int(item.get("estimated_tokens", 0) or 0)
        if item_tokens <= max(max_budget - used, 0):
            used += item_tokens
            item["budget_decision"] = {
                "included": True,
                "used_tokens_after": used,
                "budget_tokens": max_budget,
                "reason": "within_route_budget",
            }
            selected.append(item)
        else:
            dropped += 1
    if not selected and limited:
        fallback = limited[0]
        fallback["budget_decision"] = {
            "included": True,
            "used_tokens_after": int(fallback.get("estimated_tokens", 0) or 0),
            "budget_tokens": max_budget,
            "reason": "fallback_best_slice_even_when_over_budget",
        }
        selected.append(fallback)
        dropped = max(0, dropped - 1)
    for item in selected:
        item.setdefault("budget_summary", {})["dropped_candidate_slices"] = dropped
    return selected
