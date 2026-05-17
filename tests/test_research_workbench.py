from __future__ import annotations

from scripts.update_research_workbench import (
    _accepted_example_count,
    _dataset_evolution,
    _distributed_dispatch_candidates,
    _distributed_execution_overview,
    _platform_evolution,
    _project_model_program_overview,
    _training_platform_blueprint_overview,
    _distillation_overview,
    _experiment_queue,
    _promotion_overview,
    _task_balance_snapshot,
    _training_lineage,
    _training_remediation,
)


def test_training_lineage_attaches_promotion_decisions_to_model_versions() -> None:
    lineage = _training_lineage(
        [
            {
                "dataset_id": "dataset-demo",
                "name": "training-demo",
                "quality_score": 9.1,
                "quality_grade": "excellent",
                "task_mix": {"action_protocol_sft": 4},
            }
        ],
        [
            {
                "name": "model-demo",
                "model_version": "backup-demo",
                "base_model": "demo/base",
                "rollout_stage": "trained",
                "training_job_spec_id": "jobspec-demo",
                "job_status": "completed",
                "dataset_snapshot_id": "dataset-demo",
            }
        ],
        [
            {
                "name": "eval-demo",
                "label": "candidate",
                "benchmark_id": "backup_model_eval.v3.json",
                "overall_score": 7.8,
                "grade": "good",
                "subject": {"model_version": "backup-demo"},
            }
        ],
        [
            {
                "name": "decision-demo",
                "label": "candidate",
                "benchmark_id": "backup_model_eval.v3.json",
                "model_version": "backup-demo",
                "status": "ready_for_manual_review",
                "passed": True,
            }
        ],
    )

    model = lineage["datasets"][0]["model_runs"][0]
    assert model["evaluations"][0]["evaluation_run"] == "eval-demo"
    assert model["promotion_decisions"][0]["decision_run"] == "decision-demo"
    assert lineage["unlinked_promotion_decisions"] == []


def test_training_lineage_separates_baselines_from_unlinked_candidates() -> None:
    lineage = _training_lineage(
        [],
        [],
        [
            {
                "name": "base-demo",
                "label": "qwen_base_benchv3",
                "benchmark_id": "backup_model_eval.v3.json",
                "overall_score": 8.1,
                "grade": "good",
                "subject": {},
            },
            {
                "name": "candidate-demo",
                "label": "tuned_demo",
                "benchmark_id": "backup_model_eval.v3.json",
                "overall_score": 7.2,
                "grade": "good",
                "subject": {},
            },
        ],
        [],
    )

    assert lineage["baseline_evaluations"][0]["evaluation_run"] == "base-demo"
    assert lineage["unlinked_candidate_evaluations"][0]["evaluation_run"] == "candidate-demo"


def test_promotion_overview_counts_failed_checks() -> None:
    overview = _promotion_overview(
        [
            {
                "name": "decision-a",
                "label": "candidate-a",
                "model_version": "backup-a",
                "benchmark_id": "bench.json",
                "status": "blocked",
                "passed": False,
                "checks": [
                    {"name": "overall_delta_vs_baseline", "passed": False},
                    {"name": "stage_floor:model_eval.action_protocol", "passed": False},
                ],
            },
            {
                "name": "decision-b",
                "label": "candidate-b",
                "model_version": "backup-b",
                "benchmark_id": "bench.json",
                "status": "blocked",
                "passed": False,
                "checks": [
                    {"name": "overall_delta_vs_baseline", "passed": False},
                ],
            },
        ]
    )

    assert overview["summary"]["blocked"] == 2
    assert overview["failed_check_counts"][0] == {"check": "overall_delta_vs_baseline", "count": 2}


def test_training_remediation_maps_actions_to_underrepresented_tasks() -> None:
    remediation = _training_remediation(
        [
            {
                "name": "training-demo",
                "dataset_id": "dataset-demo",
                "task_mix": {
                    "action_protocol_sft": 24,
                    "rag_grounded_answer": 1,
                    "solution_reuse_sft": 4,
                },
            }
        ],
        [
            {
                "name": "model-demo",
                "model_version": "backup-demo",
                "dataset_snapshot_id": "dataset-demo",
            }
        ],
        [
            {
                "model_version": "backup-demo",
                "recommended_actions": [
                    "rebalance_grounded_answer_supervision",
                    "increase_solution_reuse_supervision",
                ],
            }
        ],
    )

    row = remediation["rows"][0]
    assert row["task_support"]["rag_grounded_answer"] == 1
    assert {item["task"] for item in row["underrepresented_tasks"]} == {
        "rag_grounded_answer",
        "solution_reuse_sft",
    }


def test_research_workbench_prefers_accepted_examples_over_raw_examples() -> None:
    total = _accepted_example_count(
        quality={"raw_examples": 132, "with_citations": 112},
        evaluation={"metrics": {"example_count": {"value": 112}}},
        snapshot={"counts": {"dataset_examples": 112}},
        task_mix={"rag_grounded_answer": 10, "action_protocol_sft": 34},
    )

    assert total == 112


def test_task_balance_snapshot_derives_watch_signal_for_legacy_runs() -> None:
    balance = _task_balance_snapshot(
        task_mix={
            "knowledge_card_qa": 30,
            "code_explanation": 31,
            "rag_grounded_answer": 1,
            "solution_reuse_sft": 7,
            "action_protocol_sft": 34,
        }
    )

    assert balance["min_task_share"] == 0.0097
    assert balance["task_balance_status"] == "watch"
    assert balance["rarest_tasks"] == ["rag_grounded_answer"]


