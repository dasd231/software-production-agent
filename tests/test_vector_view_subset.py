from agent.learning.schemas import VectorRecord
from agent.learning.vector_store import VectorIndex


def test_view_subset_preserves_embedding_flags() -> None:
    r1 = VectorRecord("1", "a", {}, [1.0, 0.0])
    r2 = VectorRecord("2", "b", {}, [0.0, 1.0])
    base = VectorIndex([r1, r2], dimensions=2, use_faiss=True, use_faiss_hnsw=True)
    sub = base.view_subset([r1])
    assert len(sub.records) == 1
    assert sub.use_faiss is True
    assert sub.use_faiss_hnsw is True
