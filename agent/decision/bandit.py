"""Bandit selector for action candidates.

函数流程图：
    rank_candidates_with_ucb(candidates, policy_state, config)
      -> _action_stats()
          -> 优先读取 ProjectState.policy.action_value_estimates
          -> 兼容读取旧 tool_success_stats
      -> _value_to_unit()
          -> 将 reward_avg 从 [-3, 3] 映射到 [0, 1]
      -> _ucb_bonus()
          -> 根据 total_count / action_count 计算探索奖励
      -> 对每个 candidate 计算 bandit_score
      -> 按 bandit_score / 原 score / action 稳定排序
      -> 返回 ranked_candidates + selector_meta

你可以继续练算法/工程化的点：
    1. 当前是 UCB1 风格的轻量多臂老虎机；可以替换成 Thompson sampling。
    2. 当前 action 粒度只到动作名；可以扩展到 action+tool、action+path、stage+action。
    3. 当前 value 来自即时 reward；可以加入 delayed reward，把最终 ship 成败回填给前序动作。
    4. 当前参数是静态值；可以根据项目类型、阶段、失败密度动态调参。
    5. 安全边界：bandit 只能重排候选动作，不能绕过 protocol/executor。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

BANDIT_VERSION = "ucb1-v1"


@dataclass(frozen=True)
class BanditConfig:
    """Small deterministic UCB configuration.

    The weights intentionally keep the heuristic score dominant. The bandit
    nudges choices from history; it should not turn a safety suggestion into an
    execution shortcut.
    """

    prior_weight: float = 0.78
    value_weight: float = 0.22
    exploration_weight: float = 0.08
    reward_min: float = -3.0
    reward_max: float = 3.0
    cold_start_value: float = 0.5


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        out = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return out if math.isfinite(out) else 0.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _action_stats(policy_state: dict[str, Any], action: str) -> dict[str, Any]:
    estimates = _as_dict(policy_state.get("action_value_estimates"))
    row = _as_dict(estimates.get(action))
    if row:
        return {
            "attempts": _safe_int(row.get("count", row.get("attempts"))),
            "reward_avg": _safe_float(row.get("q", row.get("reward_avg"))),
            "source": "action_value_estimates",
        }

    stats = _as_dict(policy_state.get("tool_success_stats"))
    legacy = _as_dict(stats.get(action))
    if legacy:
        return {
            "attempts": _safe_int(legacy.get("attempts")),
            "reward_avg": _safe_float(legacy.get("reward_avg")),
            "source": "tool_success_stats",
        }
    return {"attempts": 0, "reward_avg": 0.0, "source": "cold_start"}


def _total_count(policy_state: dict[str, Any], candidates: list[dict[str, Any]]) -> int:
    total = _safe_int(policy_state.get("decision_count"))
    if total > 0:
        return total
    seen: set[str] = set()
    summed = 0
    for row in candidates:
        action = str(row.get("action", "")).strip()
        if not action or action in seen:
            continue
        seen.add(action)
        summed += _safe_int(_action_stats(policy_state, action).get("attempts"))
    return max(1, summed)


def _value_to_unit(reward_avg: float, attempts: int, cfg: BanditConfig) -> float:
    if attempts <= 0:
        return _clamp01(cfg.cold_start_value)
    span = max(0.001, cfg.reward_max - cfg.reward_min)
    clipped = max(cfg.reward_min, min(cfg.reward_max, reward_avg))
    return _clamp01((clipped - cfg.reward_min) / span)


def _ucb_bonus(total_count: int, attempts: int, cfg: BanditConfig) -> float:
    total = max(1, total_count)
    return cfg.exploration_weight * math.sqrt(math.log(total + 1.0) / float(attempts + 1))


def rank_candidates_with_ucb(
    candidates: list[dict[str, Any]],
    policy_state: dict[str, Any] | None,
    config: BanditConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return candidates ranked by heuristic prior + learned value + UCB bonus."""

    cfg = config or BanditConfig()
    state = policy_state if isinstance(policy_state, dict) else {}
    rows = [dict(x) for x in candidates if isinstance(x, dict) and str(x.get("action", "")).strip()]
    total = _total_count(state, rows)
    ranked: list[dict[str, Any]] = []
    for row in rows:
        action = str(row.get("action", "")).strip()
        stats = _action_stats(state, action)
        attempts = _safe_int(stats.get("attempts"))
        prior = _clamp01(_safe_float(row.get("score")))
        value = _value_to_unit(_safe_float(stats.get("reward_avg")), attempts, cfg)
        bonus = _ucb_bonus(total, attempts, cfg)
        bandit_score = (cfg.prior_weight * prior) + (cfg.value_weight * value) + bonus
        row["bandit_score"] = round(bandit_score, 3)
        row["bandit_value"] = round(value, 3)
        row["bandit_bonus"] = round(bonus, 3)
        row["bandit_attempts"] = attempts
        row["bandit_source"] = str(stats.get("source", ""))
        ranked.append(row)

    ranked.sort(
        key=lambda x: (
            -_safe_float(x.get("bandit_score")),
            -_safe_float(x.get("score")),
            str(x.get("action", "")),
        )
    )
    selected = ranked[0] if ranked else {}
    selector_meta = {
        "selector_version": BANDIT_VERSION,
        "algorithm": "ucb1",
        "total_count": total,
        "selected_action": str(selected.get("action", "")),
        "selected_bandit_score": selected.get("bandit_score", 0.0),
        "selected_prior_score": selected.get("score", 0.0),
        "exploration_weight": cfg.exploration_weight,
        "prior_weight": cfg.prior_weight,
        "value_weight": cfg.value_weight,
    }
    return ranked, selector_meta
