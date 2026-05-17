from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from agent.chains.research import ResearchChainInput, run_research_chain, search_solution_library


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _make_solution_run(root: Path) -> Path:
    run = root / "run_demo"
    (run / "docs").mkdir(parents=True)
    (run / "solution_manifest.json").write_text(
        json.dumps(
            {
                "schema": "solution_manifest.v1",
                "template": "spring-vue-management",
                "stack": "Spring Boot + Vue",
                "goal": "员工管理系统 CRUD 审批",
                "retrieval_tags": ["personnel-management", "crud", "approval"],
                "artifact_hints": ["README.md", "docs/API_CONTRACT.md"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run / "docs" / "SOLUTION_BACKUP.md").write_text(
        "Reusable employee management CRUD solution with approval workflow.",
        encoding="utf-8",
    )
    return run


def test_search_solution_library_finds_manifest(tmp_path: Path) -> None:
    _make_solution_run(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()

    hits = search_solution_library("员工管理 CRUD", workspace=ws, solution_dirs=(tmp_path,), top_k=2)

    assert hits
    assert hits[0]["source"] == "solution_library"
    assert hits[0]["run_id"] == "run_demo"
    assert "crud" in hits[0]["retrieval_tags"]


def test_research_chain_combines_solution_rag_and_web(tmp_path: Path) -> None:
    _make_solution_run(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "app.py").write_text("employee approval workflow\n", encoding="utf-8")
    payload = {
        "Heading": "Spring",
        "AbstractURL": "https://example.test/spring",
        "AbstractText": "Spring Boot docs",
    }

    out = run_research_chain(
        ResearchChainInput(
            query="employee approval workflow",
            workspace=ws,
            solution_dirs=(tmp_path,),
            top_k=2,
            use_web=True,
        ),
        web_opener=lambda *_args, **_kwargs: _FakeResponse(payload),
    )

    assert out.solution_hits
    assert out.rag_hints
    assert out.web_results
    assert "[S1]" in out.answer
    assert "[R1]" in out.answer
    assert "[W1]" in out.answer
    assert out.trace["web_enabled"] is True
    assert out.evaluation["stage"] == "research.synthesis"
    assert out.trace["evaluation_score"] == out.evaluation["overall_score"]
    assert out.trace["evidence_policy"]["decision"] == "web_supplemental"
    assert out.manifest["kind"] == "research_synthesize"


def test_research_chain_llm_falls_back_without_key(tmp_path: Path) -> None:
    _make_solution_run(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()

    with patch("agent.chains.research.create_openai_compatible_client", side_effect=RuntimeError("no key")):
        out = run_research_chain(
            ResearchChainInput(
                query="员工管理 CRUD",
                workspace=ws,
                solution_dirs=(tmp_path,),
                top_k=1,
                use_llm=True,
            )
        )

    assert out.trace["llm_ok"] is False
    assert "可复用方案库命中" in out.answer
    assert out.evaluation["metrics"]["llm_synthesis"]["status"] == "failed"
