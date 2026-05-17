from __future__ import annotations

import json
from pathlib import Path

from agent.training.lineage_backfill import infer_benchmark_id, run_lineage_backfill


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _report(label: str, case_ids: list[str]) -> dict:
    return {
        "schema": "model_evaluation_report.v1",
        "label": label,
        "summary": {"overall_score": 7.5, "grade": "good"},
        "reports": [
            {"stage": "model_eval.action_protocol", "overall_score": 7.0},
            {"stage": "model_eval.grounded_answer", "overall_score": 7.1},
            {"stage": "model_eval.solution_reuse", "overall_score": 6.8},
        ],
        "cases": [{"case_id": case_id} for case_id in case_ids],
    }


def test_infer_benchmark_id_uses_exact_case_signature(tmp_path: Path) -> None:
    benchmark_dir = tmp_path / "benchmarks"
    _write_json(
        benchmark_dir / "demo.json",
        {"cases": [{"case_id": "a"}, {"case_id": "b"}]},
    )

    assert infer_benchmark_id(_report("candidate", ["a", "b"]), benchmark_dir) == "demo.json"
    assert infer_benchmark_id(_report("candidate", ["b", "a"]), benchmark_dir) == ""


def test_run_lineage_backfill_reconstructs_legacy_artifacts_and_links_eval(tmp_path: Path) -> None:
    root = tmp_path
    training_dir = root / "training_runs" / "demo"
    model_run = root / "model_runs" / "backup_demo"
    candidate_eval = root / "model_evals" / "candidate_eval"
    baseline_eval = root / "model_evals" / "baseline_eval"
    benchmark_dir = root / "benchmarks"
    _write_json(
        training_dir / "dataset_snapshot_manifest.json",
        {
            "schema": "dataset_snapshot_manifest.v1",
            "dataset_id": "dataset-demo",
            "training_dir": str(training_dir),
            "files": {"train": {"path": "train.jsonl"}, "eval": {"path": "eval.jsonl"}},
            "sharding": {"shards": []},
        },
    )
    _write_json(
        model_run / "backup_training_spec.json",
        {
            "schema": "backup_model_training_spec.v1",
            "base_model": "demo/base",
            "adapter_name": "demo-adapter",
            "hyperparameters": {"learning_rate": 2e-4},
        },
    )
    _write_json(
        model_run / "model_version_manifest.json",
        {
            "schema": "model_version_manifest.v1",
            "model_version": "backup-demo",
            "base_model": "demo/base",
            "adapter_name": "demo-adapter",
            "training_dir": str(training_dir),
            "rollout_stage": "trained",
            "training_status": "completed",
        },
    )
    _write_json(
        model_run / "run_manifest.json",
        {
            "schema": "run_manifest.v1",
            "kind": "backup_model_training",
            "input_summary": {},
            "files": {},
            "artifacts": [],
        },
    )
    _write_json(
        benchmark_dir / "demo.json",
        {"cases": [{"case_id": "a"}, {"case_id": "b"}]},
    )
    _write_json(candidate_eval / "model_evaluation_report.json", _report("candidate", ["a", "b"]))
    _write_json(baseline_eval / "model_evaluation_report.json", _report("baseline", ["a", "b"]))
    overrides = root / "research_workbench" / "lineage_overrides.json"
    _write_json(
        overrides,
        {
            "schema": "lineage_backfill_overrides.v1",
            "evaluation_links": [
                {
                    "evaluation_run": "candidate_eval",
                    "model_run": "backup_demo",
                    "baseline_evaluation_run": "baseline_eval",
                }
            ],
        },
    )

    report = run_lineage_backfill(root, overrides_path=overrides, apply=True)

    version = json.loads((model_run / "model_version_manifest.json").read_text(encoding="utf-8"))
    candidate = json.loads((candidate_eval / "model_evaluation_report.json").read_text(encoding="utf-8"))
    assert report["summary"]["changed_model_runs"] == 1
    assert version["dataset_snapshot_id"] == "dataset-demo"
    assert version["training_job_spec_id"].startswith("jobspec-")
    assert (model_run / "training_job_spec.json").exists()
    assert (model_run / "training_job_manifest.json").exists()
    assert candidate["benchmark_id"] == "demo.json"
    assert candidate["subject"]["model_version"] == "backup-demo"
    assert (candidate_eval / "model_promotion_decision.json").exists()

    second = run_lineage_backfill(root, overrides_path=overrides, apply=True)
    assert second["summary"]["changed_model_runs"] == 0
    assert second["summary"]["benchmark_ids_backfilled"] == 0
    assert second["summary"]["evaluation_links_backfilled"] == 0
    assert second["summary"]["promotion_decisions_generated"] == 0
    assert second["summary"]["baseline_only_evaluations"] == 1
    assert second["summary"]["unresolved_candidate_evaluations"] == 0
