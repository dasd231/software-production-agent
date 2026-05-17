import json
from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class EventContractBrain(AgentBrain):
    def __init__(self) -> None:
        self._fixed = False
        self._done = False

    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        if self._done:
            return '{"type":"action","action":"finish","args":{"reason":"done"}}'
        if self._fixed:
            self._done = True
            return '{"type":"action","action":"run_command","args":{"command":"python -c \\"print(9)\\"","timeout":2}}'
        return '{"type":"action","action":"run_command","args":{"command":"python -c \\"import sys; sys.exit(1)\\"","timeout":2}}'

    def fix(self, error_text, goal, plan, state, session=None):  # type: ignore[override]
        _ = error_text, goal, plan, state, session
        self._fixed = True
        return '{"type":"action","action":"run_command","args":{"command":"python -c \\"print(1)\\"","timeout":2}}'


def test_event_schema_contract(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=8)
    run_agent_loop("goal", ws, prompts, EventContractBrain(), config=cfg, resume=False)
    rows = [json.loads(x) for x in (ws / ".agent_events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows
    run_ids = {row.get("run_id") for row in rows}
    event_ids = [row.get("event_id") for row in rows]
    assert len(run_ids) == 1
    assert next(iter(run_ids))
    assert all(isinstance(x, str) and len(x) == 16 for x in event_ids)
    assert len(set(event_ids)) == len(event_ids)
    for row in rows:
        assert row.get("schema_version") == "1"
        kind = row.get("kind")
        if kind == "plan":
            assert "plan_summary" in row
        if kind in ("decide", "fix"):
            assert "action_summary" in row
            assert "token_usage" in row
        if kind in ("execute", "execute_fix", "finish", "stopped", "ship_gate_blocked"):
            assert "result_summary" in row
        if kind in ("execute", "execute_fix"):
            rs = row.get("result_summary", {})
            assert "duration_ms" in rs
            assert "preflight_status" in rs
