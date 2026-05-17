from __future__ import annotations

import json
from pathlib import Path

from agent.chains.training import TrainingPrepareInput, prepare_fine_tuning_dataset
from agent.core.executor import run_action
from agent.distillation.execution import build_teacher_execution_plan
from agent.distillation.export import export_distillation_training_examples
from agent.distillation.plans import build_distillation_plan, build_teacher_task_suite
from agent.distillation.prompts import build_teacher_prompt_batch
from agent.distillation.review import review_teacher_outputs
from agent.distillation.runtime import run_teacher_execution


def _distillation_plan() -> dict:
    suite = build_teacher_task_suite(
        name="repo-distill-v2",
        task_mix={"teacher_architecture_summary": 1.0},
    )
    return build_distillation_plan(
        name="repo-distill-v2",
        student_model="demo/student",
        teacher_mix={"local_main_teacher": 1.0},
        task_suite=suite,
    )


def _source_example() -> dict:
    return {
        "example_id": "arch-1",
        "task_type": "architecture_summary",
        "instruction": "请概括项目架构。",
        "input": "仓库：demo/repo",
        "output": "old baseline answer",
        "citations": [{"path": "project_map.json"}],
        "metadata": {"repo_id": "demo/repo"},
    }


def test_teacher_prompt_batch_builds_evidence_bound_prompts() -> None:
    batch = build_teacher_prompt_batch(
        distillation_plan=_distillation_plan(),
        source_examples=[_source_example()],
    )

    prompt = batch["prompts"][0]
    assert batch["validation"]["ok"] is True
    assert prompt["teacher_id"] == "local_main_teacher"
    assert prompt["teacher_task_id"] == "teacher_architecture_summary"
    assert prompt["student_task_type"] == "architecture_summary"
    assert prompt["evidence_bundle"] == [{"path": "project_map.json"}]


def test_teacher_execution_plan_is_dry_run_by_default_and_blocks_implicit_live_mode() -> None:
    plan = _distillation_plan()
    batch = build_teacher_prompt_batch(distillation_plan=plan, source_examples=[_source_example()])
    dry_run = build_teacher_execution_plan(distillation_plan=plan, prompt_batch=batch)
    blocked_live = build_teacher_execution_plan(
        distillation_plan=plan,
        prompt_batch=batch,
        mode="live",
        allow_remote=False,
    )

    assert dry_run["mode"] == "dry_run"
    assert dry_run["safety"]["makes_remote_calls"] is False
    assert dry_run["validation"]["ok"] is True
    assert blocked_live["validation"]["ok"] is False
    assert "live_mode_requires_allow_remote" in blocked_live["validation"]["blockers"]


def test_teacher_runtime_keeps_dry_run_side_effect_free() -> None:
    plan = _distillation_plan()
    batch = build_teacher_prompt_batch(distillation_plan=plan, source_examples=[_source_example()])
    execution_plan = build_teacher_execution_plan(distillation_plan=plan, prompt_batch=batch)
    result = run_teacher_execution(execution_plan=execution_plan)

    assert result["mode"] == "dry_run"
    assert result["counts"]["teacher_outputs"] == 0
    assert result["request_results"][0]["status"] == "skipped_dry_run"


