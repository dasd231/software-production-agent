"""Tests for learning RAG QA (fusion, confidence, generative fallback)."""

from __future__ import annotations

from unittest.mock import patch

from agent.learning.rag_pipeline import ResearchRAGConfig, lost_in_middle_reorder, reciprocal_rank_fusion
from agent.learning.rag_qa import answer_question
from agent.learning.schemas import KnowledgeCard, VectorRecord
from agent.learning.vector_store import VectorIndex, vectorize_text


def _card(title: str = "T", summary: str = "S") -> KnowledgeCard:
    return KnowledgeCard(title=title, summary=summary, tags=[], source_paths=[], questions=[])


def test_answer_question_returns_confidence_and_evidence() -> None:
    dims = 64
    q = "flask"
    qv = vectorize_text(q, dimensions=dims)
    r1 = VectorRecord("a", "hello flask world", {"path": "app.py", "start_line": 1, "end_line": 3}, qv)
    r2 = VectorRecord("b", "django unrelated", {"path": "other.py", "start_line": 1, "end_line": 2}, vectorize_text("django", dimensions=dims))
    idx = VectorIndex([r1, r2], dimensions=dims)
    cards = [_card("Install", "pip install flask")]
    out = answer_question(q, idx, cards, top_k=2)
    assert out.get("question") == q
    assert isinstance(out["evidence"], list) and len(out["evidence"]) >= 1
    assert 0.0 <= float(out["confidence"]) <= 1.0
    assert out["retrieval"]["use_bm25"] is False
    assert "trace" in out


def test_research_path_enables_trace_without_breaking_baseline_scores() -> None:
    dims = 48
    q = "alpha beta"
    qv = vectorize_text(q, dimensions=dims)
    r1 = VectorRecord("a", "alpha beta gamma", {"path": "a.py", "start_line": 1, "end_line": 2}, qv)
    r2 = VectorRecord("b", "other", {"path": "b.py", "start_line": 1, "end_line": 2}, vectorize_text("z", dimensions=dims))
    idx = VectorIndex([r1, r2], dimensions=dims)
    cfg = ResearchRAGConfig(
        multi_query=False,
        retrieve_multiplier=4,
        cross_encoder_model=None,
        lost_in_middle=False,
    )
    out = answer_question(q, idx, [_card()], top_k=2, use_bm25=True, research=cfg)
    assert out["trace"].get("mode")
    assert out["retrieval"]["research"]["multi_query"] is False


def test_research_trace_includes_retrieve_ms() -> None:
    dims = 32
    q = "alpha"
    qv = vectorize_text(q, dimensions=dims)
    r1 = VectorRecord("a", "alpha one", {"path": "src/a.py", "language": "py", "start_line": 1, "end_line": 1}, qv)
    r2 = VectorRecord("b", "beta two", {"path": "vendor/b.py", "language": "py", "start_line": 1, "end_line": 1}, vectorize_text("beta", dimensions=dims))
    idx = VectorIndex([r1, r2], dimensions=dims)
    cfg = ResearchRAGConfig(
        multi_query=False,
        retrieve_multiplier=4,
        cross_encoder_model=None,
        lost_in_middle=False,
        path_prefixes=("src",),
    )
    out = answer_question(q, idx, [_card()], top_k=2, use_bm25=True, research=cfg)
    assert "retrieve_ms" in out["trace"]
    paths = {str(e.get("path")) for e in out["evidence"]}
    assert paths <= {"src/a.py"}


def test_answer_question_includes_metrics_when_gold_paths() -> None:
    dims = 32
    q = "one"
    va = VectorRecord("x", "fact one", {"path": "app.py", "start_line": 1, "end_line": 1}, vectorize_text(q, dimensions=dims))
    idx = VectorIndex([va], dimensions=dims)
    out = answer_question(q, idx, [_card()], gold_paths={"app.py"})
    assert "metrics" in out
    assert out["metrics"].get("path_hit_rate") == 1.0


def test_lost_in_middle_reorders_longer_lists() -> None:
    recs = [
        VectorRecord(str(i), f"t{i}", {}, [1.0, 0.0, 0.0]) for i in range(4)
    ]
    out = lost_in_middle_reorder(recs)
    assert [r.record_id for r in out] == ["0", "2", "3", "1"]


def test_rrf_orders_union_when_vector_and_bm25_disagree() -> None:
    va = VectorRecord("id-a", "alpha beta", {}, [1.0, 0.0, 0.0])
    vb = VectorRecord("id-b", "gamma delta", {}, [0.0, 1.0, 0.0])
    vc = VectorRecord("id-c", "beta raretoken", {}, [0.0, 0.0, 1.0])
    fused = reciprocal_rank_fusion([[va, vb], [vc, va]], top_k=2)
    ids = [r.record_id for _, r in fused]
    assert len(ids) == 2
    assert "id-a" in ids


def test_generative_falls_back_when_client_raises() -> None:
    dims = 32
    q = "one"
    va = VectorRecord("x", "fact one", {"path": "f.py", "start_line": 1, "end_line": 1}, vectorize_text(q, dimensions=dims))
    idx = VectorIndex([va], dimensions=dims)
    cards = [_card()]
    with patch("agent.learning.rag_qa.create_openai_compatible_client", side_effect=RuntimeError("no key")):
        out = answer_question(q, idx, cards, use_generative=True, llm_provider="openai")
    assert "相关代码证据" in str(out["answer"])
