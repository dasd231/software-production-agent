import json
from pathlib import Path

from agent.analytics.events_report import compare_events_files


def _write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")


def test_compare_events_text(tmp_path: Path) -> None:
    base = tmp_path / "base.jsonl"
    cur = tmp_path / "cur.jsonl"
    _write_rows(
        base,
        [
            {"ts": 1.0, "kind": "plan", "schema_version": "1", "plan_summary": {"stage": "coding"}},
            {
                "ts": 1.5,
                "kind": "context_enriched",
                "schema_version": "1",
                "summary": {"rag_paths": ["old.py"], "rag_truncated": 0},
            },
            {"ts": 3.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"},
        ],
    )
    _write_rows(
        cur,
        [
            {"ts": 1.0, "kind": "plan", "schema_version": "1", "plan_summary": {"stage": "coding"}},
            {
                "ts": 1.5,
                "kind": "context_enriched",
                "schema_version": "1",
                "summary": {"rag_paths": ["app.py"], "rag_truncated": 1},
            },
            {"ts": 4.0, "kind": "finish", "schema_version": "1", "result_summary": {"reason": "ok"}},
        ],
    )
    out = compare_events_files(cur, base, output="text")
    assert "Event Comparison Report" in out
    assert "final_progress: stopped:max_iterations -> finished" in out
    assert "duration_seconds_delta: +1.00" in out
    assert "stage_context_delta:" in out
    assert "rag_path_delta:" in out
    assert "app.py: +1" in out
    assert "old.py: -1" in out
    assert "rag_truncated_delta: +1" in out
    assert "worsened_reasons:" in out
    assert "rag_path_down:old.py" in out
    assert "rag_truncated_up" in out


def test_compare_events_json(tmp_path: Path) -> None:
    base = tmp_path / "base.jsonl"
    cur = tmp_path / "cur.jsonl"
    _write_rows(
        base,
        [
            {"ts": 1.0, "kind": "plan", "schema_version": "1", "plan_summary": {"stage": "coding"}},
            {"ts": 2.0, "kind": "stopped", "schema_version": "1", "reason": "investigate_required"},
        ],
    )
    _write_rows(
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
                "summary": {"rag_paths": ["app.py", "server.py"], "rag_truncated": 3},
            },
            {"ts": 2.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"},
        ],
    )
    out = compare_events_files(cur, base, output="json")
    data = json.loads(out)
    assert data["severity_baseline"] == "high"
    assert data["severity_current"] == "medium"
    assert data["severity_trend"] == "improved"
    assert data["duration_seconds_current"] == 1.0
    assert data["duration_seconds_baseline"] == 1.0
    assert data["duration_seconds_delta"] == 0.0
    assert data["stage_context_delta"]["coding"]["context_hits_delta"] == 1
    assert data["rag_path_delta"]["app.py"] == 1
    assert data["rag_path_delta"]["server.py"] == 1
    assert data["rag_truncated_delta"] == 3
    assert data["worsened_reasons"] == ["rag_truncated_up"]


def test_compare_events_markdown(tmp_path: Path) -> None:
    base = tmp_path / "base.jsonl"
    cur = tmp_path / "cur.jsonl"
    _write_rows(base, [{"ts": 1.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"}])
    _write_rows(cur, [{"ts": 1.0, "kind": "finish", "schema_version": "1", "result_summary": {"reason": "ok"}}])
    out = compare_events_files(cur, base, output="markdown")
    assert out.startswith("# Event Comparison Report")
    assert "Duration seconds delta" in out
    assert "## Event Delta by Kind" in out
    assert "## Stage Context Delta" in out
    assert "## RAG Context Delta" in out
    assert "## Worsened Reasons" in out
