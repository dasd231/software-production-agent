"""Build and score project-level holdout benchmarks from projectized corpus assets."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.evaluation.aggregate import aggregate_metric_reports
from agent.evaluation.schemas import Metric, MetricReport


@dataclass(frozen=True)
class ProjectHoldoutBenchmarkBuildInput:
    projectization_dir: Path
    output_dir: Path


@dataclass(frozen=True)
class ProjectHoldoutBenchmarkBuildResult:
    output_dir: str
    files: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "files": dict(self.files),
            "counts": dict(self.counts),
            "manifest": dict(self.manifest),
        }


@dataclass(frozen=True)
class ProjectHoldoutEvaluationInput:
    benchmark_path: Path
    predictions_path: Path
    output_dir: Path
    baseline_report_path: Path | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", str(text or "").lower())


def _f1(prediction: str, expected: str) -> float:
    pred = _tokenize(prediction)
    gold = _tokenize(expected)
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    pred_counts: dict[str, int] = {}
    gold_counts: dict[str, int] = {}
    for token in pred:
        pred_counts[token] = pred_counts.get(token, 0) + 1
    for token in gold:
        gold_counts[token] = gold_counts.get(token, 0) + 1
    overlap = sum(min(pred_counts.get(token, 0), count) for token, count in gold_counts.items())
    precision = overlap / len(pred)
    recall = overlap / len(gold)
    return (2 * precision * recall / (precision + recall)) if precision and recall else 0.0


def _citation_keys(citations: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        path = str(citation.get("path", "") or "").strip()
        if path:
            keys.add(path)
    return keys


def build_project_holdout_benchmark(
    inp: ProjectHoldoutBenchmarkBuildInput,
) -> ProjectHoldoutBenchmarkBuildResult:
    """Convert projectized holdout task assets into a stable offline benchmark."""

    projectization_dir = inp.projectization_dir.resolve()
    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    projectization = _safe_json(projectization_dir / "corpus_projectization_manifest.json")
    projectization = projectization if isinstance(projectization, dict) else {}
    task_assets = [
        row
        for row in projectization.get("task_assets", [])
        if isinstance(row, dict) and str(row.get("route", "")) == "benchmark_holdout"
    ]
    cases: list[dict[str, Any]] = []
    for asset in task_assets:
        files = asset.get("files") if isinstance(asset.get("files"), dict) else {}
        for pair in _read_jsonl(Path(str(files.get("retrieval_pairs", "") or ""))):
            case_id = str(pair.get("pair_id", "") or "")
            if not case_id:
                continue
            cases.append(
                {
                    "case_id": case_id,
                    "task_type": "evidence_retrieval",
                    "query": str(pair.get("query", "") or ""),
                    "positive_evidence_id": str(pair.get("positive_evidence_id", "") or ""),
                    "positive_path": str(pair.get("positive_path", "") or ""),
                    "repo_id": str(pair.get("repo_id", "") or ""),
                }
            )
        for example in _read_jsonl(Path(str(files.get("training_examples", "") or ""))):
            task_type = str(example.get("task_type", "") or "")
            if task_type == "evidence_retrieval":
                continue
            case_id = str(example.get("example_id", "") or "")
            if not case_id:
                continue
            cases.append(
                {
                    "case_id": case_id,
                    "task_type": task_type,
                    "prompt": str(example.get("instruction", "") or "") + "\n" + str(example.get("input", "") or ""),
                    "expected_output": str(example.get("output", "") or ""),
                    "expected_citations": [
                        row for row in example.get("citations", []) if isinstance(row, dict)
                    ],
                    "repo_id": str((example.get("metadata") or {}).get("repo_id", "") or ""),
                }
            )
    benchmark = {
        "schema": "project_holdout_benchmark.v1",
        "created_at": _now(),
        "source_projectization_manifest": str(projectization_dir / "corpus_projectization_manifest.json"),
        "split_policy": "benchmark_holdout_only",
        "cases": cases,
    }
    benchmark_path = output_dir / "project_holdout_benchmark.json"
    manifest_path = output_dir / "project_holdout_benchmark_manifest.json"
    report_path = output_dir / "report.md"
    _write_json(benchmark_path, benchmark)
    counts: dict[str, int] = {}
    for case in cases:
        key = str(case.get("task_type", "unknown"))
        counts[key] = counts.get(key, 0) + 1
    manifest = {
        "schema": "project_holdout_benchmark_manifest.v1",
        "created_at": _now(),
        "source_projectization_dir": str(projectization_dir),
        "counts": {"cases": len(cases), **counts},
        "files": {"benchmark": str(benchmark_path)},
        "feedback_ready_metrics": ["recall_at_5", "mrr", "citation_precision", "answer_f1", "tokens_per_correct_answer"],
    }
    _write_json(manifest_path, manifest)
    report_path.write_text(
        "\n".join(
            [
                "# Project Holdout Benchmark",
                "",
                f"- Cases: `{len(cases)}`",
                f"- Retrieval cases: `{counts.get('evidence_retrieval', 0)}`",
                f"- Grounded cases: `{len(cases) - counts.get('evidence_retrieval', 0)}`",
                "",
                "## Guardrail",
                "",
                "- Only `benchmark_holdout` task assets are imported.",
                "- This benchmark is meant for evaluation and feedback, not training_prepare input.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return ProjectHoldoutBenchmarkBuildResult(
        output_dir=str(output_dir),
        files={
            "benchmark": str(benchmark_path),
            "manifest": str(manifest_path),
            "report": str(report_path),
        },
        counts=dict(manifest["counts"]),
        manifest=manifest,
    )


def _prediction_map(path: Path) -> dict[str, dict[str, Any]]:
    payload = _safe_json(path)
    rows = payload.get("predictions") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        rows = _read_jsonl(path)
    return {
        str(row.get("case_id", "")): row
        for row in rows
        if isinstance(row, dict) and str(row.get("case_id", "")).strip()
    }


def _retrieval_report(cases: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]) -> MetricReport:
    hits = 0
    reciprocal_ranks = 0.0
    for case in cases:
        positive = str(case.get("positive_evidence_id", "") or "")
        retrieved = [
            str(item)
            for item in (predictions.get(str(case.get("case_id", "")), {}).get("retrieved_evidence_ids", []) or [])
            if str(item)
        ][:5]
        if positive and positive in retrieved:
            hits += 1
            reciprocal_ranks += 1.0 / (retrieved.index(positive) + 1)
    total = len(cases)
    recall_at_5 = hits / total if total else 0.0
    mrr = reciprocal_ranks / total if total else 0.0
    return MetricReport(
        stage="project_holdout.retrieval",
        metrics=(
            Metric("recall_at_5", round(recall_at_5, 4), recall_at_5 * 10.0, weight=1.5),
            Metric("mrr", round(mrr, 4), mrr * 10.0, weight=1.2),
        ),
        summary={"cases": total},
    )


def _grounded_report(cases: list[dict[str, Any]], predictions: dict[str, dict[str, Any]]) -> MetricReport:
    answer_scores: list[float] = []
    citation_precisions: list[float] = []
    correct_token_costs: list[int] = []
    for case in cases:
        prediction = predictions.get(str(case.get("case_id", "")), {})
        answer = str(prediction.get("answer", "") or "")
        expected = str(case.get("expected_output", "") or "")
        answer_score = _f1(answer, expected)
        answer_scores.append(answer_score)
        expected_citations = _citation_keys([row for row in case.get("expected_citations", []) if isinstance(row, dict)])
        predicted_citations = {
            str(item)
            for item in prediction.get("citations", [])
            if str(item).strip()
        }
        if predicted_citations:
            citation_precisions.append(len(predicted_citations & expected_citations) / len(predicted_citations))
        else:
            citation_precisions.append(0.0 if expected_citations else 1.0)
        if answer_score >= 0.8:
            token_cost = prediction.get("tokens")
            if isinstance(token_cost, int) and token_cost > 0:
                correct_token_costs.append(token_cost)
            else:
                correct_token_costs.append(max(len(_tokenize(answer)), 1))
    total = len(cases)
    answer_f1 = sum(answer_scores) / total if total else 0.0
    citation_precision = sum(citation_precisions) / total if total else 0.0
    tokens_per_correct = sum(correct_token_costs) / len(correct_token_costs) if correct_token_costs else 0.0
    token_efficiency_score = min(10.0, 100.0 / tokens_per_correct) if tokens_per_correct else 0.0
    return MetricReport(
        stage="project_holdout.grounded_answer",
        metrics=(
            Metric("answer_f1", round(answer_f1, 4), answer_f1 * 10.0, weight=1.4),
            Metric("citation_precision", round(citation_precision, 4), citation_precision * 10.0, weight=1.4),
            Metric("tokens_per_correct_answer", round(tokens_per_correct, 4), token_efficiency_score, weight=0.8),
        ),
        summary={"cases": total, "correct_answers": len(correct_token_costs)},
    )


def _metric_value(report: dict[str, Any], metric_name: str) -> float:
    for stage in report.get("reports", []):
        if not isinstance(stage, dict):
            continue
        metrics = stage.get("metrics")
        if isinstance(metrics, dict):
            metric = metrics.get(metric_name)
            if isinstance(metric, dict):
                return float(metric.get("value", 0.0) or 0.0)
        elif isinstance(metrics, list):
            for metric in metrics:
                if isinstance(metric, dict) and str(metric.get("name", "")) == metric_name:
                    return float(metric.get("value", 0.0) or 0.0)
    return 0.0


def evaluate_project_holdout(inp: ProjectHoldoutEvaluationInput) -> dict[str, Any]:
    """Score offline predictions and expose feedback-ready deltas."""

    benchmark = _safe_json(inp.benchmark_path.resolve())
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    cases = [row for row in benchmark.get("cases", []) if isinstance(row, dict)]
    predictions = _prediction_map(inp.predictions_path.resolve())
    retrieval_cases = [row for row in cases if str(row.get("task_type", "")) == "evidence_retrieval"]
    grounded_cases = [row for row in cases if str(row.get("task_type", "")) != "evidence_retrieval"]
    reports = [
        _retrieval_report(retrieval_cases, predictions).to_dict(),
        _grounded_report(grounded_cases, predictions).to_dict(),
    ]
    aggregate = aggregate_metric_reports(reports, stage="project_holdout.summary").to_dict()
    report = {
        "schema": "project_holdout_evaluation_report.v1",
        "created_at": _now(),
        "benchmark_path": str(inp.benchmark_path.resolve()),
        "predictions_path": str(inp.predictions_path.resolve()),
        "summary": aggregate,
        "reports": reports,
        "feedback_metrics": {
            "recall_at_5": _metric_value({"reports": reports}, "recall_at_5"),
            "mrr": _metric_value({"reports": reports}, "mrr"),
            "citation_precision": _metric_value({"reports": reports}, "citation_precision"),
            "answer_f1": _metric_value({"reports": reports}, "answer_f1"),
            "tokens_per_correct_answer": _metric_value({"reports": reports}, "tokens_per_correct_answer"),
        },
    }
    if inp.baseline_report_path:
        baseline = _safe_json(inp.baseline_report_path.resolve())
        baseline = baseline if isinstance(baseline, dict) else {}
        report["feedback_deltas"] = {
            f"{name}_delta": round(float(value) - _metric_value(baseline, name), 4)
            for name, value in report["feedback_metrics"].items()
        }
    else:
        report["feedback_deltas"] = {}
    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "project_holdout_evaluation_report.json"
    _write_json(report_path, report)
    report["files"] = {"evaluation_report": str(report_path)}
    return report
