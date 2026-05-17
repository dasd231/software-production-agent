import json
from pathlib import Path

from agent.analytics.events_report import (
    build_history_gate_result,
    build_history_summary,
    filter_history_rows,
    history_failure_reasons,
    should_fail_history,
    summarize_history_file,
)


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")


def test_history_summary_and_text(tmp_path: Path) -> None:
    p = tmp_path / "hist.jsonl"
    rows = [
        {"schema_version": "1", "analysis_id": "a1", "status": "pass", "severity": "info", "reason": "ok", "label": "main", "duration_seconds": 1.0},
        {
            "schema_version": "1",
            "analysis_id": "a2",
            "status": "fail",
            "severity": "medium",
            "reason": "max_iterations",
            "label": "main",
            "duration_seconds": 2.5,
            "failure_reasons": ["passrate_below:90.00"],
        },
        {
            "schema_version": "1",
            "analysis_id": "a3",
            "status": "fail",
            "severity": "high",
            "reason": "investigate_required",
            "label": "nightly",
            "duration_seconds": 3.5,
            "failure_reasons": ["passrate_below:90.00", "severity_worsened"],
        },
    ]
    _write(p, rows)
    out = summarize_history_file(p, output="text")
    assert "History Trend Report" in out
    assert "pass_rate" in out
    assert "avg_duration_seconds: 2.33" in out
    assert "current_status: fail" in out
    assert "current_failure_streak: 2" in out
    assert "failure_reason_counts:" in out
    assert "passrate_below:90.00: 2" in out
    assert "latest_runs:" in out
    assert "slowest_runs:" in out
    assert "analysis_id=a3" in out
    summary = build_history_summary(rows)
    assert summary["total_runs"] == 3
    assert summary["pass_count"] == 1
    assert summary["avg_duration_seconds"] == 2.33
    assert summary["max_duration_seconds"] == 3.5
    assert summary["current_status"] == "fail"
    assert summary["current_status_streak"] == 2
    assert summary["current_failure_streak"] == 2
    assert summary["failure_reason_counts"] == {
        "passrate_below:90.00": 2,
        "severity_worsened": 1,
    }
    assert [x["analysis_id"] for x in summary["latest_runs"]] == ["a1", "a2", "a3"]
    assert summary["latest_runs"][-1]["failure_reasons"] == ["passrate_below:90.00", "severity_worsened"]
    assert summary["slowest_runs"][0]["analysis_id"] == "a3"
    assert summary["slowest_runs"][0]["duration_seconds"] == 3.5
    assert summary["slowest_runs"][1]["analysis_id"] == "a2"
    assert summary["regressions"]


def test_history_summary_markdown_and_json(tmp_path: Path) -> None:
    p = tmp_path / "hist.jsonl"
    _write(
        p,
        [
            {"schema_version": "1", "analysis_id": "a1", "status": "pass", "severity": "info", "reason": "ok", "label": "pr-1"},
        ],
    )
    md = summarize_history_file(p, output="markdown")
    assert md.startswith("# History Trend Report")
    assert "## Failure Reason Counts" in md
    assert "## Latest Runs" in md
    assert "## Slowest Runs" in md
    js = summarize_history_file(p, output="json")
    obj = json.loads(js)
    assert obj["total_runs"] == 1
    assert obj["current_status"] == "pass"
    assert obj["current_status_streak"] == 1
    assert obj["current_failure_streak"] == 0
    assert obj["latest_runs"][0]["analysis_id"] == "a1"
    assert obj["slowest_runs"] == []


def test_history_filter_label_and_last(tmp_path: Path) -> None:
    rows = [
        {"label": "main", "status": "pass", "severity": "info"},
        {"label": "nightly", "status": "fail", "severity": "high"},
        {"label": "main", "status": "fail", "severity": "medium"},
    ]
    f1 = filter_history_rows(rows, label="main", last_n=0)
    assert len(f1) == 2
    f2 = filter_history_rows(rows, label="", last_n=2)
    assert len(f2) == 2
    f3 = filter_history_rows(rows, label="main", last_n=1)
    assert len(f3) == 1


def test_history_fail_modes_and_gate_result() -> None:
    summary = {
        "total_runs": 3,
        "pass_rate": 66.67,
        "avg_duration_seconds": 2.5,
        "max_duration_seconds": 7.0,
        "current_status": "fail",
        "current_status_streak": 2,
        "current_failure_streak": 2,
        "failure_reason_counts": {"passrate_below:80.00": 1},
        "latest_runs": [{"analysis_id": "latest-1", "status": "fail"}],
        "slowest_runs": [{"analysis_id": "slow-1", "duration_seconds": 7.0}],
        "regressions": [{"index": 2}],
    }
    assert should_fail_history(mode="regression", summary=summary, min_pass_rate=80.0) is True
    assert should_fail_history(mode="passrate", summary=summary, min_pass_rate=70.0) is True
    assert should_fail_history(mode="duration", summary=summary, min_pass_rate=80.0, max_avg_duration=2.0) is True
    assert should_fail_history(mode="duration", summary=summary, min_pass_rate=80.0, max_avg_duration=3.0) is False
    assert should_fail_history(mode="duration", summary=summary, min_pass_rate=80.0, max_avg_duration="bad") is False
    assert should_fail_history(mode="max_duration", summary=summary, min_pass_rate=80.0, max_duration=6.0) is True
    assert should_fail_history(mode="max_duration", summary=summary, min_pass_rate=80.0, max_duration=8.0) is False
    assert should_fail_history(mode="max_duration", summary=summary, min_pass_rate=80.0, max_duration="bad") is False
    assert history_failure_reasons(
        mode="regression",
        failed=True,
        summary=summary,
        min_pass_rate=80.0,
    ) == ["history_regressions:1"]
    assert history_failure_reasons(
        mode="duration",
        failed=True,
        summary=summary,
        min_pass_rate=80.0,
        max_avg_duration=2.0,
    ) == ["avg_duration_above:2.00"]
    assert history_failure_reasons(
        mode="duration",
        failed=False,
        summary=summary,
        min_pass_rate=80.0,
        max_avg_duration=2.0,
    ) == []
    gate = build_history_gate_result(
        history_path=Path("hist.jsonl"),
        mode="passrate",
        min_pass_rate=80.0,
        max_avg_duration=9.0,
        max_duration=11.0,
        failed=True,
        summary=summary,
    )
    assert gate["scope"] == "history"
    assert gate["status"] == "fail"
    assert gate["failure_reasons"] == ["passrate_below:80.00"]
    assert gate["max_avg_duration"] == 9.0
    assert gate["max_duration"] == 11.0
    assert gate["avg_duration_seconds"] == 2.5
    assert gate["max_duration_seconds"] == 7.0
    assert gate["current_status"] == "fail"
    assert gate["current_status_streak"] == 2
    assert gate["current_failure_streak"] == 2
    assert gate["failure_reason_counts"] == {"passrate_below:80.00": 1}
    assert gate["latest_runs"] == [{"analysis_id": "latest-1", "status": "fail"}]
    assert gate["slowest_runs"] == [{"analysis_id": "slow-1", "duration_seconds": 7.0}]
