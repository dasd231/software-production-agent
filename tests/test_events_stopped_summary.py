import json
from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class NoFinishBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"list_files","args":{"pattern":"**/*"}}'


class AlwaysFailBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"run_command","args":{"command":"python -c \\"import sys; sys.exit(1)\\"","timeout":2}}'


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_stopped_event_has_summary_for_max_iterations(tmp_path: Path) -> None:
    ws = tmp_path / "ws1"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=1)
    run_agent_loop("goal", ws, prompts, NoFinishBrain(), config=cfg, resume=False)
    rows = _read_rows(ws / ".agent_events.jsonl")
    stopped = [r for r in rows if r.get("kind") == "stopped"][-1]
    assert stopped["reason"] == "max_iterations"
    rs = stopped.get("result_summary")
    assert isinstance(rs, dict)
    assert rs.get("action") == "stopped"
    assert rs.get("reason") == "max_iterations"


def test_stopped_event_has_summary_for_investigate_required(tmp_path: Path) -> None:
    ws = tmp_path / "ws2"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=20)
    run_agent_loop("goal", ws, prompts, AlwaysFailBrain(), config=cfg, resume=False)
    rows = _read_rows(ws / ".agent_events.jsonl")
    stopped = [r for r in rows if r.get("kind") == "stopped"][-1]
    assert stopped["reason"] == "investigate_required"
    rs = stopped.get("result_summary")
    assert isinstance(rs, dict)
    assert rs.get("action") == "stopped"
    assert rs.get("reason") == "investigate_required"
