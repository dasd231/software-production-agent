"""Tests for lightweight RAG evaluation helpers."""

from __future__ import annotations

from agent.learning.rag_eval import aggregate_answer_metrics, citation_tag_coverage, evidence_path_hit_rate


def test_evidence_path_hit_rate() -> None:
    ev = [{"path": "a/b.py"}, {"path": "other.ts"}]
    assert evidence_path_hit_rate(ev, {"a/b.py"}) == 0.5


def test_citation_tag_coverage() -> None:
    out = citation_tag_coverage("See [E1] and [e2] for details.", 3)
    assert out["coverage"] == 2 / 3
    assert 1 in out["tags_found"] and 2 in out["tags_found"]
    assert 3 in out["tags_missing"]


def test_aggregate_answer_metrics() -> None:
    payload = {
        "answer": "Ref [E1].",
        "confidence": 0.7,
        "evidence": [{"path": "x.py"}],
        "trace": {"mode": "dense"},
    }
    agg = aggregate_answer_metrics(payload, gold_paths={"x.py"})
    assert agg["path_hit_rate"] == 1.0
    assert agg["n_evidence"] == 1
    assert "citation" in agg
