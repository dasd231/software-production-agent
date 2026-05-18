from __future__ import annotations

import json
from pathlib import Path

from agent.solution_library.semantic_index import (
    SolutionEmbeddingConfig,
    ensure_solution_semantic_index,
)


def _make_solution(root: Path, name: str, text: str) -> Path:
    run = root / name
    (run / "docs").mkdir(parents=True)
    manifest = run / "solution_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "solution_manifest.v1",
                "source_type": "product_run",
                "acceptance_status": "accepted",
                "template": name,
                "goal": text,
                "retrieval_tags": ["crud"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (run / "docs" / "SOLUTION_BACKUP.md").write_text(text, encoding="utf-8")
    return manifest


def test_solution_semantic_index_builds_and_reuses(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    manifests = [
        _make_solution(tmp_path, "employee", "employee approval workflow"),
        _make_solution(tmp_path, "billing", "billing invoice reconciliation"),
    ]

    index, first = ensure_solution_semantic_index(
        ws,
        manifests,
        config=SolutionEmbeddingConfig(backend="hash", dimensions=32),
    )
    second_index, second = ensure_solution_semantic_index(
        ws,
        manifests,
        config=SolutionEmbeddingConfig(backend="hash", dimensions=32),
    )

    assert first["status"] == "built"
    assert first["record_count"] == 2
    assert (ws / ".agent_cache" / "solution_semantic" / "vector_index.jsonl").exists()
    assert second["status"] == "reused"
    assert len(index.records) == len(second_index.records) == 2
