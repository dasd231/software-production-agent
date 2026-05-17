from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain
from agent.memory.project_state import ProjectState


class FailingBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"run_command","args":{"command":"python -c \\"import sys; sys.exit(1)\\"","timeout":2}}'


def test_safety_gate_stop_reason_preserved(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    st = ProjectState(counters={"iterations": 0, "fix_attempts": 0, "command_failures": 0, "reverts": 2})
    st.save(ws / ".agent_state.json")
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=False, max_agent_iterations=10)
    out = run_agent_loop("goal", ws, prompts, FailingBrain(), config=cfg, resume=True)
    assert out.progress == "stopped:safety_gate"
    assert int(out.quality.get("wtf_likelihood", 0)) > 20
