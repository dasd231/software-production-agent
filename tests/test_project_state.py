from pathlib import Path

from agent.memory.project_state import ProjectState


def test_project_state_roundtrip(tmp_path: Path) -> None:
    st = ProjectState(goal="g", progress="init")
    st.record_error("executor", "boom", "trace")
    st.update_from_result({"action": "run_command", "ok": False, "stderr": "bad"})
    p = tmp_path / ".agent_state.json"
    st.save(p)
    loaded = ProjectState.load(p)
    assert loaded.goal == "g"
    assert loaded.errors
    assert loaded.counters["command_failures"] >= 1
    assert loaded.last_result.get("action") == "run_command"
    assert loaded.policy["policy_version"] == "heuristic-v1"
    assert isinstance(loaded.policy["action_value_estimates"], dict)


def test_record_quality(tmp_path: Path) -> None:
    st = ProjectState()
    st.record_quality(review_score=8.88, health_score=7.11)
    p = tmp_path / "state.json"
    st.save(p)
    loaded = ProjectState.load(p)
    assert loaded.quality["review_score"] == 8.88
    assert loaded.quality["health_score"] == 7.11


def test_project_state_updates_from_production_check() -> None:
    st = ProjectState()
    st.update_from_result({"action": "production_check", "ok": True})
    assert st.progress == "production_check_ok"

    st.update_from_result({"action": "production_check", "ok": False})
    assert st.progress == "production_check_failed"
    assert st.counters["command_failures"] == 1


def test_project_state_policy_roundtrip(tmp_path: Path) -> None:
    st = ProjectState()
    st.policy["recent_strategy"] = "verify"
    st.policy["last_reward"] = 1.2
    p = tmp_path / "state.json"
    st.save(p)
    loaded = ProjectState.load(p)
    assert loaded.policy["recent_strategy"] == "verify"
    assert loaded.policy["last_reward"] == 1.2
