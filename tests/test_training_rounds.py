from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.training.rounds import build_first_training_round_plan


def test_first_training_round_plan_exposes_shortest_safe_path() -> None:
    plan = build_first_training_round_plan(
        name="first-round",
        learning_dirs=["./project_task_runs/demo", "./distillation_runs/demo"],
        training_output_dir="./training_runs/first-round",
        model_output_dir="./model_runs/first-round",
    )

    assert plan["schema"] == "first_training_round_plan.v1"
    assert plan["validation"]["ok"] is True
    assert [row["action"] for row in plan["actions"]] == ["training_prepare", "backup_model_train"]
    assert plan["server_handoff"]["strategy"].startswith("prepare locally")
    assert plan["server_handoff"]["preflight_action"] == "training_server_preflight"


def test_first_training_round_plan_action_is_available(tmp_path: Path) -> None:
    result = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "first_training_round_plan",
            "args": {
                "name": "first-round",
                "learning_dirs": ["./project_task_runs/demo"],
                "training_output_dir": "./training_runs/first-round",
                "model_output_dir": "./model_runs/first-round",
            },
        },
    )

    assert result["ok"] is True
    assert result["plan"]["actions"][0]["action"] == "training_prepare"
