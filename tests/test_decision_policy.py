from agent.decision.bandit import BanditConfig, rank_candidates_with_ucb
from agent.decision.policy import evaluate_decision_policy, update_policy_state
from agent.decision.reward import compute_reward_signal
from agent.decision.trace import build_decision_trace
from agent.memory.project_state import ProjectState


def test_decision_policy_prefers_repair_with_recent_error() -> None:
    st = ProjectState(progress="run_failed")
    st.errors.append({"message": "NameError: missing_symbol", "stderr": "NameError"})
    st.counters["command_failures"] = 1
    st.structure = {
        "rag_hints": [{"path": "app.py"}],
        "mcp_capabilities": [{"tool": "workspace.search"}],
        "tests": ["tests/test_app.py"],
    }
    decision = evaluate_decision_policy("fix bug", {"stage": "fixing", "tasks": []}, st)

    assert decision["strategy"] == "repair"
    assert decision["selected_action"] in {"read_file", "mcp_call"}
    assert decision["features"]["recent_error_count"] == 1
    assert decision["candidate_actions"][0]["score"] >= decision["candidate_actions"][-1]["score"]


def test_reward_signal_rewards_success_and_penalizes_failure() -> None:
    before = ProjectState(progress="")
    after_ok = ProjectState(progress="run_ok")
    ok = compute_reward_signal(before, after_ok, {"action": "run_command", "ok": True})
    assert ok["total"] > 0
    assert ok["progress_after"] == "run_ok"

    after_fail = ProjectState(progress="run_failed")
    after_fail.counters["command_failures"] = 1
    fail = compute_reward_signal(
        before,
        after_fail,
        {"action": "run_command", "ok": False, "returncode": 1, "stderr": "boom"},
    )
    assert fail["total"] < 0
    assert fail["components"]["stderr_penalty"] < 0


def test_policy_state_updates_tool_stats_from_reward() -> None:
    policy = update_policy_state(
        {},
        executed_action="run_command",
        reward_signal={"total": 1.25, "ok": True},
        decision={"strategy": "verify", "selected_action": "production_check"},
    )

    assert policy["decision_count"] == 1
    assert policy["reward_total"] == 1.25
    assert policy["tool_success_stats"]["run_command"]["successes"] == 1
    assert policy["tool_success_stats"]["run_command"]["reward_avg"] == 1.25
    assert policy["action_value_estimates"]["run_command"]["count"] == 1
    assert policy["action_value_estimates"]["run_command"]["q"] == 1.25


def test_decision_policy_memory_adjusts_next_scores() -> None:
    st = ProjectState(progress="run_ok")
    st.structure = {"tests": ["tests/test_app.py"]}
    st.policy["tool_success_stats"] = {
        "production_check": {
            "attempts": 4,
            "successes": 0,
            "failures": 4,
            "reward_total": -8.0,
            "reward_avg": -2.0,
        },
        "run_command": {
            "attempts": 4,
            "successes": 4,
            "failures": 0,
            "reward_total": 6.0,
            "reward_avg": 1.5,
        },
    }

    decision = evaluate_decision_policy("verify project", {"stage": "qa", "tasks": []}, st)

    assert decision["strategy"] == "verify"
    assert decision["policy_memory"]["applied"] is True
    assert decision["selector"]["algorithm"] == "ucb1"
    assert decision["selected_action"] == "run_command"
    run_command = [x for x in decision["candidate_actions"] if x["action"] == "run_command"][0]
    production_check = [x for x in decision["candidate_actions"] if x["action"] == "production_check"][0]
    assert run_command["memory_adjustment"] > 0
    assert production_check["memory_adjustment"] < 0
    assert run_command["bandit_score"] > production_check["bandit_score"]


def test_bandit_ucb_can_explore_under_tried_close_candidate() -> None:
    candidates = [
        {"action": "run_command", "score": 0.71},
        {"action": "production_check", "score": 0.70},
    ]
    policy_state = {
        "decision_count": 20,
        "action_value_estimates": {
            "run_command": {"count": 20, "q": 0.0},
            "production_check": {"count": 0, "q": 0.0},
        },
    }

    ranked, meta = rank_candidates_with_ucb(
        candidates,
        policy_state,
        BanditConfig(exploration_weight=0.25),
    )

    assert meta["selector_version"] == "ucb1-v1"
    assert ranked[0]["action"] == "production_check"
    assert ranked[0]["bandit_attempts"] == 0
    assert ranked[0]["bandit_bonus"] > ranked[1]["bandit_bonus"]


def test_decision_trace_records_alignment_and_reward() -> None:
    trace = build_decision_trace(
        iteration=2,
        policy_decision={
            "policy_version": "heuristic-v1",
            "strategy": "verify",
            "selected_action": "production_check",
            "reason": "verify",
            "candidate_actions": [{"action": "production_check", "score": 0.9}],
        },
        action_obj={"type": "action", "action": "production_check", "args": {}},
        reward_signal={"total": 1.0, "ok": True},
    )

    assert trace["iteration"] == 2
    assert trace["aligned_with_policy"] is True
    assert trace["reward_after_execution"]["total"] == 1.0
