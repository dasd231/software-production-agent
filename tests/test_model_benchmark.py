from __future__ import annotations

from agent.evaluation.model_benchmark import BenchmarkCase, compare_evaluations, evaluate_predictions, score_prediction


def test_action_case_uses_protocol_validation() -> None:
    case = BenchmarkCase(
        case_id="a",
        category="action_protocol",
        prompt="",
        expected_action="workspace_index",
        expected_args={},
    )
    row = score_prediction(case, '{"type":"action","action":"workspace_index","args":{}}')

    assert row["action_valid"] is True
    assert row["action_match"] is True
    assert row["expected_args_ok"] is True


def test_text_case_tracks_terms_citations_and_forbidden_terms() -> None:
    case = BenchmarkCase(
        case_id="g",
        category="grounded_answer",
        prompt="",
        required_terms=("Spring Boot", "Vue"),
        required_citations=("[E1]",),
        forbidden_terms=("React",),
    )
    row = score_prediction(case, "答案：技术栈是 Spring Boot + Vue。[E1]")

    assert row["term_recall"] == 1.0
    assert row["citation_recall"] == 1.0
    assert row["safe"] is True
    assert row["has_final_answer"] is True


def test_evaluation_and_comparison_reports_have_stable_shape() -> None:
    cases = [
        BenchmarkCase("a", "action_protocol", "", expected_action="workspace_index", expected_args={}),
        BenchmarkCase("g", "grounded_answer", "", required_terms=("Spring Boot",), required_citations=("[E1]",)),
        BenchmarkCase("s", "solution_reuse", "", required_terms=("README",)),
    ]
    predictions = {
        "a": '{"type":"action","action":"workspace_index","args":{}}',
        "g": "Spring Boot [E1]",
        "s": "README",
    }
    base = evaluate_predictions(cases, predictions, label="base")
    tuned = evaluate_predictions(
        cases,
        predictions,
        label="tuned",
        benchmark_id="demo_benchmark.json",
        subject={"model_version": "backup-demo"},
    )
    comparison = compare_evaluations(base, tuned)

    assert base["schema"] == "model_evaluation_report.v1"
    assert base["summary"]["stage"] == "model_eval.summary"
    assert tuned["benchmark_id"] == "demo_benchmark.json"
    assert tuned["subject"]["model_version"] == "backup-demo"
    assert comparison["schema"] == "model_evaluation_comparison.v1"
    assert comparison["stages"][0]["delta"] == 0.0
