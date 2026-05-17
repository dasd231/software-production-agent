"""Decision trace records why an action was selected and what reward followed.

函数流程图：
    build_decision_trace(iteration, policy_decision, action_obj, reward_signal)
      -> 提取 policy selected_action / candidate_actions
      -> 提取 Brain 实际输出 action
      -> 计算 aligned_with_policy
      -> 附加 reward_after_execution
      -> 返回可写入 events 的 DecisionTrace dict

你可以继续练算法/工程化的点：
    1. 当前 trace 是单步；可以扩展成 episode trace，把最终 ship reward 回填到前序动作。
    2. 当前 alignment 只比 action 名；可以比 args、工具、目标文件和命令类别。
    3. 当前候选动作只存 TopN；可以落完整候选集到压缩 sidecar。
"""

from __future__ import annotations

from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def build_decision_trace(
    *,
    iteration: int,
    policy_decision: dict[str, Any],
    action_obj: dict[str, Any],
    reward_signal: dict[str, Any] | None = None,
) -> dict[str, Any]:
    decision = _as_dict(policy_decision)
    action = _as_dict(action_obj)
    actual_action = str(action.get("action", ""))
    policy_action = str(decision.get("selected_action", ""))
    candidates = [x for x in _as_list(decision.get("candidate_actions")) if isinstance(x, dict)]
    return {
        "schema_version": "1",
        "iteration": int(iteration),
        "policy_version": str(decision.get("policy_version", "")),
        "strategy": str(decision.get("strategy", "")),
        "policy_selected_action": policy_action,
        "selected_action": actual_action,
        "aligned_with_policy": bool(policy_action and actual_action == policy_action),
        "reason": str(decision.get("reason", "")),
        "candidate_actions": candidates[:5],
        "reward_after_execution": dict(reward_signal or {}),
    }
