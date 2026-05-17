"""Decision policy layer for algorithm-friendly agent evolution.

函数流程图：
    agent_loop
      -> policy.evaluate_decision_policy()
      -> reward.compute_reward_signal()
      -> trace.build_decision_trace()
      -> ProjectState.policy / events

你可以继续练算法/工程化的点：
    1. 当前只暴露启发式接口；后续可以把 bandit/RL 策略作为同一接口的实现。
    2. 当前模块不执行工具；这个边界必须保留，执行仍只能经过 executor。
"""

from agent.decision.bandit import BANDIT_VERSION, BanditConfig, rank_candidates_with_ucb
from agent.decision.policy import evaluate_decision_policy, update_policy_state
from agent.decision.reward import compute_reward_signal
from agent.decision.trace import build_decision_trace

__all__ = [
    "BANDIT_VERSION",
    "BanditConfig",
    "build_decision_trace",
    "compute_reward_signal",
    "evaluate_decision_policy",
    "rank_candidates_with_ucb",
    "update_policy_state",
]
