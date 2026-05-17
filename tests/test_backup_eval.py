from __future__ import annotations

from agent.training.backup_eval import _system_prompt_for, build_evaluation_subject


def test_action_protocol_eval_uses_real_action_schema_prompt() -> None:
    prompt = _system_prompt_for("action_protocol")

    assert "每次只输出一行合法 JSON" in prompt
    assert "training_prepare" in prompt
    assert "backup_model_train" in prompt


def test_text_eval_uses_lightweight_default_prompt() -> None:
    prompt = _system_prompt_for("grounded_answer")

    assert "可审计的软件生产 Agent" in prompt
    assert "training_prepare" not in prompt


def test_evaluation_subjects_distinguish_baselines_and_model_versions() -> None:
    baseline = build_evaluation_subject(base_model="demo/base")
    candidate = build_evaluation_subject(
        base_model="demo/base",
        model_version={
            "model_version": "backup-demo",
            "base_model": "demo/base",
            "adapter_name": "demo-adapter",
            "dataset_snapshot_id": "dataset-demo",
            "training_job_spec_id": "jobspec-demo",
        },
    )
    untracked = build_evaluation_subject(base_model="demo/base", adapter_dir="./adapter")

    assert baseline["subject_type"] == "base_model"
    assert candidate["subject_type"] == "model_version"
    assert candidate["model_version"] == "backup-demo"
    assert untracked["subject_type"] == "untracked_adapter"
