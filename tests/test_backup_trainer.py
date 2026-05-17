from __future__ import annotations

import json
from pathlib import Path

from agent.training.backup_trainer import finalize_training_artifacts, render_training_row
from agent.training.jobs import create_training_job_manifest, write_training_job_manifest


class _Tokenizer:
    def apply_chat_template(self, messages, *, tokenize: bool, add_generation_prompt: bool) -> str:
        assert tokenize is False
        assert add_generation_prompt is False
        return " | ".join(f"{row['role']}:{row['content']}" for row in messages)


def test_render_training_row_supports_messages_format() -> None:
    text = render_training_row(
        {
            "messages": [
                {"role": "system", "content": "规则"},
                {"role": "user", "content": "问题"},
                {"role": "assistant", "content": "答案"},
            ]
        },
        _Tokenizer(),
    )

    assert text == "system:规则 | user:问题 | assistant:答案"


def test_render_training_row_supports_alpaca_format() -> None:
    text = render_training_row(
        {
            "instruction": "回答问题",
            "input": "问题",
            "output": "答案",
        },
        _Tokenizer(),
    )

    assert text == "user:回答问题\n\n输入：\n问题 | assistant:答案"


def test_finalize_training_artifacts_updates_manifests(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    adapter_dir = run_dir / "adapter"
    adapter_dir.mkdir(parents=True)
    spec_path = run_dir / "backup_training_spec.json"
    spec_path.write_text("{}", encoding="utf-8")
    (run_dir / "model_version_manifest.json").write_text(
        json.dumps({"rollout_stage": "candidate"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"files": {}, "artifacts": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")
    (adapter_dir / "training_result.json").write_text("{}", encoding="utf-8")
    write_training_job_manifest(
        run_dir / "training_job_manifest.json",
        create_training_job_manifest(
            job_id="job-demo",
            spec_path=run_dir / "training_job_spec.json",
            dataset_snapshot_id="dataset-demo",
            backend="local_trl",
            execution_target="local",
        ),
    )

    finalize_training_artifacts(
        spec_path,
        {
            "output_dir": str(adapter_dir),
            "metrics": {"train_loss": 2.0},
            "eval_metrics": {"eval_loss": 1.5},
        },
    )
    finalize_training_artifacts(
        spec_path,
        {
            "output_dir": str(adapter_dir),
            "metrics": {"train_loss": 2.0},
            "eval_metrics": {"eval_loss": 1.5},
        },
    )

    version = json.loads((run_dir / "model_version_manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    report = (run_dir / "report.md").read_text(encoding="utf-8")
    assert version["rollout_stage"] == "trained"
    assert version["metrics"]["eval"]["eval_loss"] == 1.5
    assert manifest["training"]["status"] == "completed"
    assert str(adapter_dir) in manifest["artifacts"]
    assert report.count("## Training Result") == 1
    training_job = json.loads((run_dir / "training_job_manifest.json").read_text(encoding="utf-8"))
    assert training_job["current_status"] == "completed"
