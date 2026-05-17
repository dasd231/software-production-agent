from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.training.studio import (
    build_ablation_plan,
    build_training_platform_blueprint,
    build_training_recipe,
)


def _baseline_recipe() -> dict:
    return build_training_recipe(
        name="repo-reader-v1",
        research_question="Does retrieval-grounded supervision improve project understanding?",
        base_model="demo/base",
        objective="sft",
        task_mix={
            "repo_structure_mapping": 0.2,
            "symbol_grounding": 0.2,
            "evidence_retrieval": 0.3,
            "architecture_summary": 0.3,
        },
        data_mix={"repo_memory_v1": 1.0},
        method={"adapter_method": "lora", "context_window": 32768},
        evaluation_suite=["internal_repo_holdout"],
    )


def test_training_platform_blueprint_remembers_route_and_planes() -> None:
    blueprint = build_training_platform_blueprint()
    planes = {row["id"]: row for row in blueprint["planes"]}

    assert blueprint["current_priority"]["route"] == "A"
    assert blueprint["route_memory"] == [
        "A: build the platform top level first",
        "B: add distillation next",
        "C: thicken paper-grade comparison after that",
    ]
    assert planes["training_studio_plane"]["current_state"] == "active_build"


def test_training_recipe_is_human_facing_and_validated() -> None:
    recipe = _baseline_recipe()

    assert recipe["schema"] == "training_recipe.v1"
    assert recipe["validation"]["ok"] is True
    assert recipe["validation"]["task_mix_total"] == 1.0
    assert recipe["evaluation_suite"] == ["internal_repo_holdout"]


def test_ablation_plan_marks_changed_paths_against_baseline() -> None:
    baseline = _baseline_recipe()
    plan = build_ablation_plan(
        name="retrieval-weight",
        research_question="Does more retrieval supervision help?",
        baseline_recipe=baseline,
        variants=[
            {
                "name": "retrieval-up",
                "purpose": "increase retrieval share",
                "patch": {
                    "task_mix": {
                        "repo_structure_mapping": 0.15,
                        "symbol_grounding": 0.15,
                        "evidence_retrieval": 0.4,
                        "architecture_summary": 0.3,
                    }
                },
            }
        ],
        primary_metrics=["recall_at_5"],
        success_criteria=["retrieval-up beats baseline on recall_at_5"],
    )

    variant = plan["variants"][0]
    assert plan["schema"] == "ablation_plan.v1"
    assert plan["validation"]["ok"] is True
    assert "task_mix.evidence_retrieval" in variant["changed_paths"]
    assert variant["change_count"] == 3


def test_training_studio_actions_return_blueprint_recipe_and_ablation(tmp_path: Path) -> None:
    blueprint = run_action(tmp_path, {"type": "action", "action": "training_platform_blueprint", "args": {}})
    recipe = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "training_recipe_plan",
            "args": {
                "name": "demo",
                "research_question": "why",
                "base_model": "demo/base",
                "objective": "sft",
                "task_mix": {"repo_structure_mapping": 0.5, "architecture_summary": 0.5},
            },
        },
    )
    ablation = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "ablation_plan_build",
            "args": {
                "name": "demo-ablation",
                "research_question": "why",
                "baseline_recipe": recipe["recipe"],
                "variants": [
                    {
                        "name": "variant",
                        "patch": {
                            "task_mix": {
                                "repo_structure_mapping": 0.4,
                                "architecture_summary": 0.6,
                            }
                        },
                    }
                ],
                "primary_metrics": ["architecture_qa_accuracy"],
                "success_criteria": ["variant improves score"],
            },
        },
    )

    assert blueprint["ok"] is True
    assert recipe["ok"] is True
    assert ablation["ok"] is True
    assert ablation["plan"]["variants"][0]["change_count"] == 2
