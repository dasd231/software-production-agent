from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.project_model.program import build_project_model_program


def test_project_model_program_has_valid_stage_catalog() -> None:
    program = build_project_model_program()
    stages = {row["id"]: row for row in program["stages"]}

    assert program["schema"] == "project_model_program.v1"
    assert program["summary"]["source_sampling_weight_total"] == 1.0
    assert program["validation"]["ok"] is True
    assert stages["retrieval_grounded_understanding"]["task_mix"][0]["task_id"] == "evidence_retrieval"
    assert program["recommended_first_build"]["id"] == "repo_memory_v1"


def test_project_model_program_plan_action_returns_valid_blueprint(tmp_path: Path) -> None:
    out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "project_model_program_plan",
            "args": {"ambition": "internet_scale", "target_context_tokens": 65536},
        },
    )

    assert out["ok"] is True
    assert out["plan"]["target_context_tokens"] == 65536
    assert out["plan"]["validation"]["retrieval_before_or_with_qa"] is True
