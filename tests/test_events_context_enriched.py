import json
from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class FinishBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"finish","args":{"reason":"ok"}}'


def test_context_enriched_event_emitted(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("from flask import Flask\n", encoding="utf-8")
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=2)
    run_agent_loop("build flask api", ws, prompts, FinishBrain(), config=cfg, resume=False)
    rows = [json.loads(x) for x in (ws / ".agent_events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    events = [r for r in rows if r.get("kind") == "context_enriched"]
    assert events
    summary = events[-1].get("summary", {})
    assert isinstance(summary, dict)
    assert "skill_hints" in summary
    assert summary["rag_paths"] == ["app.py"]
    assert summary["rag_truncated"] == 0
