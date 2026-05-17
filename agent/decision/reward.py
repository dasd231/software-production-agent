"""Reward signal calculation for software-production agent decisions.

函数流程图：
    compute_reward_signal(before_state, after_state, result)
      -> _state_dict() 统一 ProjectState/dict 输入
      -> 根据 result.ok / progress / counters / stderr / timeout 计算 components
      -> round + clip 得到 total reward
      -> 返回 RewardSignal dict

你可以继续练算法/工程化的点：
    1. 当前 reward 是启发式；可以引入项目级验收指标、覆盖率、diff 风险和历史趋势。
    2. 当前只看前后状态差；可以加入 action cost、工具耗时、RAG 命中质量。
    3. 当前立即奖励为主；可以增加 delayed reward，把最终 ship 结果回填到前序决策。
    4. 当前 reward 不学习；后续可接 bandit / value estimate / policy gradient。
"""

from __future__ import annotations

from typing import Any

REWARD_VERSION = "heuristic-v1"


def _state_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        out = value.to_dict()
        return out if isinstance(out, dict) else {}
    return {}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _progress_score(progress: str) -> float:
    if progress.startswith("finished:"):
        return 1.4
    if progress in ("production_check_ok", "run_ok"):
        return 0.55
    if progress in ("production_check_failed", "run_failed"):
        return -0.45
    if progress.startswith("stopped:") or progress.startswith("ship_gate:"):
        return -0.9
    return 0.0


def compute_reward_signal(before_state: Any, after_state: Any, result: dict[str, Any]) -> dict[str, Any]:
    before = _state_dict(before_state)
    after = _state_dict(after_state)
    before_counters = _as_dict(before.get("counters"))
    after_counters = _as_dict(after.get("counters"))
    before_quality = _as_dict(before.get("quality"))
    after_quality = _as_dict(after.get("quality"))
    before_progress = str(before.get("progress", ""))
    after_progress = str(after.get("progress", ""))
    ok = bool(result.get("ok", False))
    components: dict[str, float] = {
        "execution_ok": 0.8 if ok else -0.8,
        "progress": _progress_score(after_progress) - max(0.0, _progress_score(before_progress) * 0.25),
    }
    command_failure_delta = _safe_int(after_counters.get("command_failures")) - _safe_int(
        before_counters.get("command_failures")
    )
    if command_failure_delta > 0:
        components["command_failure_delta"] = -0.35 * command_failure_delta
    error_delta = len(after.get("errors", []) if isinstance(after.get("errors"), list) else []) - len(
        before.get("errors", []) if isinstance(before.get("errors"), list) else []
    )
    if error_delta > 0:
        components["error_delta"] = -0.20 * error_delta
    stderr = str(result.get("stderr", "") or result.get("stderr_head", ""))
    if stderr.strip():
        components["stderr_penalty"] = -0.15
    if int(result.get("returncode", 0) or 0) == -1 or "[timeout]" in stderr.lower() or "timed out" in stderr.lower():
        components["timeout_penalty"] = -0.55
    if result.get("action") == "production_check" and ok:
        components["verification_bonus"] = 0.35
    if result.get("action") == "finish" and ok:
        components["finish_bonus"] = 0.65
    quality_delta = (
        _safe_float(after_quality.get("review_score"))
        + _safe_float(after_quality.get("health_score"))
        - _safe_float(before_quality.get("review_score"))
        - _safe_float(before_quality.get("health_score"))
    )
    if quality_delta:
        components["quality_delta"] = max(-0.3, min(0.3, quality_delta / 20.0))
    total = round(max(-3.0, min(3.0, sum(components.values()))), 3)
    return {
        "schema_version": "1",
        "reward_version": REWARD_VERSION,
        "total": total,
        "components": {k: round(v, 3) for k, v in components.items()},
        "ok": ok,
        "action": str(result.get("action", "")),
        "progress_before": before_progress,
        "progress_after": after_progress,
    }
