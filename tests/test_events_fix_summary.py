import json
from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class FailThenFixBrain(AgentBrain):
    def __init__(self) -> None:
        self._fixed = False

    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        if not self._fixed:
            return '{"type":"action","action":"run_command","args":{"command":"python -c \\"import sys; sys.exit(1)\\"","timeout":2}}'
        return '{"type":"action","action":"finish","args":{"reason":"ok"}}'

    def fix(self, error_text, goal, plan, state, session=None):  # type: ignore[override]
        _ = error_text, goal, plan, state, session
        self._fixed = True
        return '{"type":"action","action":"run_command","args":{"command":"python -c \\"print(7)\\"","timeout":2}}'


def test_fix_event_has_action_summary(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=5)
    run_agent_loop("goal", ws, prompts, FailThenFixBrain(), config=cfg, resume=False)
    rows = [json.loads(x) for x in (ws / ".agent_events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    fix_rows = [r for r in rows if r.get("kind") == "fix"]
    assert fix_rows
    s = fix_rows[-1].get("action_summary")
    assert isinstance(s, dict)
    assert s.get("action") == "run_command"
    assert "python -c" in str(s.get("command_head", ""))
