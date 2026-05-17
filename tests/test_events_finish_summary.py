import json
from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class FinishOnlyBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"finish","args":{"reason":"ok"}}'


def test_finish_event_has_result_summary(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=3)
    run_agent_loop("goal", ws, prompts, FinishOnlyBrain(), config=cfg, resume=False)
    events_path = ws / ".agent_events.jsonl"
    rows = [json.loads(x) for x in events_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    finish_rows = [r for r in rows if r.get("kind") == "finish"]
    assert finish_rows
    rs = finish_rows[-1].get("result_summary")
    assert isinstance(rs, dict)
    assert rs.get("action") == "finish"
    assert rs.get("ok") is True
