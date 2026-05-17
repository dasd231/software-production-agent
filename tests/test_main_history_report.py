import json
import sys
from pathlib import Path

from agent import main as main_mod


def test_main_history_report_json(tmp_path: Path, monkeypatch) -> None:
    hist = tmp_path / "history.jsonl"
    hist.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "analysis_id": "a1",
                "status": "pass",
                "severity": "info",
                "reason": "ok",
                "label": "nightly-main",
                "duration_seconds": 1.25,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-history-report",
            str(hist),
            "--inspect-format",
            "json",
        ],
    )
    rc = main_mod.main()
    assert rc == 0


def test_main_history_report_fail_and_output_json(tmp_path: Path, monkeypatch) -> None:
    hist = tmp_path / "history.jsonl"
    out = tmp_path / "history-gate.json"
    hist.write_text(
        "\n".join(
            [
                json.dumps({"schema_version": "1", "analysis_id": "a1", "status": "pass", "severity": "info", "reason": "ok", "label": "main", "duration_seconds": 1.0}),
                json.dumps({"schema_version": "1", "analysis_id": "a2", "status": "fail", "severity": "high", "reason": "investigate_required", "label": "main", "duration_seconds": 3.0}),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-history-report",
            str(hist),
            "--inspect-history-fail-on",
            "passrate",
            "--history-min-pass-rate",
            "90",
            "--inspect-output-json",
            str(out),
        ],
    )
    rc = main_mod.main()
    assert rc == 4
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["scope"] == "history"
    assert obj["status"] == "fail"
    assert obj["failure_reasons"] == ["passrate_below:90.00"]
    assert obj["failure_reason_counts"] == {"final_reason:investigate_required": 1}
    assert [x["analysis_id"] for x in obj["latest_runs"]] == ["a1", "a2"]
    assert obj["current_status"] == "fail"
    assert obj["current_status_streak"] == 1
    assert obj["current_failure_streak"] == 1
    assert obj["avg_duration_seconds"] == 2.0


def test_main_history_report_with_label_filter_passes(tmp_path: Path, monkeypatch) -> None:
    hist = tmp_path / "history.jsonl"
    out = tmp_path / "history-gate-pass.json"
    hist.write_text(
        "\n".join(
            [
                json.dumps({"schema_version": "1", "analysis_id": "a1", "status": "fail", "severity": "high", "reason": "investigate_required", "label": "nightly"}),
                json.dumps({"schema_version": "1", "analysis_id": "a2", "status": "pass", "severity": "info", "reason": "ok", "label": "main"}),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-history-report",
            str(hist),
            "--history-label",
            "main",
            "--inspect-history-fail-on",
            "passrate",
            "--history-min-pass-rate",
            "90",
            "--inspect-output-json",
            str(out),
        ],
    )
    rc = main_mod.main()
    assert rc == 0
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["status"] == "pass"


def test_main_history_report_duration_gate_fails(tmp_path: Path, monkeypatch) -> None:
    hist = tmp_path / "history.jsonl"
    out = tmp_path / "duration-gate.json"
    hist.write_text(
        "\n".join(
            [
                json.dumps({"schema_version": "1", "analysis_id": "a1", "status": "pass", "severity": "info", "reason": "ok", "label": "main", "duration_seconds": 4.0}),
                json.dumps({"schema_version": "1", "analysis_id": "a2", "status": "pass", "severity": "info", "reason": "ok", "label": "main", "duration_seconds": 8.0}),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-history-report",
            str(hist),
            "--inspect-history-fail-on",
            "duration",
            "--history-max-avg-duration",
            "5",
            "--inspect-output-json",
            str(out),
        ],
    )
    rc = main_mod.main()
    assert rc == 4
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["status"] == "fail"
    assert obj["gate_mode"] == "duration"
    assert obj["failure_reasons"] == ["avg_duration_above:5.00"]
    assert obj["max_avg_duration"] == 5.0
    assert obj["avg_duration_seconds"] == 6.0


def test_main_history_report_max_duration_gate_fails(tmp_path: Path, monkeypatch) -> None:
    hist = tmp_path / "history.jsonl"
    out = tmp_path / "max-duration-gate.json"
    hist.write_text(
        "\n".join(
            [
                json.dumps({"schema_version": "1", "analysis_id": "a1", "status": "pass", "severity": "info", "reason": "ok", "label": "main", "duration_seconds": 2.0}),
                json.dumps({"schema_version": "1", "analysis_id": "a2", "status": "pass", "severity": "info", "reason": "ok", "label": "main", "duration_seconds": 12.0}),
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-history-report",
            str(hist),
            "--inspect-history-fail-on",
            "max_duration",
            "--history-max-duration",
            "10",
            "--inspect-output-json",
            str(out),
        ],
    )
    rc = main_mod.main()
    assert rc == 4
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["status"] == "fail"
    assert obj["gate_mode"] == "max_duration"
    assert obj["failure_reasons"] == ["max_duration_above:10.00"]
    assert obj["max_duration"] == 10.0
    assert obj["max_duration_seconds"] == 12.0
    assert obj["slowest_runs"][0]["analysis_id"] == "a2"
    assert obj["slowest_runs"][0]["duration_seconds"] == 12.0