def test_teacher_runtime_executes_explicit_live_plan_with_injected_completion() -> None:
    plan = _distillation_plan()
    batch = build_teacher_prompt_batch(distillation_plan=plan, source_examples=[_source_example()])
    execution_plan = build_teacher_execution_plan(
        distillation_plan=plan,
        prompt_batch=batch,
        mode="live",
        allow_remote=True,
    )
    result = run_teacher_execution(
        execution_plan=execution_plan,
        completion_fn=lambda request: {
            "content": json.dumps(
                {
                    "output": "项目包含入口、测试和依赖配置。",
                    "citations": [{"path": "project_map.json"}],
                },
                ensure_ascii=False,
            ),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )

    assert result["validation"]["ok"] is True
    assert result["counts"]["completed_requests"] == 1
    assert result["teacher_outputs"][0]["output"].startswith("项目包含")
    assert result["usage"]["total_tokens"] == 15


def test_teacher_output_review_rejects_citations_outside_prompt_evidence() -> None:
    plan = _distillation_plan()
    batch = build_teacher_prompt_batch(distillation_plan=plan, source_examples=[_source_example()])
    prompt_id = batch["prompts"][0]["prompt_id"]
    review = review_teacher_outputs(
        distillation_plan=plan,
        prompt_batch=batch,
        teacher_outputs=[
            {
                "teacher_id": "local_main_teacher",
                "task_id": "teacher_architecture_summary",
                "prompt_id": prompt_id,
                "output": "项目由入口、测试与依赖配置构成。",
                "citations": [{"path": "project_map.json"}],
            },
            {
                "teacher_id": "local_main_teacher",
                "task_id": "teacher_architecture_summary",
                "prompt_id": prompt_id,
                "output": "我额外引用了不存在的文件。",
                "citations": [{"path": "README.md"}],
            },
        ],
    )

    assert review["counts"]["accepted_outputs"] == 1
    assert review["counts"]["rejected_outputs"] == 1
    assert review["validation"]["ok"] is False
    assert review["rejected_outputs"][0]["review"]["reasons"] == ["citations_not_in_prompt_evidence"]


def test_distillation_export_writes_training_prepare_compatible_learning_dir(tmp_path: Path) -> None:
    plan = _distillation_plan()
    batch = build_teacher_prompt_batch(distillation_plan=plan, source_examples=[_source_example()])
    prompt_id = batch["prompts"][0]["prompt_id"]
    review = review_teacher_outputs(
        distillation_plan=plan,
        prompt_batch=batch,
        teacher_outputs=[
            {
                "teacher_id": "local_main_teacher",
                "task_id": "teacher_architecture_summary",
                "prompt_id": prompt_id,
                "output": "这是一个足够长、且忠于证据的项目架构摘要。",
                "citations": [{"path": "project_map.json"}],
            }
        ],
    )
    result = export_distillation_training_examples(
        output_dir=tmp_path / "distill_learning",
        distillation_plan=plan,
        teacher_output_review=review,
    )

    rows = [
        json.loads(line)
        for line in Path(result["files"]["training_examples"]).read_text(encoding="utf-8").splitlines()
    ]
    training = prepare_fine_tuning_dataset(
        TrainingPrepareInput(
            output_dir=tmp_path / "training_from_distill",
            learning_dirs=(Path(result["output_dir"]),),
            include_protocol_examples=False,
            min_chars=10,
            eval_ratio=0.0,
        )
    )
    assert result["manifest"]["compatible_with_training_prepare"] is True
    assert result["counts"]["training_examples"] == 1
    assert rows[0]["task_type"] == "architecture_summary"
    assert rows[0]["metadata"]["source"] == "distillation_v1"
    assert training.total_examples == 1


def test_distillation_execution_actions_cover_prompt_review_and_export(tmp_path: Path) -> None:
    plan = _distillation_plan()
    batch_out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "teacher_prompt_batch_build",
            "args": {"distillation_plan": plan, "source_examples": [_source_example()]},
        },
    )
    execution_out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "teacher_execution_plan_build",
            "args": {"distillation_plan": plan, "prompt_batch": batch_out["batch"]},
        },
    )
    dry_run_out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "teacher_execution_run",
            "args": {"execution_plan": execution_out["plan"]},
        },
    )
    prompt_id = batch_out["batch"]["prompts"][0]["prompt_id"]
    review_out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "teacher_output_review_build",
            "args": {
                "distillation_plan": plan,
                "prompt_batch": batch_out["batch"],
                "teacher_outputs": [
                    {
                        "teacher_id": "local_main_teacher",
                        "task_id": "teacher_architecture_summary",
                        "prompt_id": prompt_id,
                        "output": "这是一个足够长的教师输出。",
                        "citations": [{"path": "project_map.json"}],
                    }
                ],
            },
        },
    )
    export_out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "distillation_export_build",
            "args": {
                "output_dir": "distill_export",
                "distillation_plan": plan,
                "teacher_output_review": review_out["review"],
            },
        },
    )

    assert batch_out["ok"] is True
    assert execution_out["ok"] is True
    assert execution_out["plan"]["mode"] == "dry_run"
    assert dry_run_out["ok"] is True
    assert dry_run_out["result"]["counts"]["teacher_outputs"] == 0
    assert review_out["ok"] is True
    assert export_out["ok"] is True
    assert Path(export_out["files"]["training_examples"]).exists()
