"""FAISS-backed VectorIndex matches linear cosine on small fixtures."""

from __future__ import annotations

import pytest

pytest.importorskip("faiss")

from agent.learning.schemas import VectorRecord
from agent.learning.vector_store import VectorIndex


def test_faiss_search_matches_brute_force_order() -> None:
    def nv(*xs: float) -> list[float]:
        s = sum(x * x for x in xs) ** 0.5
        return [x / s for x in xs]

    q = nv(1, 0, 0, 0, 0, 0, 0, 0)
    r0 = VectorRecord("0", "t0", {}, nv(0.99, 0.1, 0, 0, 0, 0, 0, 0))
    r1 = VectorRecord("1", "t1", {}, nv(0, 1, 0, 0, 0, 0, 0, 0))
    r2 = VectorRecord("2", "t2", {}, nv(0.5, 0.5, 0, 0, 0, 0, 0, 0))
    idx_f = VectorIndex([r0, r1, r2], dimensions=8, use_faiss=True)
    idx_l = VectorIndex([r0, r1, r2], dimensions=8, use_faiss=False)

    qv = q
    faiss_out = idx_f._search_faiss(qv, 2)
    linear_out = idx_l._search_linear(qv, 2)
    assert [r.record_id for _, r in faiss_out] == [r.record_id for _, r in linear_out]
    assert [round(s, 5) for s, _ in faiss_out] == [round(s, 5) for s, _ in linear_out]


def test_hnsw_falls_back_to_flat_when_below_min_vectors() -> None:
    def nv(*xs: float) -> list[float]:
        s = sum(x * x for x in xs) ** 0.5
        return [x / s for x in xs]

    q = nv(1, 0, 0, 0, 0, 0, 0, 0)
    recs = [VectorRecord(str(i), "t", {}, nv(float(i), 1.0, 0, 0, 0, 0, 0, 0)) for i in range(3)]
    idx_h = VectorIndex(recs, dimensions=8, use_faiss=True, use_faiss_hnsw=True, faiss_hnsw_min_vectors=256)
    idx_f = VectorIndex(recs, dimensions=8, use_faiss=True, use_faiss_hnsw=False)
    qv = q
    assert [r.record_id for _, r in idx_h._search_faiss(qv, 2)] == [r.record_id for _, r in idx_f._search_faiss(qv, 2)]
