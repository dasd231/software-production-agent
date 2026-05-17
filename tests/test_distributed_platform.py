from __future__ import annotations

from agent.distributed.backends import RayClusterBackend, list_distributed_backends
from agent.distributed.dispatch import build_distributed_job_plan
from agent.distributed.manifests import build_distributed_job_manifest
from agent.distributed.plans import build_distributed_platform_plan
from agent.distributed.workloads import get_distributed_workload, list_distributed_workloads
from agent.core.executor import run_action
from pathlib import Path


def test_ray_cluster_backend_builds_contract_only_submission_plan() -> None:
    backend = RayClusterBackend()
    plan = backend.build_submission_plan(
        job_id="job-demo",
        workload="benchmark_evaluations",
        entrypoint="python -m agent.training.backup_eval",
        resources={"cpu": 2},
    )

    assert backend.describe()["name"] == "ray_cluster"
    assert plan["schema"] == "ray_submission_plan.v1"
    assert plan["resources"]["cpu"] == 2
    assert plan["submission_mode"] == "contract_only"


def test_distributed_job_manifest_starts_planned_without_dispatch() -> None:
    manifest = build_distributed_job_manifest(
        job_id="job-demo",
        backend="ray_cluster",
        workload="learning_run",
        resources={"gpu": 0},
    )

    assert manifest["schema"] == "distributed_job_manifest.v1"
    assert manifest["current_status"] == "planned"
    assert manifest["runtime"]["remote_job_id"] == ""
    assert manifest["queue"] == "learning"
    assert manifest["resources"]["cpu"] == 2


def test_distributed_platform_plan_keeps_data_planes_separate() -> None:
    plan = build_distributed_platform_plan()
    planes = {row["name"]: row for row in plan["planes"]}

    assert list_distributed_backends()[0]["name"] == "ray_cluster"
    assert planes["execution_plane"]["primary"] == "Ray"
    assert planes["batch_data_plane"]["primary"] == "Spark"
    assert planes["streaming_data_plane"]["primary"] == "Flink"


def test_distributed_platform_plan_action_dispatches(tmp_path: Path) -> None:
    out = run_action(tmp_path, {"type": "action", "action": "distributed_platform_plan", "args": {}})

    assert out["ok"] is True
    assert out["plan"]["schema"] == "distributed_platform_plan.v1"


def test_distributed_workload_catalog_has_expected_operational_defaults(tmp_path: Path) -> None:
    workloads = {row["id"]: row for row in list_distributed_workloads()}
    training = get_distributed_workload("training_dispatch")
    out = run_action(tmp_path, {"type": "action", "action": "distributed_workload_catalog", "args": {}})

    assert workloads["benchmark_evaluation"]["queue"] == "evaluation"
    assert workloads["promotion_gate"]["priority"] == "high"
    assert training and training["resources"]["gpu"] == 1
    assert out["ok"] is True
    assert len(out["workloads"]) >= 5


def test_distributed_job_plan_previews_manifest_and_submission(tmp_path: Path) -> None:
    plan = build_distributed_job_plan(job_id="job-demo", workload="promotion_gate")
    out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "distributed_job_plan",
            "args": {"job_id": "job-demo", "workload": "promotion_gate"},
        },
    )

    assert plan["dispatch_mode"] == "preview_only"
    assert plan["manifest"]["queue"] == "governance"
    assert plan["submission"]["queue"] == "governance"
    assert out["ok"] is True
    assert out["plan"]["submission"]["backend"] == "ray_cluster"
