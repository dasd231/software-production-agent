import json
import sys
from pathlib import Path

from agent import main as main_mod


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")


def test_main_inspect_save_and_fail_on_critical(tmp_path: Path, monkeypatch) -> None:
    events = tmp_path / "events.jsonl"
    out = tmp_path / "report.txt"
    meta = tmp_path / "report.txt.meta.json"
    gate = tmp_path / "gate.json"
    _write(
        events,
        [
            {
                "ts": 1.0,
                "kind": "stopped",
                "schema_version": "1",
                "reason": "safety_gate",
                "result_summary": {"reason": "safety_gate"},
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(events),
            "--inspect-save",
            str(out),
            "--inspect-output-json",
            str(gate),
            "--inspect-fail-on",
            "critical",
        ],
    )
    rc = main_mod.main()
    assert rc == 3
    assert out.exists()
    assert meta.exists()
    assert gate.exists()
    gate_obj = json.loads(gate.read_text(encoding="utf-8"))
    assert gate_obj["status"] == "fail"
    assert gate_obj["failure_reasons"] == ["severity_critical"]
    assert "Event Report" in out.read_text(encoding="utf-8")


def test_main_inspect_fail_on_worsened_with_baseline(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "base.jsonl"
    cur = tmp_path / "cur.jsonl"
    _write(base, [{"ts": 1.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"}])
    _write(cur, [{"ts": 1.0, "kind": "stopped", "schema_version": "1", "reason": "investigate_required"}])
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(cur),
            "--inspect-baseline",
            str(base),
            "--inspect-fail-on",
            "worsened",
            "--inspect-format",
            "json",
        ],
    )
    rc = main_mod.main()
    assert rc == 3


def test_main_inspect_output_json_with_baseline_includes_context_deltas(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "base.jsonl"
    cur = tmp_path / "cur.jsonl"
    gate = tmp_path / "gate.json"
    _write(
        base,
        [
            {
                "ts": 1.0,
                "kind": "context_enriched",
                "schema_version": "1",
                "summary": {"rag_paths": ["old.py"], "rag_truncated": 0},
            },
            {"ts": 2.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"},
        ],
    )
    _write(
        cur,
        [
            {
                "ts": 1.0,
                "kind": "plan",
                "schema_version": "1",
                "plan_summary": {"stage": "coding", "context_task_hints": ["先参考 rag_hints"]},
            },
            {
                "ts": 1.5,
                "kind": "context_enriched",
                "schema_version": "1",
                "summary": {"rag_paths": ["app.py"], "rag_truncated": 2},
            },
            {"ts": 2.0, "kind": "stopped", "schema_version": "1", "reason": "investigate_required"},
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(cur),
            "--inspect-baseline",
            str(base),
            "--inspect-output-json",
            str(gate),
            "--inspect-fail-on",
            "worsened",
        ],
    )
    rc = main_mod.main()
    assert rc == 3
    obj = json.loads(gate.read_text(encoding="utf-8"))
    assert obj["severity_trend"] == "worsened"
    assert obj["worsened_reasons"] == ["severity_worsened", "rag_path_down:old.py", "rag_truncated_up"]
    assert obj["failure_reasons"] == ["severity_worsened", "rag_path_down:old.py", "rag_truncated_up"]
    assert obj["stage_context_delta"]["coding"]["context_hits_delta"] == 1
    assert obj["rag_path_delta"] == {"app.py": 1, "old.py": -1}
    assert obj["rag_truncated_delta"] == 2


def test_main_inspect_fail_on_worsened_context_regression(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "base.jsonl"
    cur = tmp_path / "cur.jsonl"
    _write(
        base,
        [
            {
                "ts": 1.0,
                "kind": "plan",
                "schema_version": "1",
                "plan_summary": {"stage": "coding", "context_task_hints": ["先参考 rag_hints"]},
            },
            {"ts": 2.0, "kind": "finish", "schema_version": "1", "result_summary": {"reason": "ok"}},
        ],
    )
    _write(
        cur,
        [
            {"ts": 1.0, "kind": "plan", "schema_version": "1", "plan_summary": {"stage": "coding"}},
            {"ts": 2.0, "kind": "finish", "schema_version": "1", "result_summary": {"reason": "ok"}},
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(cur),
            "--inspect-baseline",
            str(base),
            "--inspect-fail-on",
            "worsened",
        ],
    )
    rc = main_mod.main()
    assert rc == 3


def test_main_inspect_output_json_pass(tmp_path: Path, monkeypatch) -> None:
    events = tmp_path / "events.jsonl"
    gate = tmp_path / "gate-pass.json"
    _write(
        events,
        [
            {
                "ts": 1.0,
                "kind": "finish",
                "schema_version": "1",
                "result_summary": {"reason": "ok"},
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(events),
            "--inspect-output-json",
            str(gate),
            "--inspect-fail-on",
            "critical",
        ],
    )
    rc = main_mod.main()
    assert rc == 0
    obj = json.loads(gate.read_text(encoding="utf-8"))
    assert obj["status"] == "pass"


def test_main_inspect_appends_history(tmp_path: Path, monkeypatch) -> None:
    events = tmp_path / "events.jsonl"
    history = tmp_path / "history.jsonl"
    _write(
        events,
        [
            {
                "ts": 1.0,
                "kind": "finish",
                "schema_version": "1",
                "result_summary": {"reason": "ok"},
            }
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(events),
            "--inspect-history",
            str(history),
            "--inspect-label",
            "nightly-main",
        ],
    )
    rc = main_mod.main()
    assert rc == 0
    rows = [json.loads(x) for x in history.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(rows) == 1
    assert rows[0]["label"] == "nightly-main"
    assert rows[0]["status"] == "pass"
    assert rows[0]["duration_seconds"] == 0.0


def test_main_inspect_fail_on_no_context_usage(tmp_path: Path, monkeypatch) -> None:
    events = tmp_path / "events.jsonl"
    _write(
        events,
        [
            {
                "ts": 1.0,
                "kind": "plan",
                "schema_version": "1",
                "plan_summary": {"stage": "coding"},
            },
            {"ts": 2.0, "kind": "finish", "schema_version": "1", "result_summary": {"reason": "ok"}},
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(events),
            "--inspect-fail-on",
            "no_context_usage",
        ],
    )
    rc = main_mod.main()
    assert rc == 3


def test_main_inspect_fail_on_stage_context_missing(tmp_path: Path, monkeypatch) -> None:
    events = tmp_path / "events.jsonl"
    _write(
        events,
        [
            {
                "ts": 1.0,
                "kind": "plan",
                "schema_version": "1",
                "plan_summary": {"stage": "coding"},
            },
            {
                "ts": 2.0,
                "kind": "plan",
                "schema_version": "1",
                "plan_summary": {"stage": "fixing", "context_task_hints": ["优先按 skill_hints 执行: debugging"]},
            },
            {"ts": 3.0, "kind": "finish", "schema_version": "1", "result_summary": {"reason": "ok"}},
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(events),
            "--inspect-fail-on",
            "stage_context_missing",
            "--inspect-context-stages",
            "coding,fixing",
        ],
    )
    rc = main_mod.main()
    assert rc == 3


def test_main_inspect_stage_context_missing_outputs_missing_stages(tmp_path: Path, monkeypatch) -> None:
    events = tmp_path / "events.jsonl"
    gate = tmp_path / "gate.json"
    _write(
        events,
        [
            {
                "ts": 1.0,
                "kind": "plan",
                "schema_version": "1",
                "plan_summary": {"stage": "coding"},
            },
            {
                "ts": 2.0,
                "kind": "plan",
                "schema_version": "1",
                "plan_summary": {"stage": "fixing", "context_task_hints": ["优先按 skill_hints 执行: debugging"]},
            },
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "agent.main",
            "--inspect-events",
            str(events),
            "--inspect-fail-on",
            "stage_context_missing",
            "--inspect-context-stages",
            "coding,fixing",
            "--inspect-output-json",
            str(gate),
        ],
    )
    rc = main_mod.main()
    assert rc == 3
    obj = json.loads(gate.read_text(encoding="utf-8"))
    assert "missing_context_stages" in obj
    assert obj["missing_context_stages"] == ["coding"]
    assert obj["failure_reasons"] == ["stage_context_missing:coding"]