def test_experiment_queue_prioritizes_next_executable_step() -> None:
    queue = _experiment_queue(
        [
            {
                "dataset_id": "dataset-ready",
                "task_balance_status": "ok",
                "min_task_share": 0.08,
            },
            {
                "dataset_id": "dataset-watch",
                "task_balance_status": "watch",
                "min_task_share": 0.01,
            },
        ],
        [
            {
                "name": "model-queued",
                "model_version": "backup-queued",
                "dataset_snapshot_id": "dataset-ready",
                "job_status": "queued",
                "rollout_stage": "candidate",
            },
            {
                "name": "model-trained",
                "model_version": "backup-trained",
                "dataset_snapshot_id": "dataset-ready",
                "job_status": "completed",
                "rollout_stage": "trained",
            },
            {
                "name": "model-evaluated",
                "model_version": "backup-evaluated",
                "dataset_snapshot_id": "dataset-watch",
                "job_status": "completed",
                "rollout_stage": "trained",
            },
            {
                "name": "model-blocked",
                "model_version": "backup-blocked",
                "dataset_snapshot_id": "dataset-watch",
                "job_status": "completed",
                "rollout_stage": "trained",
            },
        ],
        [
            {"name": "eval-trained", "subject": {"model_version": "backup-evaluated"}},
            {"name": "eval-blocked", "subject": {"model_version": "backup-blocked"}},
        ],
        [
            {"model_version": "backup-blocked", "status": "blocked", "passed": False},
        ],
    )

    rows = {row["model_run"]: row for row in queue["rows"]}
    assert rows["model-queued"]["next_action"] == "execute_training_job"
    assert rows["model-trained"]["next_action"] == "run_benchmark_evaluation"
    assert rows["model-evaluated"]["next_action"] == "run_promotion_gate"
    assert rows["model-blocked"]["next_action"] == "apply_remediation_then_retrain"


def test_dataset_evolution_summarizes_rebalanced_progress() -> None:
    evolution = _dataset_evolution(
        [
            {
                "name": "protocol_old",
                "dataset_id": "dataset-old",
                "total_examples": 100,
                "min_task_share": 0.01,
                "task_balance_status": "watch",
                "task_mix": {"rag_grounded_answer": 1, "action_protocol_sft": 30},
            },
            {
                "name": "protocol_rebalanced",
                "dataset_id": "dataset-new",
                "total_examples": 112,
                "min_task_share": 0.08,
                "task_balance_status": "ok",
                "task_mix": {"rag_grounded_answer": 10, "action_protocol_sft": 34},
            },
        ],
        [
            {
                "name": "candidate-new",
                "dataset_snapshot_id": "dataset-new",
                "rollout_stage": "candidate",
            }
        ],
    )

    assert evolution["summary"]["balanced_datasets"] == 1
    assert any("1 to 10" in item for item in evolution["observations"])
    assert evolution["rows"][1]["has_candidate_model"] is True


def test_platform_evolution_tracks_ray_spark_flink_layering() -> None:
    evolution = _platform_evolution()
    rows = {row["name"]: row for row in evolution["rows"]}

    assert evolution["schema"] == "research_platform_evolution.v1"
    assert rows["execution_plane"]["primary"] == "Ray"
    assert rows["batch_data_plane"]["primary"] == "Spark"
    assert rows["streaming_data_plane"]["primary"] == "Flink"


def test_distributed_execution_overview_summarizes_catalog() -> None:
    overview = _distributed_execution_overview()

    assert overview["schema"] == "research_distributed_execution_overview.v1"
    assert overview["summary"]["workloads"] >= 5
    assert "training" in overview["queue_counts"]
    assert "training_dispatch" in overview["gpu_workloads"]


def test_distributed_dispatch_candidates_only_wrap_executable_actions() -> None:
    payload = _distributed_dispatch_candidates(
        {
            "rows": [
                {"model_run": "candidate-a", "next_action": "execute_training_job", "reason": "queued"},
                {"model_run": "candidate-b", "next_action": "run_benchmark_evaluation", "reason": "trained"},
                {"model_run": "candidate-c", "next_action": "apply_remediation_then_retrain", "reason": "blocked"},
            ]
        }
    )

    assert payload["summary"]["dispatchable"] == 2
    assert {row["workload"] for row in payload["rows"]} == {"training_dispatch", "benchmark_evaluation"}


def test_project_model_program_overview_exposes_repo_model_blueprint() -> None:
    overview = _project_model_program_overview()

    assert overview["schema"] == "research_project_model_program.v1"
    assert overview["validation"]["ok"] is True
    assert overview["recommended_first_build"]["id"] == "repo_memory_v1"
    assert any(row["id"] == "retrieval_grounded_understanding" for row in overview["stages"])


def test_training_platform_blueprint_overview_keeps_route_memory() -> None:
    overview = _training_platform_blueprint_overview()

    assert overview["schema"] == "research_training_platform_blueprint.v1"
    assert overview["current_priority"]["route"] == "B"
    assert len(overview["planes"]) == 4


def test_distillation_overview_exposes_teacher_catalog() -> None:
    overview = _distillation_overview()

    assert overview["schema"] == "research_distillation_overview.v1"
    assert overview["summary"]["teachers"] >= 3
    assert overview["summary"]["teacher_tasks"] >= 5
    assert overview["summary"]["pipeline_stages"] == 4
    assert overview["pipeline"][1]["id"] == "teacher_execution_plan"
