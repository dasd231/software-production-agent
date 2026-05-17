"""Decision policy scoring: turn state/context into candidate action guidance.

函数流程图：
    evaluate_decision_policy(goal, plan, state)
      -> extract_policy_features()
          -> 从 ProjectState / structure / last_result 提取稳定特征
      -> _choose_strategy()
          -> repair / investigate / verify / ship / build / exploit
      -> _candidate_scores()
          -> 对候选 action 打分并写清 reason
      -> _apply_policy_memory()
          -> 用 ProjectState.policy.tool_success_stats 的 reward_avg 微调分数
      -> bandit.rank_candidates_with_ucb()
          -> 用 action value estimate + UCB 探索奖励重排候选动作
      -> 返回 decision_policy dict

    update_policy_state(policy_state, executed_action, reward_signal, decision)
      -> 更新 decision_count / reward_total / last_reward
      -> 更新 tool_success_stats[action]
      -> 更新 action_value_estimates[action].q
      -> 返回可序列化 PolicyState dict

你可以继续练算法/工程化的点：
    1. scorer：当前是启发式规则；可以替换为线性模型、树模型或学习到的 value function。
    2. exploration：当前接入 UCB1；可以继续实现 epsilon-greedy、Thompson sampling。
    3. feature：当前手工抽特征；可以加入项目类型、历史 passrate、工具时延、RAG 覆盖率。
    4. memory：当前用当前 ProjectState 的 reward_avg 调整动作分；可以落盘全局 policy memory 跨项目复用。
    5. 安全：policy 只能建议 action，不能执行；这个边界不要突破。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.decision.bandit import rank_candidates_with_ucb

POLICY_VERSION = "heuristic-v1"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _tool_names(caps: list[Any]) -> list[str]:
    out: list[str] = []
    for cap in caps:
        if not isinstance(cap, dict):
            continue
        tool = str(cap.get("tool", "")).strip()
        if tool:
            out.append(tool)
    return out


def _policy_state_from(state: Any) -> dict[str, Any]:
    policy = getattr(state, "policy", {})
    return policy if isinstance(policy, dict) else {}


def extract_policy_features(goal: str, plan: dict[str, Any], state: Any) -> dict[str, Any]:
    structure = _as_dict(getattr(state, "structure", {}))
    counters = _as_dict(getattr(state, "counters", {}))
    quality = _as_dict(getattr(state, "quality", {}))
    last_result = _as_dict(getattr(state, "last_result", {}))
    files = _as_list(getattr(state, "files", [])) or _as_list(structure.get("files", []))
    tests = _as_list(structure.get("tests", []))
    entrypoints = _as_list(structure.get("entrypoints", []))
    mcp_tools = _tool_names(_as_list(structure.get("mcp_capabilities", [])))
    errors = _as_list(getattr(state, "errors", []))
    progress = str(getattr(state, "progress", ""))
    current_stage = str(plan.get("stage") or getattr(state, "current_stage", ""))
    last_action = str(last_result.get("action", ""))
    last_ok = bool(last_result.get("ok", False)) if last_result else False
    return {
        "goal_chars": len(goal or ""),
        "stage": current_stage,
        "progress": progress,
        "files_count": len(files),
        "tests_count": len(tests),
        "entrypoints_count": len(entrypoints),
        "package_files_count": len(_as_list(structure.get("package_files", []))),
        "rag_hit_count": len(_as_list(structure.get("rag_hints", []))),
        "skill_hint_count": len(_as_list(structure.get("skill_hints", []))),
        "mcp_tool_count": len(mcp_tools),
        "mcp_tools": mcp_tools[:8],
        "has_workspace_search": "workspace.search" in mcp_tools,
        "recent_error_count": len(errors),
        "command_failures": _safe_int(counters.get("command_failures")),
        "fix_attempts": _safe_int(counters.get("fix_attempts")),
        "last_action": last_action,
        "last_ok": last_ok,
        "last_command_failed": last_action == "run_command" and last_result and not last_ok,
        "review_score": _safe_float(quality.get("review_score")),
        "health_score": _safe_float(quality.get("health_score")),
        "wtf_likelihood": _safe_int(quality.get("wtf_likelihood")),
    }


def _choose_strategy(features: dict[str, Any]) -> str:
    if _safe_int(features.get("command_failures")) >= 3:
        return "investigate"
    if _safe_int(features.get("recent_error_count")) > 0 or bool(features.get("last_command_failed")):
        return "repair"
    if str(features.get("stage")) == "ship":
        return "ship"
    if str(features.get("progress")) in ("run_ok", "production_check_ok") or _safe_int(features.get("tests_count")) > 0:
        return "verify"
    if _safe_int(features.get("files_count")) == 0:
        return "build"
    return "exploit"


def _candidate(action: str, score: float, reason: str, args_hint: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "action": action,
        "score": round(max(0.0, min(float(score), 1.0)), 3),
        "reason": reason,
        "args_hint": dict(args_hint or {}),
    }


def _candidate_scores(features: dict[str, Any], strategy: str) -> list[dict[str, Any]]:
    has_search = bool(features.get("has_workspace_search"))
    rag_hits = _safe_int(features.get("rag_hit_count"))
    tests = _safe_int(features.get("tests_count"))
    progress = str(features.get("progress", ""))
    candidates = [
        _candidate("workspace_index", 0.35, "refresh workspace structure before acting"),
        _candidate("read_file", 0.32, "inspect relevant files before editing"),
        _candidate("run_command", 0.42, "collect executable feedback from the workspace"),
        _candidate("production_check", 0.24, "verify compile/tests through the production checker", {"include_pytest": True}),
        _candidate("write_file", 0.30, "make a minimal implementation change"),
        _candidate("finish", 0.08, "finish only after verification and ship gate"),
    ]
    if has_search:
        candidates.append(
            _candidate(
                "mcp_call",
                0.34,
                "use workspace.search when direct context is weak",
                {"tool": "workspace.search", "args": {"query": "<goal-or-error>", "top_k": 3}},
            )
        )

    if strategy == "build":
        candidates.extend(
            [
                _candidate("write_file", 0.86, "workspace is empty or sparse; create the first implementation"),
                _candidate("workspace_index", 0.62, "confirm project shape before broad edits"),
            ]
        )
    elif strategy == "repair":
        candidates.extend(
            [
                _candidate("read_file", 0.82, "recent failure exists; inspect target code before changing it"),
                _candidate("run_command", 0.58, "rerun a narrow command after a minimal repair"),
            ]
        )
        if has_search:
            candidates.append(
                _candidate(
                    "mcp_call",
                    0.76 if rag_hits == 0 else 0.64,
                    "use workspace.search to localize the failing symbol or file",
                    {"tool": "workspace.search", "args": {"query": "<stderr-or-error>", "top_k": 3}},
                )
            )
    elif strategy == "investigate":
        candidates.extend(
            [
                _candidate("mcp_call", 0.84 if has_search else 0.0, "collect evidence before another edit", {"tool": "workspace.search"}),
                _candidate("read_file", 0.78, "inspect minimal suspect files"),
                _candidate("run_command", 0.55, "run targeted debug command, not broad changes"),
            ]
        )
    elif strategy == "verify":
        candidates.extend(
            [
                _candidate("production_check", 0.90 if tests else 0.78, "verification is the best next industrial gate"),
                _candidate("run_command", 0.66, "run the project-specific acceptance command"),
                _candidate("finish", 0.38 if progress.endswith("_ok") else 0.18, "finish only after quality and ship gates"),
            ]
        )
    elif strategy == "ship":
        ready = progress in ("run_ok", "production_check_ok")
        candidates.extend(
            [
                _candidate("finish", 0.92 if ready else 0.22, "ship stage reached; finish only if latest verification is green"),
                _candidate("production_check", 0.78 if not ready else 0.48, "run final check if latest verification is missing"),
            ]
        )
    else:
        candidates.extend(
            [
                _candidate("read_file", 0.58, "preserve context before editing"),
                _candidate("write_file", 0.54, "continue minimal implementation"),
                _candidate("production_check", 0.50 if tests else 0.36, "verify when tests or package files exist"),
            ]
        )

    by_action: dict[str, dict[str, Any]] = {}
    for row in candidates:
        action = str(row.get("action", ""))
        if not action:
            continue
        prev = by_action.get(action)
        if prev is None or _safe_float(row.get("score")) > _safe_float(prev.get("score")):
            by_action[action] = row
    return sorted(by_action.values(), key=lambda x: (-_safe_float(x.get("score")), str(x.get("action"))))[:6]


def _memory_adjustment(stats_row: dict[str, Any]) -> float:
    attempts = _safe_int(stats_row.get("attempts"))
    if attempts <= 0:
        return 0.0
    confidence = min(1.0, attempts / 3.0)
    reward_avg = _safe_float(stats_row.get("reward_avg"))
    return round(max(-0.20, min(0.20, reward_avg * 0.12 * confidence)), 3)


def _policy_memory_snapshot(policy_state: dict[str, Any]) -> dict[str, Any]:
    stats = policy_state.get("tool_success_stats")
    if not isinstance(stats, dict):
        return {"applied": False, "action_values": []}
    values: list[dict[str, Any]] = []
    for action, row in stats.items():
        if not isinstance(row, dict):
            continue
        attempts = _safe_int(row.get("attempts"))
        if attempts <= 0:
            continue
        values.append(
            {
                "action": str(action),
                "attempts": attempts,
                "successes": _safe_int(row.get("successes")),
                "failures": _safe_int(row.get("failures")),
                "reward_avg": round(_safe_float(row.get("reward_avg")), 3),
                "adjustment": _memory_adjustment(row),
            }
        )
    values = sorted(values, key=lambda x: (-abs(_safe_float(x.get("adjustment"))), str(x.get("action"))))[:8]
    return {"applied": bool(values), "action_values": values}


def _apply_policy_memory(
    candidates: list[dict[str, Any]],
    policy_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    memory = _policy_memory_snapshot(policy_state)
    stats = policy_state.get("tool_success_stats")
    if not isinstance(stats, dict):
        return candidates, memory
    out: list[dict[str, Any]] = []
    for row in candidates:
        action = str(row.get("action", ""))
        updated = dict(row)
        stat = stats.get(action)
        if isinstance(stat, dict):
            adjustment = _memory_adjustment(stat)
            if adjustment:
                base = _safe_float(updated.get("score"))
                updated["base_score"] = round(base, 3)
                updated["memory_adjustment"] = adjustment
                updated["memory_attempts"] = _safe_int(stat.get("attempts"))
                updated["score"] = round(max(0.0, min(1.0, base + adjustment)), 3)
                updated["reason"] = (
                    str(updated.get("reason", ""))
                    + f"; policy memory adjusted {adjustment:+.3f} from reward_avg={_safe_float(stat.get('reward_avg')):.3f}"
                )
        out.append(updated)
    return sorted(out, key=lambda x: (-_safe_float(x.get("score")), str(x.get("action"))))[:6], memory


def evaluate_decision_policy(goal: str, plan: dict[str, Any], state: Any) -> dict[str, Any]:
    features = extract_policy_features(goal, plan, state)
    strategy = _choose_strategy(features)
    candidates = _candidate_scores(features, strategy)
    policy_state = _policy_state_from(state)
    candidates, policy_memory = _apply_policy_memory(candidates, policy_state)
    candidates, bandit_selector = rank_candidates_with_ucb(candidates, policy_state)
    selected = candidates[0] if candidates else _candidate("workspace_index", 0.0, "no candidates")
    return {
        "policy_version": POLICY_VERSION,
        "strategy": strategy,
        "features": features,
        "policy_memory": policy_memory,
        "selector": bandit_selector,
        "candidate_actions": candidates,
        "selected_action": selected.get("action", ""),
        "selected_score": selected.get("score", 0.0),
        "selected_bandit_score": selected.get("bandit_score", 0.0),
        "reason": selected.get("reason", ""),
    }


def update_policy_state(
    policy_state: dict[str, Any] | None,
    *,
    executed_action: str,
    reward_signal: dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    out = deepcopy(policy_state) if isinstance(policy_state, dict) else {}
    out["policy_version"] = POLICY_VERSION
    out["recent_strategy"] = str(decision.get("strategy", ""))
    out["last_selected_action"] = str(decision.get("selected_action", ""))
    out["last_executed_action"] = str(executed_action)
    reward = _safe_float(reward_signal.get("total"))
    out["last_reward"] = round(reward, 3)
    out["decision_count"] = _safe_int(out.get("decision_count")) + 1
    out["reward_total"] = round(_safe_float(out.get("reward_total")) + reward, 3)
    stats = out.get("tool_success_stats")
    if not isinstance(stats, dict):
        stats = {}
    row = stats.get(executed_action)
    if not isinstance(row, dict):
        row = {"attempts": 0, "successes": 0, "failures": 0, "reward_total": 0.0, "reward_avg": 0.0}
    row["attempts"] = _safe_int(row.get("attempts")) + 1
    if bool(reward_signal.get("ok", False)):
        row["successes"] = _safe_int(row.get("successes")) + 1
    else:
        row["failures"] = _safe_int(row.get("failures")) + 1
    row["reward_total"] = round(_safe_float(row.get("reward_total")) + reward, 3)
    attempts = max(1, _safe_int(row.get("attempts")))
    row["reward_avg"] = round(_safe_float(row.get("reward_total")) / attempts, 3)
    stats[executed_action] = row
    out["tool_success_stats"] = stats
    estimates = out.get("action_value_estimates")
    if not isinstance(estimates, dict):
        estimates = {}
    estimate = estimates.get(executed_action)
    if not isinstance(estimate, dict):
        estimate = {"count": 0, "q": 0.0, "reward_total": 0.0, "last_reward": 0.0}
    count = _safe_int(estimate.get("count")) + 1
    previous_q = _safe_float(estimate.get("q"))
    estimate["count"] = count
    estimate["last_reward"] = round(reward, 3)
    estimate["reward_total"] = round(_safe_float(estimate.get("reward_total")) + reward, 3)
    estimate["q"] = round(previous_q + ((reward - previous_q) / max(1, count)), 3)
    estimate["last_strategy"] = str(decision.get("strategy", ""))
    estimates[executed_action] = estimate
    out["action_value_estimates"] = estimates
    selector = decision.get("selector")
    if isinstance(selector, dict):
        out["last_selector"] = {
            "selector_version": str(selector.get("selector_version", "")),
            "selected_action": str(selector.get("selected_action", "")),
            "selected_bandit_score": selector.get("selected_bandit_score", 0.0),
        }
    return out
