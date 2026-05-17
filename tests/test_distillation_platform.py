from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.distillation.catalog import list_teacher_models, list_teacher_tasks
from agent.distillation.datasets import build_distillation_dataset_manifest
from agent.distillation.plans import build_distillation_plan, build_teacher_task_suite


def test_teacher_catalog_exposes_models_and_tasks() -> None:
    teachers = {row["id"]: row for row in list_teacher_models()}
    tasks = {row["id"]: row for row in list_teacher_tasks()}

    assert "deepseek_reasoning_teacher" in teachers
    assert teachers["local_main_teacher"]["provider"] == "main_deepseek"
    assert tasks["teacher_repo_grounded_qa"]["requires_evidence"] is True


def test_distillation_plan_validates_teacher_mix_and_suite() -> None:
    suite = build_teacher_task_suite(name="repo-distill-v1")
    plan = build_distillation_plan(
        name="repo-distill-v1",
        student_model="demo/student",
        teacher_mix={"deepseek_reasoning_teacher": 0.6, "local_main_teacher": 0.4},
        task_suite=suite,
        consensus_policy="multi_teacher_consensus",
    )

    assert suite["validation"]["ok"] is True
    assert plan["validation"]["ok"] is True
    assert plan["validation"]["teacher_count"] == 2
    assert plan["consensus_policy"] == "multi_teacher_consensus"


def test_distillation_dataset_manifest_filters_unusable_teacher_outputs() -> None:
    suite = build_teacher_task_suite(name="repo-distill-v1")
    plan = build_distillation_plan(
        name="repo-distill-v1",
        student_model="demo/student",
        teacher_mix={"local_main_teacher": 1.0},
        task_suite=suite,
    )
    manifest = build_distillation_dataset_manifest(
        distillation_plan=plan,
        teacher_outputs=[
            {
                "teacher_id": "local_main_teacher",
                "task_id": "teacher_repo_grounded_qa",
                "prompt_id": "p1",
                "instruction": "answer",
                "input": "where",
                "output": "here",
                "citations": [{"path": "app.py", "line": 1}],
            },
            {
                "teacher_id": "local_main_teacher",
                "task_id": "teacher_repo_grounded_qa",
                "prompt_id": "p2",
                "instruction": "answer",
                "input": "where",
                "output": "",
                "citations": [],
            },
        ],
    )

    assert manifest["counts"]["accepted_examples"] == 1
    assert manifest["counts"]["rejected_examples"] == 1
    assert manifest["validation"]["ok"] is False


def test_distillation_actions_expose_control_plane(tmp_path: Path) -> None:
    registry = run_action(tmp_path, {"type": "action", "action": "teacher_registry", "args": {}})
    suite_out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "teacher_task_suite_plan",
            "args": {"name": "suite-demo"},
        },
    )
    plan_out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "distillation_plan_build",
            "args": {
                "name": "distill-demo",
                "student_model": "demo/student",
                "teacher_mix": {"local_main_teacher": 1.0},
                "task_suite": suite_out["suite"],
            },
        },
    )
    manifest_out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "distillation_dataset_manifest_build",
            "args": {
                "distillation_plan": plan_out["plan"],
                "teacher_outputs": [
                    {
                        "teacher_id": "local_main_teacher",
                        "task_id": "teacher_repo_grounded_qa",
                        "prompt_id": "p1",
                        "instruction": "answer",
                        "input": "where",
                        "output": "here",
                        "citations": [{"path": "app.py", "line": 1}],
                    }
                ],
            },
        },
    )

    assert registry["ok"] is True
    assert suite_out["ok"] is True
    assert plan_out["ok"] is True
    assert manifest_out["ok"] is True
