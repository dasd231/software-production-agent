from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class StageFlowBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, state, last_result, session
        stage = str(plan.get("stage", ""))
        if stage == "coding":
            return '{"type":"action","action":"run_command","args":{"command":"python -c \\"print(1)\\"","timeout":5}}'
        if stage == "review":
            return '{"type":"action","action":"list_files","args":{"pattern":"**/*"}}'
        if stage == "qa":
            return '{"type":"action","action":"workspace_index","args":{}}'
        if stage == "ship":
            return '{"type":"action","action":"finish","args":{"reason":"ship_gate_passed"}}'
        return '{"type":"action","action":"finish","args":{"reason":"fallback"}}'


def test_stage_flow_review_qa_ship(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=False, max_agent_iterations=12)
    st = run_agent_loop("goal", ws, prompts, StageFlowBrain(), config=cfg, resume=False)
    assert st.progress.startswith("finished:")
    assert st.current_stage == "ship"
    assert st.quality.get("review_score") is not None
    assert st.quality.get("health_score") is not None


class ProductionCheckStageBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, state, last_result, session
        stage = str(plan.get("stage", ""))
        if stage == "coding":
            return '{"type":"action","action":"run_command","args":{"command":"python -c \\"print(1)\\"","timeout":5}}'
        if stage == "review":
            return '{"type":"action","action":"list_files","args":{"pattern":"**/*"}}'
        if stage == "qa":
            return '{"type":"action","action":"production_check","args":{"include_pytest":false}}'
        if stage == "ship":
            return '{"type":"action","action":"finish","args":{"reason":"verified"}}'
        return '{"type":"action","action":"finish","args":{"reason":"fallback"}}'


def test_stage_flow_qa_uses_production_check_for_health(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=False, max_agent_iterations=12)
    st = run_agent_loop("goal", ws, prompts, ProductionCheckStageBrain(), config=cfg, resume=False)
    assert st.progress.startswith("finished:")
    assert st.last_result["action"] == "finish"
    assert st.quality.get("health_score") is not None
