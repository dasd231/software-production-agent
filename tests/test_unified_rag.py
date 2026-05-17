from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from agent.config import AppConfig
from agent.context.enrichment import enrich_structure, enrichment_summary
from agent.learning.schemas import KnowledgeCard, VectorRecord
from agent.learning.vector_store import VectorIndex, vectorize_text
from agent.rag.unified import retrieve_unified_snippets


def _make_learning_run(root: Path, *, text: str = "stripe webhook handler") -> Path:
    out = root / "learning"
    out.mkdir()
    record = VectorRecord(
        "billing.py:1-3",
        text,
        {"path": "billing.py", "language": "py", "start_line": 1, "end_line": 3},
        vectorize_text(text),
    )
    VectorIndex([record]).save_jsonl(out / "vector_index.jsonl")
    cards = [
        KnowledgeCard(
            title="Billing",
            summary="Stripe webhook billing implementation.",
            tags=["billing"],
            source_paths=["billing.py"],
            questions=["How does webhook billing work?"],
        ).to_dict()
    ]
    (out / "knowledge_cards.json").write_text(json.dumps(cards), encoding="utf-8")
    return out


def test_unified_rag_fuses_workspace_and_learning_hints(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("def payment():\n    return 'local payment'\n", encoding="utf-8")
    learning = _make_learning_run(tmp_path, text="payment webhook billing")

    out = retrieve_unified_snippets(
        ws,
        "payment webhook",
        top_k=1,
        learning_dirs=(str(learning),),
        learning_top_k=1,
    )

    sources = [hint.get("source") for hint in out.hints]
    assert sources[:2] == ["local_workspace", "learning_run"]
    assert out.summary["learning"]["hits"] == 1
    assert out.summary["sources"]["learning_run"] == 1
    assert out.summary["evaluation"]["stage"] == "rag.unified_retrieval"


def test_unified_rag_keeps_local_results_when_learning_store_is_broken(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("from flask import Flask\n", encoding="utf-8")

    out = retrieve_unified_snippets(
        ws,
        "flask",
        top_k=1,
        learning_dirs=(str(tmp_path / "missing"),),
        learning_top_k=1,
    )

    assert out.hints[0]["path"] == "app.py"
    assert out.summary["learning"]["stores"][0]["ok"] is False
    assert "error" in out.summary["learning"]["stores"][0]
    assert "evaluation" in out.summary


def test_context_enrichment_can_inject_learning_rag(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("def payment():\n    return 'local payment'\n", encoding="utf-8")
    learning = _make_learning_run(tmp_path, text="payment webhook billing")
    cfg = replace(
        AppConfig.from_env(),
        enable_skill_hints=False,
        enable_rag_hints=True,
        enable_learning_rag=True,
        learning_rag_dirs=(str(learning),),
        learning_rag_top_k=1,
        enable_mcp_capabilities=False,
        rag_hints_top_k=1,
    )

    out = enrich_structure(
        {},
        workspace=ws,
        goal="payment webhook",
        plan_dict={"stage": "coding", "tasks": [], "meta": {}},
        state_dict={"progress": ""},
        config=cfg,
    )

    assert any(hint.get("source") == "learning_run" for hint in out["rag_hints"])
    assert out["rag_observability"]["learning"]["hits"] == 1
    assert enrichment_summary(out)["rag_sources"]["learning_run"] == 1
