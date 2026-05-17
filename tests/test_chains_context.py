from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from agent.chains.context import ContextChainInput, build_context_query, run_context_chain
from agent.config import AppConfig


def test_context_chain_returns_structure_and_summary(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("from flask import Flask\n", encoding="utf-8")
    cfg = replace(
        AppConfig.from_env(),
        enable_skill_hints=False,
        enable_rag_hints=True,
        enable_mcp_capabilities=False,
        rag_hints_top_k=1,
    )

    result = run_context_chain(
        ContextChainInput(
            structure={},
            workspace=ws,
            goal="build flask api",
            plan={"stage": "coding", "tasks": [], "meta": {}},
            state={"progress": ""},
            config=cfg,
        )
    )

    assert result.structure["rag_hints"][0]["path"] == "app.py"
    assert result.summary["rag_hints"] == 1
    assert result.summary["rag_sources"] == {"local_workspace": 1}


def test_build_context_query_uses_recent_errors() -> None:
    query = build_context_query(
        "",
        {"tasks": []},
        {
            "errors": [
                {"message": "old"},
                {
                    "message": "NameError: missing_symbol is not defined",
                    "stderr": "Traceback\nNameError: missing_symbol is not defined",
                },
            ]
        },
    )

    assert "missing_symbol" in query
    assert "Traceback" in query

