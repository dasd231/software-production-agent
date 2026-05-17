"""Small, thesis-oriented benchmark for backup local-model evaluation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.core.protocol import ProtocolError, parse_and_validate_action_line
from agent.evaluation.aggregate import aggregate_metric_reports
from agent.evaluation.schemas import Metric, MetricReport


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    category: str
    prompt: str
    expected_action: str = ""
    expected_args: dict[str, Any] | None = None
    required_terms: tuple[str, ...] = ()
    required_citations: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    max_new_tokens: int = 160

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BenchmarkCase":
        return cls(
            case_id=str(raw["case_id"]),
            category=str(raw["category"]),
            prompt=str(raw["prompt"]),
            expected_action=str(raw.get("expected_action", "") or ""),
            expected_args=dict(raw.get("expected_args") or {}),
            required_terms=tuple(str(x) for x in raw.get("required_terms", []) if str(x)),
            required_citations=tuple(str(x) for x in raw.get("required_citations", []) if str(x)),
            forbidden_terms=tuple(str(x) for x in raw.get("forbidden_terms", []) if str(x)),
            max_new_tokens=max(int(raw.get("max_new_tokens", 160) or 160), 1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "prompt": self.prompt,
            "expected_action": self.expected_action,
            "expected_args": dict(self.expected_args or {}),
            "required_terms": list(self.required_terms),
            "required_citations": list(self.required_citations),
            "forbidden_terms": list(self.forbidden_terms),
            "max_new_tokens": self.max_new_tokens,
        }


def load_benchmark(path: Path) -> list[BenchmarkCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("benchmark must contain a cases array")
    return [BenchmarkCase.from_dict(row) for row in rows if isinstance(row, dict)]


def _contains_terms(text: str, terms: tuple[str, ...]) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    found = [term for term in terms if term.lower() in lowered]
    missing = [term for term in terms if term.lower() not in lowered]
    return found, missing


def _extract_final_answer(text: str) -> str:
    for marker in ("最终答案：", "答案：", "Final answer:", "Answer:"):
        if marker in text:
            return text.rsplit(marker, 1)[-1].strip()
    return ""


def _score_action_case(case: BenchmarkCase, prediction: str) -> dict[str, Any]:
    parsed: dict[str, Any] | None = None
    error = ""
    try:
        parsed = parse_and_validate_action_line(prediction)
    except ProtocolError as exc:
        error = str(exc)
    expected_args = case.expected_args or {}
    action_valid = parsed is not None
    action_match = bool(parsed and parsed.get("action") == case.expected_action)
    args = parsed.get("args", {}) if parsed else {}
    expected_args_ok = bool(parsed and all(args.get(key) == value for key, value in expected_args.items()))
    return {
        "case_id": case.case_id,
        "category": case.category,
        "prediction": prediction,
        "parsed_action": parsed,
        "action_valid": action_valid,
        "action_match": action_match,
        "expected_args_ok": expected_args_ok,
        "error": error,
        "score": round((int(action_valid) + int(action_match) + int(expected_args_ok)) / 3.0 * 10.0, 2),
    }


def _score_text_case(case: BenchmarkCase, prediction: str) -> dict[str, Any]:
    answer = _extract_final_answer(prediction)
    found_terms, missing_terms = _contains_terms(answer, case.required_terms)
    found_citations, missing_citations = _contains_terms(answer, case.required_citations)
    found_forbidden, _ = _contains_terms(answer, case.forbidden_terms)
    term_recall = len(found_terms) / len(case.required_terms) if case.required_terms else 1.0
    citation_recall = len(found_citations) / len(case.required_citations) if case.required_citations else 1.0
    safe = not found_forbidden
    weighted = term_recall * 0.6 + citation_recall * 0.25 + (1.0 if safe else 0.0) * 0.15
    return {
        "case_id": case.case_id,
        "category": case.category,
        "prediction": prediction,
        "answer": answer,
        "has_final_answer": bool(answer),
        "found_terms": found_terms,
        "missing_terms": missing_terms,
        "found_citations": found_citations,
        "missing_citations": missing_citations,
        "found_forbidden": found_forbidden,
        "term_recall": round(term_recall, 4),
        "citation_recall": round(citation_recall, 4),
        "safe": safe,
        "score": round(weighted * 10.0, 2),
    }


def score_prediction(case: BenchmarkCase, prediction: str) -> dict[str, Any]:
    if case.category == "action_protocol":
        return _score_action_case(case, prediction)
    return _score_text_case(case, prediction)


def _action_report(rows: list[dict[str, Any]]) -> MetricReport:
    total = len(rows)
    valid_rate = sum(1 for row in rows if row.get("action_valid")) / total if total else 0.0
    match_rate = sum(1 for row in rows if row.get("action_match")) / total if total else 0.0
    args_rate = sum(1 for row in rows if row.get("expected_args_ok")) / total if total else 0.0
    return MetricReport(
        stage="model_eval.action_protocol",
        metrics=(
            Metric("valid_action_rate", round(valid_rate, 4), valid_rate * 10.0, weight=1.4),
            Metric("expected_action_rate", round(match_rate, 4), match_rate * 10.0, weight=1.4),
            Metric("expected_args_rate", round(args_rate, 4), args_rate * 10.0, weight=1.2),
        ),
        summary={"cases": total},
    )


def _text_report(rows: list[dict[str, Any]], *, stage: str) -> MetricReport:
    total = len(rows)
    avg_term_recall = sum(float(row.get("term_recall", 0.0)) for row in rows) / total if total else 0.0
    avg_citation_recall = sum(float(row.get("citation_recall", 0.0)) for row in rows) / total if total else 0.0
    safety_rate = sum(1 for row in rows if row.get("safe")) / total if total else 0.0
    avg_case_score = sum(float(row.get("score", 0.0)) for row in rows) / total if total else 0.0
    return MetricReport(
        stage=stage,
        metrics=(
            Metric("required_term_recall", round(avg_term_recall, 4), avg_term_recall * 10.0, weight=1.5),
            Metric("citation_recall", round(avg_citation_recall, 4), avg_citation_recall * 10.0, weight=1.2),
            Metric("forbidden_term_safety", round(safety_rate, 4), safety_rate * 10.0, weight=1.0),
            Metric("average_case_score", round(avg_case_score, 4), avg_case_score, weight=1.0),
            Metric(
                "final_answer_rate",
                round(sum(1 for row in rows if row.get("has_final_answer")) / total, 4) if total else 0.0,
                (sum(1 for row in rows if row.get("has_final_answer")) / total * 10.0) if total else 0.0,
                weight=1.2,
            ),
        ),
        summary={"cases": total},
    )


def evaluate_predictions(
    cases: list[BenchmarkCase],
    predictions: dict[str, str],
    *,
    label: str,
    benchmark_id: str = "",
    subject: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [score_prediction(case, predictions.get(case.case_id, "")) for case in cases]
    by_category: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_category.setdefault(str(row["category"]), []).append(row)

    reports: list[dict[str, Any]] = []
    if by_category.get("action_protocol"):
        reports.append(_action_report(by_category["action_protocol"]).to_dict())
    if by_category.get("grounded_answer"):
        reports.append(_text_report(by_category["grounded_answer"], stage="model_eval.grounded_answer").to_dict())
    if by_category.get("solution_reuse"):
        reports.append(_text_report(by_category["solution_reuse"], stage="model_eval.solution_reuse").to_dict())
    aggregate = aggregate_metric_reports(reports, stage="model_eval.summary").to_dict()
    report = {
        "schema": "model_evaluation_report.v1",
        "label": label,
        "benchmark_id": benchmark_id,
        "summary": aggregate,
        "reports": reports,
        "cases": rows,
    }
    if subject:
        report["subject"] = dict(subject)
    return report


def compare_evaluations(base: dict[str, Any], tuned: dict[str, Any]) -> dict[str, Any]:
    def stage_scores(report: dict[str, Any]) -> dict[str, float]:
        out: dict[str, float] = {}
        summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
        out["summary"] = float(summary.get("overall_score", 0.0) or 0.0)
        for row in report.get("reports", []):
            if isinstance(row, dict):
                out[str(row.get("stage", ""))] = float(row.get("overall_score", 0.0) or 0.0)
        return out

    base_scores = stage_scores(base)
    tuned_scores = stage_scores(tuned)
    stages = sorted(set(base_scores) | set(tuned_scores))
    return {
        "schema": "model_evaluation_comparison.v1",
        "base_label": base.get("label"),
        "tuned_label": tuned.get("label"),
        "stages": [
            {
                "stage": stage,
                "base_score": round(base_scores.get(stage, 0.0), 2),
                "tuned_score": round(tuned_scores.get(stage, 0.0), 2),
                "delta": round(tuned_scores.get(stage, 0.0) - base_scores.get(stage, 0.0), 2),
            }
            for stage in stages
        ],
    }
