from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import _ship_gate_error, run_agent_loop
from agent.core.brain import AgentBrain
from agent.memory.project_state import ProjectState


class AlwaysFinishBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"finish","args":{"reason":"done"}}'


def test_ship_gate_rules() -> None:
    st = ProjectState(current_stage="ship", progress="run_ok")
    st.quality = {"review_score": 8.0, "health_score": 7.2, "wtf_likelihood": 0}
    assert _ship_gate_error(st, 6.0, 7.0) is None

    st.quality["health_score"] = 6.5
    assert "health_score" in str(_ship_gate_error(st, 6.0, 7.0))


def test_ship_gate_accepts_production_check_ok() -> None:
    st = ProjectState(current_stage="ship", progress="production_check_ok")
    st.quality = {"review_score": 8.0, "health_score": 7.2, "wtf_likelihood": 0}
    assert _ship_gate_error(st, 6.0, 7.0) is None


def test_ship_gate_custom_thresholds() -> None:
    st = ProjectState(current_stage="ship", progress="run_ok")
    st.quality = {"review_score": 6.2, "health_score": 7.2, "wtf_likelihood": 0}
    assert _ship_gate_error(st, 6.0, 7.0) is None
    assert "review_score" in str(_ship_gate_error(st, 7.0, 7.0))


def test_ship_gate_blocks_finish_when_health_low(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    seed = ProjectState(
        goal="goal",
        current_stage="qa",
        progress="run_ok",
        quality={"review_score": 8.0, "health_score": 6.2, "wtf_likelihood": 0},
        counters={"iterations": 0, "fix_attempts": 0, "command_failures": 0, "reverts": 0},
        files=["app.py"],
    )
    seed.save(ws / ".agent_state.json")
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=False, max_agent_iterations=1)
    out = run_agent_loop("goal", ws, prompts, AlwaysFinishBrain(), config=cfg, resume=True)
    assert out.progress == "stopped:max_iterations"
    assert any(e.get("source") == "ship_gate" for e in out.errors)
