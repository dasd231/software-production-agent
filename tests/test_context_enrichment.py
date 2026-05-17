from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain

#测试替身
class ImmediateFinishBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"finish","args":{"reason":"ok"}}'


def test_loop_enriches_structure_with_skills_rag_mcp(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "app.py").write_text("from flask import Flask\n", encoding="utf-8")
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=False, max_agent_iterations=3)
    st = run_agent_loop("build flask api", ws, prompts, ImmediateFinishBrain(), config=cfg, resume=False)
    assert isinstance(st.structure.get("skill_hints"), list)
    assert isinstance(st.structure.get("rag_hints"), list)
    assert isinstance(st.structure.get("mcp_capabilities"), list)

