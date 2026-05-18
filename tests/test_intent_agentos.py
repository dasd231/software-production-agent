from __future__ import annotations

import json
from pathlib import Path

from agent.core.executor import run_action
from agent.evidence.ledger import build_evidence_ledger
from agent.intent.compiler import compile_intent
from agent.resources.registry import discover_resources
from agent.solution_library.publish import publish_solution_from_run
from agent.workflows.dry_run import dry_run_workflow


def test_intent_compile_builds_asset_workflow(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    out = compile_intent("爬取 GitHub 常规前后端项目，训练微调，并沉淀为本地方案资产", ws, roots=(tmp_path,))
    chains = [node["chain"] for node in out["workflow"]["nodes"]]

    assert out["schema"] == "intent_compilation.v1"
    assert out["validation"]["ok"] is True
    assert chains == ["context", "github_crawler", "research", "training", "evidence_ledger"]
    assert out["dry_run"]["approval_required"] is True
    assert "training" in out["intent_tags"]
    assert any(item["type"] == "chain" for item in out["resource_suggestions"])


def test_workflow_dry_run_reports_gates_and_outputs(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    spec = {
        "schema": "workflow.v1",
        "version": "asset.v1",
        "nodes": [
            {"id": "research", "chain": "research"},
            {"id": "publish", "chain": "solution_publish"},
            {"id": "ledger", "chain": "evidence_ledger"},
        ],
        "edges": [["research", "publish"], ["publish", "ledger"]],
    }

    out = dry_run_workflow(spec, ws)

    assert out["schema"] == "workflow_dry_run.v1"
    assert out["ok"] is True
    assert out["execution_order"] == ["research", "publish", "ledger"]
    assert out["nodes"][1]["expected_outputs"] == ["solution_manifest.json", "docs/SOLUTION_BACKUP.md", "run_manifest.json"]
    assert "evidence_capture" in out["preflight_gates"]


def test_evidence_ledger_collects_manifests_reports_and_events(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "run_manifest.json").write_text(
        json.dumps({"kind": "research", "manifest_id": "m1", "evaluation": {"overall_score": 8.2}}),
        encoding="utf-8",
    )
    (ws / "solution_manifest.json").write_text(
        json.dumps({"template": "demo", "stack": "Spring + Vue", "training_eligible": True, "quality_score": 8.0}),
        encoding="utf-8",
    )
    (ws / "evaluation_report.json").write_text(
        json.dumps({"stage": "crawler", "overall_score": 7.5, "grade": "B"}),
        encoding="utf-8",
    )
    (ws / "governance_report.json").write_text(
        json.dumps({"ok": True, "risk_level": "low", "issues": []}),
        encoding="utf-8",
    )
    (ws / ".agent_events.jsonl").write_text('{"event":"start"}\n{"event":"finish"}\n', encoding="utf-8")

    out = build_evidence_ledger(ws, write_path=ws / "evidence_ledger.json")
    registry = discover_resources(ws, roots=(tmp_path,))

    assert out["schema"] == "evidence_ledger.v1"
    assert out["summary"]["by_type"]["run_manifest"] == 1
    assert out["summary"]["by_type"]["governance_report"] == 1
    assert out["summary"]["by_type"]["agent_events"] == 1
    assert (ws / "evidence_ledger.json").exists()
    assert registry["summary"]["by_type"]["evidence_ledger"] >= 1


def test_solution_publish_infers_stack_and_writes_asset(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / "docs").mkdir(parents=True)
    (ws / "backend").mkdir()
    (ws / "frontend").mkdir()
    (ws / "README.md").write_text("人员管理系统，包含登录权限、审批流、增删改查。", encoding="utf-8")
    (ws / "backend" / "pom.xml").write_text("<project></project>", encoding="utf-8")
    (ws / "frontend" / "package.json").write_text('{"dependencies":{"vue":"latest"}}', encoding="utf-8")

    out = publish_solution_from_run(ws, output_dir=tmp_path / "solutions", title="people-admin")
    manifest_path = Path(out["files"]["solution_manifest"])

    assert out["ok"] is True
    assert manifest_path.exists()
    assert Path(out["files"]["solution_backup"]).exists()
    assert Path(out["files"]["run_manifest"]).exists()
    assert out["manifest"]["schema_version"] == "solution_manifest.v2"
    assert out["manifest"]["stack"] == "Spring Boot + Vue"
    assert out["manifest"]["acceptance_status"] == "accepted"
    assert out["manifest"]["accepted_by"] == "operator"
    assert Path(out["files"]["acceptance_feedback"]).exists()
    assert "auth" in out["manifest"]["retrieval_tags"]
    assert "workflow" in out["manifest"]["retrieval_tags"]


def test_new_agentos_actions_dispatch(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "README.md").write_text("demo", encoding="utf-8")

    compiled = run_action(ws, {"type": "action", "action": "intent_compile", "args": {"goal": "构建登录权限系统并沉淀方案"}})
    assert compiled["ok"] is True
    assert compiled["compilation"]["workflow"]["nodes"][-1]["chain"] == "evidence_ledger"
    assert "user_acceptance_required" in " ".join(compiled["compilation"]["risk_notes"])

    dry = run_action(
        ws,
        {
            "type": "action",
            "action": "workflow_dry_run",
            "args": {"spec": compiled["compilation"]["workflow"]},
        },
    )
    assert dry["ok"] is True
    assert dry["dry_run"]["schema"] == "workflow_dry_run.v1"

    ledger = run_action(
        ws,
        {"type": "action", "action": "evidence_ledger", "args": {"output_path": "evidence_ledger.json"}},
    )
    assert ledger["ok"] is True
    assert (ws / "evidence_ledger.json").exists()

    published = run_action(
        ws,
        {"type": "action", "action": "solution_publish", "args": {"output_dir": "solutions", "title": "demo-solution"}},
    )
    assert published["ok"] is True
    assert Path(published["files"]["solution_manifest"]).exists()
