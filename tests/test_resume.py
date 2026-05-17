from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class FinishBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"finish","args":{"reason":"ok"}}'


def test_resume_loads_existing_state(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=False, max_agent_iterations=2)
    brain = FinishBrain()
    st1 = run_agent_loop("goal-a", ws, prompts, brain, config=cfg, resume=False)
    st2 = run_agent_loop("goal-b", ws, prompts, brain, config=cfg, resume=True)
    assert st1.progress.startswith("finished:")
    assert st2.goal == "goal-b"
    assert st2.last_iteration >= 0
