from __future__ import annotations

import json
from pathlib import Path

from agent.chains.model_training import BackupModelTrainInput, prepare_backup_model_training


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _make_training_dir(root: Path, *, examples: int = 2, sample_score: float = 8.2) -> Path:
    training = root / "training"
    _write_jsonl(training / "train.jsonl", [{"messages": []} for _ in range(examples)])
    _write_jsonl(training / "eval.jsonl", [{"messages": []}])
    (training / "training_plan.json").write_text(
        json.dumps({"base_model": "demo/base-model", "dataset_format": "messages"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (training / "sample_quality_report.json").write_text(
        json.dumps({"overall_score": sample_score, "grade": "excellent"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (training / "governance_report.json").write_text(
        json.dumps(
            {
                "grade": "good",
                "metrics": {"secret_scan": {"status": "ok"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return training


def test_prepare_backup_model_training_blocks_when_environment_not_ready(tmp_path: Path, monkeypatch) -> None:
    training = _make_training_dir(tmp_path, examples=2)

    monkeypatch.setattr(
        "agent.chains.model_training.detect_training_environment",
        lambda: {
            "schema": "backup_training_environment.v1",
            "packages": {"torch": True, "transformers": True, "datasets": False, "peft": False, "trl": False},
            "missing_packages": ["datasets", "peft", "trl"],
            "torch_version": "2.x",
            "cuda_available": False,
            "cuda_device_count": 0,
            "ready": False,
        },
    )
    result = prepare_backup_model_training(
        BackupModelTrainInput(
            training_dir=training,
            output_dir=tmp_path / "backup_out",
            min_train_examples=1,
        )
    )

    assert result.status == "blocked_environment"
    assert result.launchable is False
    assert Path(result.files["model_version_manifest"]).exists()
    assert Path(result.files["training_job_spec"]).exists()
    assert Path(result.files["training_job_manifest"]).exists()
    assert result.model_version["role"] == "backup_local_model"


def test_prepare_backup_model_training_can_be_launch_ready(tmp_path: Path, monkeypatch) -> None:
    training = _make_training_dir(tmp_path, examples=3)
    monkeypatch.setattr(
        "agent.chains.model_training.detect_training_environment",
        lambda: {
            "schema": "backup_training_environment.v1",
            "packages": {"torch": True, "transformers": True, "datasets": True, "peft": True, "trl": True},
            "missing_packages": [],
            "torch_version": "2.x",
            "cuda_available": True,
            "cuda_device_count": 1,
            "ready": True,
        },
    )
    result = prepare_backup_model_training(
        BackupModelTrainInput(
            training_dir=training,
            output_dir=tmp_path / "backup_ready",
            min_train_examples=1,
            launch=True,
        )
    )

    assert result.status == "launch_ready"
    assert result.launchable is True
    assert result.spec["base_model"] == "demo/base-model"
    assert result.spec["training_job_spec"]["schema"] == "training_job_spec.v1"
    assert Path(result.files["launch_command"]).exists()
