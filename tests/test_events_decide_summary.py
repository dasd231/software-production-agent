import json
from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.core.agent_loop import run_agent_loop
from agent.core.brain import AgentBrain


class OneCommandBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return '{"type":"action","action":"run_command","args":{"command":"python -c \\"print(42)\\"","timeout":3}}'


class SandboxPlanBrain(AgentBrain):
    def decide(self, goal, plan, state, last_result, session=None):  # type: ignore[override]
        _ = goal, plan, state, last_result, session
        return (
            '{"type":"action","action":"k8s_sandbox_plan","args":'
            '{"command":"python train_model.py","namespace":"agent-sandbox","output_path":"sandbox/job.json"}}'
        )


def test_decide_event_has_action_summary(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=1)
    run_agent_loop("goal", ws, prompts, OneCommandBrain(), config=cfg, resume=False)
    rows = [json.loads(x) for x in (ws / ".agent_events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    decide = [r for r in rows if r.get("kind") == "decide"][-1]
    s = decide.get("action_summary")
    assert isinstance(s, dict)
    assert s.get("action") == "run_command"
    assert "python -c" in str(s.get("command_head", ""))
    assert [r.get("kind") for r in rows].count("decision_policy") >= 1
    assert [r.get("kind") for r in rows].count("reward_signal") >= 1
    assert [r.get("kind") for r in rows].count("decision_trace") >= 1
    reward = [r for r in rows if r.get("kind") == "reward_signal"][-1].get("reward", {})
    assert reward.get("action") == "run_command"


def test_decide_event_summarizes_k8s_sandbox_plan(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    prompts = Path(__file__).resolve().parents[1] / "agent" / "prompts"
    cfg = replace(AppConfig.from_env(), session_log_jsonl=False, event_log=True, max_agent_iterations=1)
    run_agent_loop("goal", ws, prompts, SandboxPlanBrain(), config=cfg, resume=False)
    rows = [json.loads(x) for x in (ws / ".agent_events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    decide = [r for r in rows if r.get("kind") == "decide"][-1]
    summary = decide.get("action_summary")

    assert summary["action"] == "k8s_sandbox_plan"
    assert summary["namespace"] == "agent-sandbox"
    assert "python train_model.py" in summary["command_head"]
