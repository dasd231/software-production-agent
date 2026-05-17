import json
from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain
from agent.memory.project_state import ProjectState


class FinishBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"finish","args":{"reason":"done"}}'


def test_ship_gate_blocked_event_has_result_summary(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    seed = ProjectState(
        current_stage="qa",
        progress="run_ok",
        quality={"review_score": 8.0, "health_score": 6.0, "wtf_likelihood": 0},
        counters={"iterations": 0, "fix_attempts": 0, "command_failures": 0, "reverts": 0},
        files=["app.py"],
    )
    seed.save(ws / ".agent_state.json")
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=1)
    run_agent_loop("goal", ws, prompts, FinishBrain(), config=cfg, resume=True)
    rows = [json.loads(x) for x in (ws / ".agent_events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    blocked = [r for r in rows if r.get("kind") == "ship_gate_blocked"]
    assert blocked
    rs = blocked[-1].get("result_summary")
    assert isinstance(rs, dict)
    assert rs.get("action") == "ship_gate_blocked"
    assert rs.get("stage") == "ship"
