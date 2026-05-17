"""Compact context hints for Brain and Planner payloads.

函数流程图：
    build_context_digest(structure)
      -> 提取 skill_hints / rag_hints / mcp_capabilities
      -> _compact_rag_hint() 裁剪 RAG 字段
      -> _compact_decision_policy() 裁剪策略建议和策略记忆
      -> summary 记录 total/included/omitted
      -> 返回 Brain/Planner 可消费的小 payload

你可以继续练算法/工程化的点：
    1. token budget：当前固定 TopN；可以按模型上下文预算动态分配。
    2. rerank：当前按上游顺序裁剪；可以按阶段、失败类型和 reward 重新排序。
    3. decision features：当前保留策略摘要和 bandit 选择器摘要；后续可加入可解释 feature importance。
    4. schema：当前宽松 dict；可以为 context_digest 定义版本化 DTO。
"""

from __future__ import annotations

from typing import Any

#上下文压缩器
#安全非负整数转换，处理rag脏数据
def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0

def _safe_float(value: Any) -> float:
    try:
        out = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out and out not in (float("inf"), float("-inf")) else 0.0

#安全字符串列表截取
def _string_list(value: Any, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x) for x in value[:limit]]

#RAG提示压缩，保留关键信息并限制长度
def _compact_rag_hint(hint: Any) -> Any:
    if not isinstance(hint, dict):
        return str(hint)[:200]
    out: dict[str, Any] = {
        "path": str(hint.get("path", "")),
        "line_start": _safe_int(hint.get("line_start")),
        "line_end": _safe_int(hint.get("line_end")),
        "score": _safe_float(hint.get("score")),
        "overlap_tokens": _string_list(hint.get("overlap_tokens"), 8),
        "line_overlap_tokens": _string_list(hint.get("line_overlap_tokens"), 8),
        "size_bytes": _safe_int(hint.get("size_bytes")),
        "preview": str(hint.get("preview", ""))[:260],
    }
    for key, limit in (
        ("source", 40),
        ("source_run", 80),
        ("retrieval_mode", 80),
    ):
        value = str(hint.get(key, "") or "").strip()
        if value:
            out[key] = value[:limit]
    if "confidence" in hint:
        out["confidence"] = _safe_float(hint.get("confidence"))
    if hint.get("truncated"):
        out["truncated"] = True
    return out

def _truncated_rag_count(rag_hints: list[Any]) -> int:
    count = 0
    for hint in rag_hints:
        if isinstance(hint, dict) and hint.get("truncated"):
            count += 1
    return count


def _rag_source_counts(rag_hints: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hint in rag_hints:
        if not isinstance(hint, dict):
            continue
        source = str(hint.get("source", "local_workspace") or "local_workspace")
        counts[source] = counts.get(source, 0) + 1
    return counts


def _summary_row(total: int, included: int) -> dict[str, int]:
    return {
        "total": total,
        "included": included,
        "omitted": max(0, total - included),
    }


def _compact_decision_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict):
        return {}
    candidates = policy.get("candidate_actions") if isinstance(policy.get("candidate_actions"), list) else []
    compact_candidates: list[dict[str, Any]] = []
    for row in candidates[:4]:
        if not isinstance(row, dict):
            continue
        compact_candidates.append(
            {
                "action": str(row.get("action", "")),
                "score": row.get("score", 0.0),
                "reason": str(row.get("reason", ""))[:160],
                "args_hint": row.get("args_hint", {}) if isinstance(row.get("args_hint", {}), dict) else {},
                "memory_adjustment": row.get("memory_adjustment", 0.0),
                "bandit_score": row.get("bandit_score", 0.0),
                "bandit_bonus": row.get("bandit_bonus", 0.0),
                "bandit_attempts": _safe_int(row.get("bandit_attempts")),
            }
        )
    features = policy.get("features") if isinstance(policy.get("features"), dict) else {}
    memory = policy.get("policy_memory") if isinstance(policy.get("policy_memory"), dict) else {}
    selector = policy.get("selector") if isinstance(policy.get("selector"), dict) else {}
    values = memory.get("action_values") if isinstance(memory.get("action_values"), list) else []
    return {
        "policy_version": str(policy.get("policy_version", "")),
        "strategy": str(policy.get("strategy", "")),
        "selected_action": str(policy.get("selected_action", "")),
        "selected_score": policy.get("selected_score", 0.0),
        "selected_bandit_score": policy.get("selected_bandit_score", 0.0),
        "reason": str(policy.get("reason", ""))[:200],
        "selector": {
            "selector_version": str(selector.get("selector_version", "")),
            "algorithm": str(selector.get("algorithm", "")),
            "selected_action": str(selector.get("selected_action", "")),
            "selected_bandit_score": selector.get("selected_bandit_score", 0.0),
            "total_count": _safe_int(selector.get("total_count")),
        },
        "features": {
            "stage": str(features.get("stage", "")),
            "progress": str(features.get("progress", "")),
            "recent_error_count": _safe_int(features.get("recent_error_count")),
            "command_failures": _safe_int(features.get("command_failures")),
            "rag_hit_count": _safe_int(features.get("rag_hit_count")),
            "tests_count": _safe_int(features.get("tests_count")),
            "mcp_tool_count": _safe_int(features.get("mcp_tool_count")),
            "last_command_failed": bool(features.get("last_command_failed", False)),
        },
        "policy_memory": {
            "applied": bool(memory.get("applied", False)),
            "action_values": [x for x in values[:4] if isinstance(x, dict)],
        },
        "candidate_actions": compact_candidates,
    }


#构建上下文摘要，提取和压缩技能提示、RAG提示、MCP能力和策略建议
def build_context_digest(structure: dict[str, Any]) -> dict[str, Any]:
    skill_hints = (
        structure.get("skill_hints") if isinstance(structure.get("skill_hints"), list) else []
    )
    rag_hints = structure.get("rag_hints") if isinstance(structure.get("rag_hints"), list) else []
    mcp_caps = (
        structure.get("mcp_capabilities")
        if isinstance(structure.get("mcp_capabilities"), list)
        else []
    )
    decision_policy = structure.get("decision_policy") if isinstance(structure.get("decision_policy"), dict) else {}
    skill_included = min(len(skill_hints), 3)
    rag_included = min(len(rag_hints), 3)
    mcp_included = min(len(mcp_caps), 5)
    return {
        "skill_hints": [str(x) for x in skill_hints[:skill_included]],
        "rag_hints": [_compact_rag_hint(x) for x in rag_hints[:rag_included]],
        "mcp_capabilities": mcp_caps[:mcp_included],
        "decision_policy": _compact_decision_policy(decision_policy),
        "summary": {
            "skill_hints": _summary_row(len(skill_hints), skill_included),
            "rag_hints": _summary_row(len(rag_hints), rag_included),
            "mcp_capabilities": _summary_row(len(mcp_caps), mcp_included),
            "decision_policy": _summary_row(1 if decision_policy else 0, 1 if decision_policy else 0),
            "rag_truncated": _truncated_rag_count(rag_hints),
            "rag_sources": _rag_source_counts(rag_hints),
        },
    }
