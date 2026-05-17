from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class AlwaysFailBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"run_command","args":{"command":"python -c \\"import sys; sys.exit(1)\\"","timeout":2}}'


def test_investigate_escalation_stops_early(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=False, max_agent_iterations=20)
    out = run_agent_loop("goal", ws, prompts, AlwaysFailBrain(), config=cfg, resume=False)
    assert out.progress == "stopped:investigate_required"
    assert int(out.counters.get("command_failures", 0)) >= 3
    handoff = out.structure.get("investigate_handoff")
    assert isinstance(handoff, dict)
    assert handoff.get("reason") == "investigate_required"
    assert isinstance(handoff.get("recommended_next_actions"), list)
