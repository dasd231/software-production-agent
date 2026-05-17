from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.enterprise.stack import build_enterprise_stack_plan


def test_enterprise_stack_plan_answers_three_enterprise_questions(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    plan = build_enterprise_stack_plan(
        "上市企业私有化 AI 平台，支持 vLLM/SGLang、100+ 终端、多 Agent、RAG、灰度发布和热迭代",
        ws,
        scale="listed",
        regulated=True,
    )

    assert plan["schema"] == "enterprise_stack_plan.v1"
    assert plan["scale_tier"] == "listed"
    assert plan["risk_profile"]["human_approval_required"] is True
    ids = {row["id"] for row in plan["scenario_solutions"]}
    assert ids == {
        "llm_serving_selection",
        "production_multi_agent_engineering",
        "private_ai_platform_100_terminals",
    }
    serving = plan["scenario_solutions"][0]
    assert "vLLM" in serving["answer"]
    assert "SGLang" in serving["answer"]
    assert any("32K+" in row["scenario"] for row in serving["selection_matrix"])
    platform = plan["scenario_solutions"][2]
    assert "model_version_management" in platform
    assert "gray_release" in platform
    assert "elastic_scaling" in platform
    assert platform["reference_capacity_start"]["terminals"] == "100+"


def test_enterprise_stack_action_dispatches(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    out = run_action(
        ws,
        {
            "type": "action",
            "action": "enterprise_stack_plan",
            "args": {
                "goal": "工业生产级私有化 Agent 平台，要求热迭代和 vLLM 模型服务",
                "scale": "enterprise",
                "regulated": False,
            },
        },
    )

    assert out["ok"] is True
    assert out["plan"]["schema"] == "enterprise_stack_plan.v1"
    layers = {choice["layer"] for choice in out["plan"]["technology_choices"]}
    assert "model_runtime" in layers
    assert "progressive_delivery" in layers
    assert "distributed_execution" in layers
    assert "batch_data_processing" in layers
