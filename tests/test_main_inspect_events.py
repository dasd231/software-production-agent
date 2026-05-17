import json
from pathlib import Path

from agent.analytics.events_report import summarize_events_file


def test_inspect_events_text(tmp_path: Path) -> None:
    p = tmp_path / ".agent_events.jsonl"
    p.write_text(
        "\n".join(
            [
                json.dumps({"ts": 1.0, "kind": "plan", "schema_version": "1", "plan_summary": {"stage": "coding"}}),
                json.dumps({"ts": 2.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"}),
            ]
        ),
        encoding="utf-8",
    )
    out = summarize_events_file(p, output="text")
    assert "Event Report" in out
    assert "duration_seconds: 1.00" in out
    assert "final_reason: max_iterations" in out


def test_inspect_events_json(tmp_path: Path) -> None:
    p = tmp_path / ".agent_events.jsonl"
    p.write_text(
        json.dumps({"ts": 1.0, "kind": "finish", "schema_version": "1", "result_summary": {"reason": "ok"}}),
        encoding="utf-8",
    )
    out = summarize_events_file(p, output="json")
    data = json.loads(out)
    assert data["final_progress"] == "finished"
    assert data["duration_seconds"] == 0.0
