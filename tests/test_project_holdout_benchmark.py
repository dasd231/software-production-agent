from __future__ import annotations

import json
from pathlib import Path

from agent.chains.github_crawler import CrawlProfileInput, crawl_frontend_backend_repos
from agent.core.executor import run_action
from agent.corpus_intelligence.projectization import CorpusProjectizationInput, materialize_corpus_projectization
from agent.project_model.holdout_benchmark import (
    ProjectHoldoutBenchmarkBuildInput,
    ProjectHoldoutEvaluationInput,
    build_project_holdout_benchmark,
    evaluate_project_holdout,
)


def _make_repo(root: Path) -> Path:
    repo = root / "holdout_repo"
    (repo / "backend" / "src" / "main" / "java" / "demo").mkdir(parents=True)
    (repo / "backend" / "src" / "test" / "java" / "demo").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "README.md").write_text("# Demo\n\nSpring Boot demo.", encoding="utf-8")
    (repo / "docs" / "ARCHITECTURE.md").write_text("backend api", encoding="utf-8")
    (repo / "pom.xml").write_text(
        "<project><dependencies><dependency><artifactId>spring-boot-starter-web</artifactId></dependency></dependencies></project>",
        encoding="utf-8",
    )
    (repo / "backend" / "src" / "main" / "java" / "demo" / "DemoApplication.java").write_text(
        "@SpringBootApplication\n@RestController\nclass DemoApplication {}",
        encoding="utf-8",
    )
    (repo / "backend" / "src" / "test" / "java" / "demo" / "DemoApplicationTest.java").write_text(
        "class DemoApplicationTest {}",
        encoding="utf-8",
    )
    return repo


def _projectize(tmp_path: Path) -> Path:
    repo = _make_repo(tmp_path)
    crawl = crawl_frontend_backend_repos(
        CrawlProfileInput(
            query="spring boot",
            output_dir=tmp_path / "crawl",
            local_repos=(repo,),
            repo_limit=1,
            min_stars=0,
            quality_threshold=0.0,
        )
    )
    projectized = materialize_corpus_projectization(
        CorpusProjectizationInput(crawl_output_dir=Path(crawl.output_dir), output_dir=tmp_path / "projectized")
    )
    return Path(projectized.output_dir)


def _perfect_predictions(benchmark_path: Path) -> list[dict]:
    benchmark = json.loads(benchmark_path.read_text(encoding="utf-8"))
    rows = []
    for case in benchmark["cases"]:
        if case["task_type"] == "evidence_retrieval":
            rows.append(
                {
                    "case_id": case["case_id"],
                    "retrieved_evidence_ids": [case["positive_evidence_id"]],
                }
            )
        else:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "answer": case["expected_output"],
                    "citations": [row["path"] for row in case["expected_citations"]],
                    "tokens": 12,
                }
            )
    return rows


def test_build_project_holdout_benchmark_consumes_holdout_only(tmp_path: Path) -> None:
    projectized_dir = _projectize(tmp_path)
    result = build_project_holdout_benchmark(
        ProjectHoldoutBenchmarkBuildInput(projectization_dir=projectized_dir, output_dir=tmp_path / "benchmark")
    )

    assert result.manifest["schema"] == "project_holdout_benchmark_manifest.v1"
    assert result.counts["cases"] >= 1
    assert result.counts["evidence_retrieval"] >= 1
    benchmark = json.loads(Path(result.files["benchmark"]).read_text(encoding="utf-8"))
    assert benchmark["split_policy"] == "benchmark_holdout_only"


def test_evaluate_project_holdout_emits_feedback_ready_metrics_and_deltas(tmp_path: Path) -> None:
    projectized_dir = _projectize(tmp_path)
    benchmark = build_project_holdout_benchmark(
        ProjectHoldoutBenchmarkBuildInput(projectization_dir=projectized_dir, output_dir=tmp_path / "benchmark")
    )
    benchmark_path = Path(benchmark.files["benchmark"])
    predictions_path = tmp_path / "predictions.json"
    predictions_path.write_text(json.dumps({"predictions": _perfect_predictions(benchmark_path)}), encoding="utf-8")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "reports": [
                    {"metrics": [{"name": "recall_at_5", "value": 0.0}, {"name": "mrr", "value": 0.0}]},
                    {
                        "metrics": [
                            {"name": "citation_precision", "value": 0.0},
                            {"name": "answer_f1", "value": 0.0},
                            {"name": "tokens_per_correct_answer", "value": 0.0},
                        ]
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    report = evaluate_project_holdout(
        ProjectHoldoutEvaluationInput(
            benchmark_path=benchmark_path,
            predictions_path=predictions_path,
            output_dir=tmp_path / "eval",
            baseline_report_path=baseline_path,
        )
    )

    assert report["schema"] == "project_holdout_evaluation_report.v1"
    assert report["feedback_metrics"]["recall_at_5"] == 1.0
    assert report["feedback_metrics"]["citation_precision"] == 1.0
    assert report["feedback_deltas"]["recall_at_5_delta"] == 1.0
    assert report["feedback_deltas"]["citation_precision_delta"] == 1.0
    assert Path(report["files"]["evaluation_report"]).exists()


def test_project_holdout_actions_are_available(tmp_path: Path) -> None:
    projectized_dir = _projectize(tmp_path)
    benchmark = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "project_holdout_benchmark_build",
            "args": {"projectization_dir": str(projectized_dir), "output_dir": "./benchmark"},
        },
    )
    benchmark_path = Path(benchmark["files"]["benchmark"])
    predictions_path = tmp_path / "predictions.json"
    predictions_path.write_text(json.dumps({"predictions": _perfect_predictions(benchmark_path)}), encoding="utf-8")
    evaluation = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "project_holdout_evaluate",
            "args": {
                "benchmark_path": str(benchmark_path),
                "predictions_path": str(predictions_path),
                "output_dir": "./eval",
            },
        },
    )

    assert benchmark["ok"] is True
    assert evaluation["ok"] is True
    assert evaluation["report"]["feedback_metrics"]["recall_at_5"] == 1.0
