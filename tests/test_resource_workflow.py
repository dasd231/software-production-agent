from __future__ import annotations

import json
from pathlib import Path

from agent.resources.registry import discover_resources
from agent.innovation.radar import build_innovation_radar
from agent.workflows.spec import validate_workflow_spec


def test_resource_registry_discovers_chains_models_and_local_artifacts(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    run = tmp_path / "run_demo"
    run.mkdir()
    (run / "solution_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "solution_manifest.v2",
                "acceptance_status": "accepted",
                "template": "spring-vue",
                "goal": "employee management",
                "stack": "Spring + Vue",
                "retrieval_tags": ["employee", "crud"],
                "quality_score": 8.1,
            }
        ),
        encoding="utf-8",
    )
    learning = tmp_path / "learning"
    learning.mkdir()
    (learning / "knowledge_cards.json").write_text("[]", encoding="utf-8")
    (learning / "vector_index.jsonl").write_text("", encoding="utf-8")
    (learning / "knowledge_promotion.json").write_text(
        json.dumps({"schema": "knowledge_promotion.v1", "summary": {"promoted": 1, "rejected": 0}}),
        encoding="utf-8",
    )
    (learning / "knowledge_quality_report.json").write_text(
        json.dumps({"schema": "knowledge_quality_run.v1", "aggregate": {"overall_score": 8.8, "grade": "excellent"}}),
        encoding="utf-8",
    )
    model_run = tmp_path / "model_run"
    model_run.mkdir()
    (model_run / "model_version_manifest.json").write_text(
        json.dumps(
            {
                "schema": "model_version_manifest.v1",
                "model_version": "backup-demo",
                "role": "backup_local_model",
                "base_model": "demo/base",
                "adapter_name": "backup-lora",
                "rollout_stage": "candidate",
            }
        ),
        encoding="utf-8",
    )
    (model_run / "training_job_manifest.json").write_text(
        json.dumps(
            {
                "schema": "training_job_manifest.v1",
                "job_id": "job-demo",
                "backend": "local_trl",
                "execution_target": "local",
                "current_status": "queued",
            }
        ),
        encoding="utf-8",
    )
    (model_run / "model_promotion_decision.json").write_text(
        json.dumps(
            {
                "schema": "model_promotion_decision.v1",
                "passed": True,
                "status": "ready_for_manual_review",
                "candidate": {
                    "label": "candidate",
                    "model_version": "backup-demo",
                    "benchmark_id": "backup_model_eval.v3.json",
                },
            }
        ),
        encoding="utf-8",
    )
    (model_run / "distributed_job_manifest.json").write_text(
        json.dumps(
            {
                "schema": "distributed_job_manifest.v1",
                "job_id": "distributed-demo",
                "backend": "ray_cluster",
                "workload": "benchmark_evaluation",
                "queue": "evaluation",
                "current_status": "planned",
            }
        ),
        encoding="utf-8",
    )
    (learning / "dataset_snapshot_manifest.json").write_text(
        json.dumps(
            {
                "schema": "dataset_snapshot_manifest.v1",
                "dataset_id": "dataset-demo",
                "counts": {"train_examples": 3, "eval_examples": 1},
                "sharding": {"enabled": True},
            }
        ),
        encoding="utf-8",
    )

    registry = discover_resources(ws, roots=(tmp_path,))
    types = {row["type"] for row in registry["resources"]}

    assert "chain" in types
    assert "model_provider" in types
    assert "model_runtime" in types
    assert "distributed_backend" in types
    assert "distributed_platform_plan" in types
    assert "distributed_workload" in types
    assert "distributed_job" in types
    assert "solution" in types
    assert "knowledge_store" in types
    assert "model_version" in types
    assert "model_promotion_decision" in types
    assert "dataset_snapshot" in types
    assert "training_job" in types
    assert registry["summary"]["total"] >= 4
    knowledge = next(row for row in registry["resources"] if row["type"] == "knowledge_store")
    assert knowledge["metadata"]["quality_gated"] is True
    assert knowledge["metadata"]["quality_grade"] == "excellent"


def test_workflow_validate_orders_known_chains() -> None:
    out = validate_workflow_spec(
        {
            "schema": "workflow.v1",
            "version": "demo",
            "nodes": [{"id": "research", "chain": "research"}, {"id": "train", "chain": "training"}],
            "edges": [["research", "train"]],
        }
    )

    assert out["ok"] is True
    assert out["execution_order"] == ["research", "train"]
    assert "solution:read" in out["permissions"]


def test_workflow_validate_rejects_cycles() -> None:
    out = validate_workflow_spec(
        {
            "schema": "workflow.v1",
            "version": "demo",
            "nodes": ["research", "training"],
            "edges": [["research", "training"], ["training", "research"]],
        }
    )

    assert out["ok"] is False
    assert "workflow graph has a cycle" in out["errors"]


def test_innovation_radar_builds_signature_cards(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    radar = build_innovation_radar(ws, roots=(tmp_path,))

    assert radar["schema"] == "innovation_radar.v1"
    assert "证据驱动" in radar["north_star"]
    assert radar["innovation_cards"]
    assert radar["workflow_templates"]
    assert radar["recommended_next_build"]["score"] >= 0
