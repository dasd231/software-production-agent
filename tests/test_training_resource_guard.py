from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent.training.resource_guard import (
    build_training_resource_policy,
    evaluate_training_resource_admission,
    probe_gpu_inventory,
)
from agent.training.safe_launcher import launch_with_guard


def test_training_resource_guard_blocks_foreign_compute_processes() -> None:
    policy = build_training_resource_policy()
    admission = evaluate_training_resource_admission(
        policy=policy,
        probe={
            "ok": True,
            "gpus": [
                {
                    "index": 0,
                    "memory_total_mb": 24576,
                    "memory_used_mb": 512,
                    "utilization_gpu_pct": 3,
                }
            ],
            "compute_processes": [{"pid": 123, "process_name": "python", "used_memory_mb": 1024}],
        },
    )

    assert admission["admitted"] is False
    assert "foreign_compute_processes_present" in admission["blockers"]


def test_gpu_probe_parses_nvidia_smi_csv() -> None:
    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        if "--query-gpu=index,name,memory.total,memory.used,utilization.gpu" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "0, NVIDIA GeForce RTX 3090, 24576, 1024, 5\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    probe = probe_gpu_inventory(runner=fake_runner)

    assert probe["ok"] is True
    assert probe["gpus"][0]["memory_total_mb"] == 24576
    assert probe["gpus"][0]["utilization_gpu_pct"] == 5


def test_safe_launcher_writes_preflight_and_blocks_shared_gpu(tmp_path: Path, monkeypatch) -> None:
    spec_path = tmp_path / "backup_training_spec.json"
    spec_path.write_text("{}", encoding="utf-8")
    (tmp_path / "training_job_spec.json").write_text(
        json.dumps({"resource_policy": build_training_resource_policy()}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agent.training.safe_launcher.run_server_resource_preflight",
        lambda policy: {
            "schema": "training_server_preflight.v1",
            "policy": policy,
            "admission": {"admitted": False, "blockers": ["foreign_compute_processes_present"]},
        },
    )

    result = launch_with_guard(spec_path)

    assert result["status"] == "blocked_shared_resource"
    assert (tmp_path / "resource_preflight.json").exists()
