from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.context.enrichment import enrich_structure, enrichment_summary


def test_enrich_structure_respects_toggles(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("from flask import Flask\n", encoding="utf-8")
    cfg = replace(
        AppConfig.from_env(),
        enable_skill_hints=False,
        enable_rag_hints=True,
        enable_mcp_capabilities=False,
        rag_hints_top_k=2,
    )
    out = enrich_structure(
        {},
        workspace=ws,
        goal="build flask api",
        plan_dict={"stage": "coding", "tasks": [], "meta": {}},
        state_dict={"progress": ""},
        config=cfg,
    )
    assert "skill_hints" not in out
    assert isinstance(out.get("rag_hints"), list)
    assert "mcp_capabilities" not in out
    s = enrichment_summary(out)
    assert s["skill_hints"] == 0
    assert s["rag_paths"] == ["app.py"]
    assert s["rag_truncated"] == 0


def test_enrich_structure_rag_hints_with_empty_goal_use_entries(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("print('entry')\n", encoding="utf-8")
    cfg = replace(
        AppConfig.from_env(),
        enable_skill_hints=False,
        enable_rag_hints=True,
        enable_mcp_capabilities=False,
        rag_hints_top_k=1,
    )
    out = enrich_structure(
        {},
        workspace=ws,
        goal="",
        plan_dict={"stage": "coding", "tasks": [], "meta": {}},
        state_dict={"progress": ""},
        config=cfg,
    )
    assert out["rag_hints"][0]["path"] == "app.py"


def test_enrich_structure_rag_hints_include_recent_errors(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("def handler():\n    return missing_symbol\n", encoding="utf-8")
    cfg = replace(
        AppConfig.from_env(),
        enable_skill_hints=False,
        enable_rag_hints=True,
        enable_mcp_capabilities=False,
        rag_hints_top_k=1,
    )
    out = enrich_structure(
        {},
        workspace=ws,
        goal="fix runtime bug",
        plan_dict={"stage": "fixing", "tasks": ["根据 stderr 修复代码"], "meta": {}},
        state_dict={
            "progress": "run_failed",
            "errors": [
                {
                    "message": "NameError: missing_symbol is not defined",
                    "stderr": "Traceback\nNameError: missing_symbol is not defined",
                }
            ],
        },
        config=cfg,
    )
    assert out["rag_hints"][0]["path"] == "app.py"
    assert "missing_symbol" in out["rag_hints"][0]["overlap_tokens"]


def test_enrichment_summary_includes_rag_observability() -> None:
    summary = enrichment_summary(
        {
            "skill_hints": ["debugging"],
            "rag_hints": [
                {"path": "app.py", "truncated": True},
                {"path": "app.py", "truncated": False},
                {"path": "tests/test_app.py", "truncated": True},
                "legacy hint",
            ],
            "mcp_capabilities": [{"tool": "workspace.search"}],
        }
    )

    assert summary["skill_hints"] == 1
    assert summary["rag_hints"] == 4
    assert summary["mcp_capabilities"] == 1
    assert summary["rag_paths"] == ["app.py", "tests/test_app.py"]
    assert summary["rag_truncated"] == 2
