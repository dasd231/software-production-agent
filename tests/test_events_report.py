import json
from pathlib import Path

from agent.analytics.events_report import (
    append_history_row,
    build_gate_result,
    build_history_row,
    build_events_summary,
    build_report_metadata,
    compare_summaries,
    file_sha256,
    inspection_failure_reasons,
    load_events,
    render_summary_text,
    save_report_with_metadata,
    should_fail_inspection,
    summarize_events_file,
)


def test_events_report_build_and_render(tmp_path: Path) -> None:
    p = tmp_path / ".agent_events.jsonl"
    rows = [
        {
            "ts": 1.0,
            "kind": "plan",
            "schema_version": "1",
            "run_id": "run-a",
            "plan_summary": {
                "stage": "coding",
                "context_task_hints": ["先参考 rag_hints 的相关片段，再决定最小改动范围"],
                "context_hint_count": 1,
            },
        },
        {
            "ts": 1.5,
            "kind": "context_enriched",
            "schema_version": "1",
            "run_id": "run-a",
            "summary": {"rag_paths": ["app.py", "tests/test_app.py"], "rag_truncated": 1},
        },
        {
            "ts": 1.6,
            "kind": "context_enriched",
            "schema_version": "1",
            "run_id": "run-a",
            "summary": {"rag_paths": ["app.py"], "rag_truncated": 0},
        },
        {"ts": 2.0, "kind": "plan", "schema_version": "1", "run_id": "run-b", "plan_summary": {"stage": "review", "priority_guidance": ["a"]}},
        {
            "ts": 2.2,
            "kind": "decision_policy",
            "schema_version": "1",
            "run_id": "run-b",
            "decision": {
                "strategy": "verify",
                "selected_action": "production_check",
                "selector": {"selector_version": "ucb1-v1", "selected_bandit_score": 0.93},
                "candidate_actions": [{"action": "production_check", "bandit_bonus": 0.04}],
            },
        },
        {
            "ts": 2.4,
            "kind": "decision_trace",
            "schema_version": "1",
            "run_id": "run-b",
            "trace": {"aligned_with_policy": True},
        },
        {
            "ts": 2.6,
            "kind": "reward_signal",
            "schema_version": "1",
            "run_id": "run-b",
            "reward": {"action": "production_check", "total": 1.2, "ok": True, "progress_after": "production_check_ok"},
        },
        {"ts": 3.0, "kind": "finish", "schema_version": "1", "run_id": "run-b", "result_summary": {"reason": "ok"}},
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    loaded = load_events(p)
    summary = build_events_summary(loaded)
    assert summary["total_events"] == 8
    assert summary["first_ts"] == 1.0
    assert summary["last_ts"] == 3.0
    assert summary["duration_seconds"] == 2.0
    assert summary["run_count"] == 2
    assert summary["run_ids"] == ["run-a", "run-b"]
    assert summary["decision_strategy_counts"] == {"verify": 1}
    assert summary["policy_selected_counts"] == {"production_check": 1}
    assert summary["bandit_selector_counts"] == {"ucb1-v1": 1}
    assert summary["avg_selected_bandit_score"] == 0.93
    assert summary["avg_top_bandit_bonus"] == 0.04
    assert summary["decision_alignment"] == {"aligned": 1, "diverged": 0}
    assert summary["reward_count"] == 1
    assert summary["avg_reward"] == 1.2
    assert summary["last_rewards"][0]["action"] == "production_check"
    assert summary["priority_guidance_plan_hits"] == 1
    assert summary["context_hint_plan_hits"] == 1
    assert summary["context_hint_task_count"] == 1
    assert summary["rag_paths_top"] == [{"path": "app.py", "count": 2}, {"path": "tests/test_app.py", "count": 1}]
    assert summary["rag_truncated_total"] == 1
    assert summary["stage_context_usage"]["coding"]["plans"] == 1
    assert summary["stage_context_usage"]["coding"]["context_hits"] == 1
    assert summary["stage_context_usage"]["review"]["plans"] == 1
    assert summary["stage_context_usage"]["review"]["context_hits"] == 0
    assert summary["final_progress"] == "finished"
    assert "diagnostic" in summary
    assert "failure_actions_top" in summary
    assert "last_failures" in summary
    txt = render_summary_text(summary)
    assert "Event Report" in txt
    assert "duration_seconds: 2.00" in txt
    assert "run_count: 2" in txt
    assert "run_ids: run-a, run-b" in txt
    assert "decision_strategy_counts:" in txt
    assert "bandit_selector_counts:" in txt
    assert "avg_selected_bandit_score: 0.930" in txt
    assert "avg_reward: 1.200" in txt
    assert "context_hint_plan_hits: 1" in txt
    assert "rag_paths_top:" in txt
    assert "app.py: 2" in txt
    assert "rag_truncated_total: 1" in txt
    assert "stage_path: coding -> review" in txt
    assert "stage_context_usage:" in txt
    assert "coding: plans=1, context_hits=1" in txt


def test_events_report_json_output(tmp_path: Path) -> None:
    p = tmp_path / ".agent_events.jsonl"
    p.write_text(json.dumps({"ts": 1.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"}), encoding="utf-8")
    out = summarize_events_file(p, output="json")
    data = json.loads(out)
    assert data["final_reason"] == "max_iterations"
    assert data["duration_seconds"] == 0.0


def test_events_report_markdown_output(tmp_path: Path) -> None:
    p = tmp_path / ".agent_events.jsonl"
    rows = [
        {"ts": 1.0, "kind": "plan", "schema_version": "1", "run_id": "run-md", "plan_summary": {"stage": "coding"}},
        {
            "ts": 1.5,
            "kind": "context_enriched",
            "schema_version": "1",
            "run_id": "run-md",
            "summary": {"rag_paths": ["bad.py"], "rag_truncated": 2},
        },
        {
            "ts": 2.0,
            "kind": "execute",
            "schema_version": "1",
            "run_id": "run-md",
            "result_summary": {"action": "run_command", "ok": False, "returncode": 1, "stderr_head": "SyntaxError: bad"},
        },
        {
            "ts": 2.5,
            "kind": "reward_signal",
            "schema_version": "1",
            "run_id": "run-md",
            "reward": {"action": "run_command", "total": -1.1, "ok": False, "progress_after": "run_failed"},
        },
        {"ts": 3.0, "kind": "stopped", "schema_version": "1", "run_id": "run-md", "reason": "max_iterations"},
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    out = summarize_events_file(p, output="markdown")
    assert out.startswith("# Event Report")
    assert "## Run IDs" in out
    assert "`run-md`" in out
    assert "## RAG Context" in out
    assert "`bad.py` x 1" in out
    assert "Truncated snippets: 2" in out
    assert "## Top Failure Actions" in out
    assert "## Stage Context Usage" in out
    assert "## Rewards" in out


def test_events_report_diagnostic_investigate_required(tmp_path: Path) -> None:
    p = tmp_path / ".agent_events.jsonl"
    rows = [
        {"ts": 1.0, "kind": "stopped", "schema_version": "1", "reason": "investigate_required", "result_summary": {"reason": "investigate_required"}}
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    data = json.loads(summarize_events_file(p, output="json"))
    assert data["diagnostic"]["severity"] == "high"
    assert data["diagnostic"]["root_cause"] == "repeated_command_failures"


def test_events_report_diagnostic_ship_gate_block(tmp_path: Path) -> None:
    p = tmp_path / ".agent_events.jsonl"
    rows = [
        {"ts": 1.0, "kind": "ship_gate_blocked", "schema_version": "1", "result_summary": {"action": "ship_gate_blocked"}},
        {"ts": 2.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"},
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    data = json.loads(summarize_events_file(p, output="json"))
    assert data["diagnostic"]["root_cause"] == "ship_gate_quality_block"


def test_events_report_diagnostic_import_error_from_stderr(tmp_path: Path) -> None:
    p = tmp_path / ".agent_events.jsonl"
    rows = [
        {
            "ts": 1.0,
            "kind": "execute",
            "schema_version": "1",
            "result_summary": {"action": "run_command", "ok": False, "stderr_head": "ModuleNotFoundError: No module named xyz"},
        },
        {"ts": 2.0, "kind": "stopped", "schema_version": "1", "reason": "max_iterations"},
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows), encoding="utf-8")
    data = json.loads(summarize_events_file(p, output="json"))
    assert data["diagnostic"]["root_cause"] == "dependency_or_import_path"


def test_should_fail_inspection_critical_and_worsened() -> None:
    s_critical = {"diagnostic": {"severity": "critical"}}
    assert should_fail_inspection(mode="critical", summary=s_critical) is True
    assert should_fail_inspection(mode="critical", summary={"diagnostic": {"severity": "high"}}) is False

    base = {"diagnostic": {"severity": "medium"}, "total_events": 1, "by_kind": {}, "stage_path": [], "final_progress": "", "final_reason": ""}
    cur = {"diagnostic": {"severity": "high"}, "total_events": 1, "by_kind": {}, "stage_path": [], "final_progress": "", "final_reason": ""}
    comp = compare_summaries(cur, base)
    assert should_fail_inspection(mode="worsened", comparison=comp) is True
    assert comp["worsened_reasons"] == ["severity_worsened"]

    context_comp = {
        "severity_trend": "unchanged",
        "stage_context_delta": {"coding": {"plans_delta": 0, "context_hits_delta": -1}},
        "rag_path_delta": {},
        "rag_truncated_delta": 0,
    }
    assert should_fail_inspection(mode="worsened", comparison=context_comp) is True

    rag_comp = {
        "severity_trend": "unchanged",
        "stage_context_delta": {},
        "rag_path_delta": {"app.py": -1},
        "rag_truncated_delta": 0,
    }
    assert should_fail_inspection(mode="worsened", comparison=rag_comp) is True

    trunc_comp = {
        "severity_trend": "unchanged",
        "stage_context_delta": {},
        "rag_path_delta": {},
        "rag_truncated_delta": 1,
    }
    assert should_fail_inspection(mode="worsened", comparison=trunc_comp) is True
    assert inspection_failure_reasons(mode="worsened", failed=True, comparison=trunc_comp) == ["rag_truncated_up"]
    assert inspection_failure_reasons(mode="worsened", failed=False, comparison=trunc_comp) == []


def test_should_fail_inspection_no_context_usage() -> None:
    s_fail = {
        "by_kind": {"plan": 2},
        "context_hint_plan_hits": 0,
        "diagnostic": {"severity": "info"},
    }
    assert should_fail_inspection(mode="no_context_usage", summary=s_fail) is True

    s_pass = {
        "by_kind": {"plan": 2},
        "context_hint_plan_hits": 1,
        "diagnostic": {"severity": "info"},
    }
    assert should_fail_inspection(mode="no_context_usage", summary=s_pass) is False


def test_should_fail_inspection_stage_context_missing() -> None:
    s_fail = {
        "stage_context_usage": {
            "coding": {"plans": 2, "context_hits": 0},
            "fixing": {"plans": 1, "context_hits": 1},
        }
    }
    assert should_fail_inspection(mode="stage_context_missing", summary=s_fail) is True
    assert inspection_failure_reasons(
        mode="stage_context_missing",
        failed=True,
        summary=s_fail,
        required_stages=["coding", "fixing"],
    ) == ["stage_context_missing:coding"]

    s_pass = {
        "stage_context_usage": {
            "coding": {"plans": 2, "context_hits": 1},
            "fixing": {"plans": 1, "context_hits": 1},
        }
    }
    assert should_fail_inspection(mode="stage_context_missing", summary=s_pass) is False


def test_report_metadata_and_sidecar(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"ts": 1.0, "kind": "finish", "schema_version": "1", "result_summary": {"reason": "ok"}}), encoding="utf-8")
    meta = build_report_metadata(
        current_path=events,
        baseline_path=None,
        inspect_format="text",
        fail_mode="",
    )
    assert meta["schema_version"] == "1"
    assert isinstance(meta.get("analysis_id"), str) and len(meta["analysis_id"]) == 16
    assert meta["current_events_sha256"] == file_sha256(events)

    save_path = tmp_path / "report.txt"
    sidecar = save_report_with_metadata(save_path, "hello", meta)
    assert save_path.exists()
    assert sidecar.exists()


def test_build_gate_result() -> None:
    summary = {
        "final_reason": "max_iterations",
        "final_progress": "stopped:max_iterations",
        "duration_seconds": 12.34,
        "diagnostic": {"severity": "medium"},
    }
    gate = build_gate_result(
        analysis_id="abc123",
        fail_mode="critical",
        failed=False,
        summary=summary,
        comparison=None,
    )
    assert gate["analysis_id"] == "abc123"
    assert gate["status"] == "pass"
    assert gate["severity"] == "medium"
    assert gate["duration_seconds"] == 12.34
    assert gate["failure_reasons"] == []


def test_build_gate_result_includes_comparison_context_deltas() -> None:
    gate = build_gate_result(
        analysis_id="abc123",
        fail_mode="worsened",
        failed=True,
        summary=None,
        comparison={
            "severity_current": "high",
            "severity_trend": "worsened",
            "final_reason_current": "investigate_required",
            "final_progress_current": "stopped:investigate_required",
            "duration_seconds_current": 9.5,
            "duration_seconds_delta": 2.25,
            "stage_context_delta": {"fixing": {"plans_delta": 1, "context_hits_delta": -1}},
            "rag_path_delta": {"app.py": 2},
            "rag_truncated_delta": 1,
            "worsened_reasons": ["severity_worsened", "rag_truncated_up"],
        },
    )

    assert gate["status"] == "fail"
    assert gate["severity"] == "high"
    assert gate["duration_seconds"] == 9.5
    assert gate["duration_seconds_delta"] == 2.25
    assert gate["failure_reasons"] == ["severity_worsened", "rag_truncated_up"]
    assert gate["severity_trend"] == "worsened"
    assert gate["worsened_reasons"] == ["severity_worsened", "rag_truncated_up"]
    assert gate["stage_context_delta"]["fixing"]["context_hits_delta"] == -1
    assert gate["rag_path_delta"] == {"app.py": 2}
    assert gate["rag_truncated_delta"] == 1


def test_history_row_and_append(tmp_path: Path) -> None:
    gate = {
        "analysis_id": "id-1",
        "status": "pass",
        "severity": "info",
        "reason": "ok",
        "final_progress": "finished",
        "duration_seconds": 3.21,
        "failure_reasons": [],
        "gate_mode": "critical",
    }
    row = build_history_row(
        gate_result=gate,
        label="pr-123",
        baseline_path=None,
        report_path=tmp_path / "report.txt",
    )
    assert row["analysis_id"] == "id-1"
    assert row["label"] == "pr-123"
    assert row["duration_seconds"] == 3.21
    assert row["failure_reasons"] == []
    hist = tmp_path / "history.jsonl"
    append_history_row(hist, row)
    lines = hist.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
