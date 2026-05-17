from __future__ import annotations

import json
from pathlib import Path

from agent.training.datasets import build_dataset_storage_profile, create_dataset_snapshot
from agent.training.jobs import create_training_job_manifest, transition_training_job, update_training_job_runtime
from agent.training.runners.linux_remote import LinuxRemoteRunner
from agent.training.runners.local_trl import LocalTRLRunner
from agent.training.runners.ray_cluster import RayClusterRunner
from agent.training.specs import build_training_job_spec


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_create_dataset_snapshot_builds_traceable_shards(tmp_path: Path) -> None:
    training = tmp_path / "training"
    rows = [
        {"messages": [], "metadata": {"task_type": "grounded_answer"}},
        {"messages": [], "metadata": {"task_type": "action_protocol_sft"}},
        {"messages": [], "metadata": {"task_type": "action_protocol_sft"}},
    ]
    _write_jsonl(training / "dataset.jsonl", rows)
    _write_jsonl(training / "train.jsonl", rows[:2])
    _write_jsonl(training / "eval.jsonl", rows[2:])
    (training / "quality_report.json").write_text('{"evaluation_score":9.1}', encoding="utf-8")
    (training / "sample_quality_report.json").write_text('{"overall_score":9.2}', encoding="utf-8")
    (training / "governance_report.json").write_text('{"grade":"excellent"}', encoding="utf-8")
    (training / "evaluation_report.json").write_text("{}", encoding="utf-8")
    (training / "run_manifest.json").write_text(
        json.dumps({"manifest_id": "run-demo", "source_refs": [{"type": "learning_dir", "path": "x"}]}),
        encoding="utf-8",
    )

    snapshot = create_dataset_snapshot(training, shard_size=1)

    assert snapshot["schema"] == "dataset_snapshot_manifest.v1"
    assert snapshot["source_manifest_id"] == "run-demo"
    assert snapshot["counts"]["train_examples"] == 2
    assert snapshot["task_mix"]["dataset"]["action_protocol_sft"] == 2
    assert snapshot["storage_profile"]["migration_state"] == "local_jsonl"
    assert len(snapshot["sharding"]["shards"]) == 3
    assert (training / "dataset_snapshot_manifest.json").exists()


def test_training_job_spec_and_manifest_capture_execution_contract(tmp_path: Path) -> None:
    snapshot = {
        "dataset_id": "dataset-demo",
        "training_dir": str(tmp_path / "training"),
        "files": {
            "train": {"path": "train.jsonl"},
            "eval": {"path": "eval.jsonl"},
        },
        "sharding": {"shards": []},
    }
    spec = build_training_job_spec(
        base_model="demo/base",
        adapter_name="demo-adapter",
        dataset_snapshot=snapshot,
        backend="local_trl",
        hyperparameters={"learning_rate": 2e-4},
        evaluation_benchmark="./benchmarks/demo.json",
        output_dir=tmp_path / "run",
    )
    manifest = create_training_job_manifest(
        job_id=spec["job_spec_id"],
        spec_path=tmp_path / "run" / "training_job_spec.json",
        dataset_snapshot_id="dataset-demo",
        backend="local_trl",
        execution_target="local",
    )
    manifest = transition_training_job(manifest, "validated", detail="ok")
    manifest = transition_training_job(manifest, "queued", detail="ready")

    assert spec["schema"] == "training_job_spec.v1"
    assert spec["dataset_snapshot"]["dataset_id"] == "dataset-demo"
    assert spec["execution_profile"]["profile_id"] == "local_default"
    assert spec["sync_contract"]["verification"]["verify_input_hashes"] is True
    assert spec["resume_policy"]["enabled"] is True
    assert spec["retry_policy"]["max_attempts"] == 2
    assert spec["evaluation"]["required_before_promotion"] is True
    assert manifest["current_status"] == "queued"
    assert [row["status"] for row in manifest["status_history"]] == ["created", "validated", "queued"]
    assert LocalTRLRunner().build_launch_command(Path("spec.json")).endswith('"spec.json"')


def test_training_job_manifest_tracks_remote_runtime_fields(tmp_path: Path) -> None:
    manifest = create_training_job_manifest(
        job_id="job-demo",
        spec_path=tmp_path / "training_job_spec.json",
        dataset_snapshot_id="dataset-demo",
        backend="linux_remote",
        execution_target="remote_linux",
    )
    manifest = update_training_job_runtime(
        manifest,
        remote_job_id="slurm-42",
        execution_host="gpu-a100-01",
        resume_from_checkpoint="/checkpoints/step-200",
        heartbeat=True,
        failure_classification="preempted",
        retry_count=1,
    )

    assert manifest["remote_job_id"] == "slurm-42"
    assert manifest["execution_host"] == "gpu-a100-01"
    assert manifest["resume_from_checkpoint"].endswith("step-200")
    assert manifest["last_heartbeat_at"]
    assert manifest["failure_classification"] == "preempted"
    assert manifest["retry_count"] == 1
    assert LinuxRemoteRunner().describe()["dispatch_mode"] == "contract_only"


def test_training_job_spec_supports_ray_cluster_profile(tmp_path: Path) -> None:
    snapshot = {
        "dataset_id": "dataset-demo",
        "training_dir": str(tmp_path / "training"),
        "files": {"train": {"path": "train.jsonl"}, "eval": {"path": "eval.jsonl"}},
        "sharding": {"shards": []},
    }
    spec = build_training_job_spec(
        base_model="demo/base",
        adapter_name="demo-adapter",
        dataset_snapshot=snapshot,
        backend="ray_cluster",
        hyperparameters={"learning_rate": 2e-4},
        output_dir=tmp_path / "run",
    )

    assert spec["execution_profile"]["profile_id"] == "ray_cluster_default"
    assert spec["execution_profile"]["scheduler"] == "ray_jobs"
    assert RayClusterRunner().describe()["dispatch_mode"] == "contract_only"


def test_dataset_storage_profile_can_plan_future_parquet_without_copying_data(tmp_path: Path) -> None:
    profile = build_dataset_storage_profile(
        training_dir=tmp_path / "training",
        dataset_id="dataset-demo",
        preferred_format="parquet",
        object_store_uri="s3://datasets/demo",
    )

    assert profile["current_format"] == "jsonl"
    assert profile["preferred_format"] == "parquet"
    assert profile["spark_ready"] is True
    assert profile["migration_state"] == "parquet_planned"
