from __future__ import annotations

from pathlib import Path

from agent.learning.hierarchical_rag import (
    HIERARCHY_META_FILE,
    PARENT_CHUNKS_FILE,
    build_hierarchical_vector_index,
    load_parent_chunks_jsonl,
    save_hierarchy_artifacts,
    small_to_big_search,
)
from agent.learning.rag_qa import answer_question
from agent.learning.schemas import CodeSlice, KnowledgeCard


def _slice(path: str, start: int, text: str, language: str = "python") -> CodeSlice:
    lines = text.splitlines()
    return CodeSlice(
        path=path,
        language=language,
        start_line=start,
        end_line=start + len(lines) - 1,
        text=text,
        tokens=tuple(w.lower() for w in text.replace("_", " ").split()[:20]),
    )


def test_hierarchical_index_marks_child_metadata_and_parent_chunks(tmp_path: Path) -> None:
    slices = [
        _slice("app/services/book_service.py", 1, "class BookService:\n    def list_books(self):\n        return []"),
        _slice("app/services/book_service.py", 4, "    def borrow_book(self, reader_id):\n        # borrowing circulation\n        return reader_id"),
        _slice("README.md", 1, "# Library\nBorrowing and return workflow", "markdown"),
    ]

    index, parents, meta = build_hierarchical_vector_index(
        slices,
        repo_id="demo/library",
        parent_max_lines=4,
        parent_overlap_lines=1,
        dimensions=64,
    )

    assert len(index.records) == len(slices)
    assert parents
    assert meta["schema"] == "hierarchical_rag.v1"
    child = next(r for r in index.records if r.record_id.startswith("app/services/book_service.py"))
    assert child.metadata["schema"] == "hierarchical_rag.v1"
    assert child.metadata["granularity"] == "child"
    assert child.metadata["repo_id"] == "demo/library"
    assert child.metadata["parent_id"] in parents
    assert child.metadata["content_type"] == "code"
    assert child.metadata["source_kind"] == "source_code"
    assert child.metadata["path_parts"] == ["app", "services", "book_service.py"]
    assert "BookService" in child.metadata["symbol_hints"]

    save_hierarchy_artifacts(tmp_path, parents, meta)
    assert (tmp_path / PARENT_CHUNKS_FILE).exists()
    assert (tmp_path / HIERARCHY_META_FILE).exists()
    loaded = load_parent_chunks_jsonl(tmp_path / PARENT_CHUNKS_FILE)
    assert set(loaded) == set(parents)


def test_small_to_big_search_expands_child_hit_to_parent_context() -> None:
    slices = [
        _slice("library.py", 1, "class LibraryService:\n    def validate_reader(self):\n        return True"),
        _slice("library.py", 4, "    def borrow_book(self):\n        overdue_fine = 0\n        return overdue_fine"),
    ]
    index, parents, _ = build_hierarchical_vector_index(
        slices,
        repo_id="demo/library",
        parent_max_lines=6,
        parent_overlap_lines=0,
        dimensions=64,
    )

    hits = small_to_big_search(index, parents, "overdue_fine borrow", top_k=1, child_fetch_k=2)

    assert len(hits) == 1
    score, record = hits[0]
    assert score > 0
    assert record.metadata["granularity"] == "parent"
    assert record.metadata["small_to_big"] is True
    assert record.metadata["matched_children"]
    assert "validate_reader" in record.text
    assert "overdue_fine" in record.text


def test_answer_question_can_use_parent_context_for_evidence() -> None:
    slices = [
        _slice("library.py", 1, "class LibraryService:\n    def validate_reader(self):\n        return True"),
        _slice("library.py", 4, "    def borrow_book(self):\n        overdue_fine = 0\n        return overdue_fine"),
    ]
    index, parents, _ = build_hierarchical_vector_index(
        slices,
        repo_id="demo/library",
        parent_max_lines=6,
        parent_overlap_lines=0,
        dimensions=64,
    )
    cards = [KnowledgeCard(title="Library", summary="Borrowing workflow", tags=["library"], source_paths=["library.py"], questions=[])]

    out = answer_question("How is overdue_fine handled?", index, cards, top_k=1, parent_chunks=parents)

    assert out["trace"]["small_to_big"]["enabled"] is True
    evidence = out["evidence"][0]
    assert evidence["granularity"] == "parent"
    assert evidence["matched_children"]
    assert "validate_reader" in evidence["preview"]
