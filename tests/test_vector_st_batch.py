"""SentenceTransformer 建库走批量 encode 路径。"""

from __future__ import annotations

from agent.learning.schemas import CodeSlice
from agent.learning.vector_store import build_vector_index


def test_build_vector_index_uses_st_batch_encode(monkeypatch) -> None:
    from agent.learning import vector_store as vs

    calls: dict[str, object] = {}

    def fake_encode(texts: list[str], model_name: str, *, batch_size: int = 32) -> list[list[float]]:
        calls["n_texts"] = len(texts)
        calls["batch_size"] = batch_size
        calls["model"] = model_name
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]][: len(texts)]

    monkeypatch.setattr(vs, "encode_texts_sentence_transformer", fake_encode)

    slices = [
        CodeSlice(path="a.py", language="py", start_line=1, end_line=1, text="hello", tokens=()),
        CodeSlice(path="b.py", language="py", start_line=1, end_line=1, text="world", tokens=()),
    ]
    idx = build_vector_index(
        slices,
        use_sentence_transformer=True,
        sentence_transformer_model="dummy-model",
        st_batch_size=16,
    )

    assert calls["n_texts"] == 2
    assert calls["batch_size"] == 16
    assert calls["model"] == "dummy-model"
    assert len(idx.records) == 2
    assert idx.dimensions == 3
