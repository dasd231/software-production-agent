"""Local hashing-vector store for RAG.

函数流程图：
    build_vector_index(slices, embedding 后端 …)
      -> hash / OpenAI / SentenceTransformer（**批量 encode**）
      -> VectorRecord -> VectorIndex（可选 FAISS FlatIP / **HNSW**）

    VectorIndex.search(query)
      -> 与建库相同后端编码 query
      -> 可选 FAISS；HNSW 仅在向量数 ≥ 阈值时启用，否则 FlatIP

    save_jsonl / load_jsonl
      -> 与 orchestrator 写入的 vector_meta.json 对齐（load 默认 auto_meta）

你可以继续练算法/工程化的点：
    1. IVF+PQ：超大规模语料可在 HNSW 之外再试 IVF 系列。
    2. 多向量：ColBERT token 级表示需另建索引结构。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from agent.learning.schemas import CodeSlice, VectorRecord

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

_ST_MODELS: dict[str, Any] = {}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}|[\u4e00-\u9fff]{2,}", text.lower())


def vectorize_text_openai(text: str, client: Optional[OpenAI] = None, model: str = "text-embedding-3-small") -> list[float]:
    if not client:
        if not OpenAI:
            raise ImportError("OpenAI package not installed")
        client = OpenAI()
    response = client.embeddings.create(input=text, model=model)
    return response.data[0].embedding


def encode_texts_sentence_transformer(
    texts: list[str],
    model_name: str,
    *,
    batch_size: int = 32,
) -> list[list[float]]:
    """对多段文本一次或分 batch 调用 ST，加速建库。"""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        raise ImportError("pip install sentence-transformers") from e
    if model_name not in _ST_MODELS:
        _ST_MODELS[model_name] = SentenceTransformer(model_name)
    model = _ST_MODELS[model_name]
    arr = model.encode(
        texts,
        batch_size=max(1, int(batch_size)),
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    try:
        import numpy as np

        mat = np.asarray(arr, dtype=float)
        if mat.ndim == 1:
            mat = mat.reshape(1, -1)
        return [[float(x) for x in mat[i].reshape(-1).tolist()] for i in range(mat.shape[0])]
    except Exception:
        return [[float(x) for x in list(row)] for row in arr]


def vectorize_text_sentence_transformer(text: str, model_name: str) -> list[float]:
    return encode_texts_sentence_transformer([text], model_name, batch_size=1)[0]


def vectorize_text(text: str, dimensions: int = 256, use_openai: bool = False, client: Optional[OpenAI] = None, model: str = "text-embedding-3-small") -> list[float]:
    if use_openai:
        return vectorize_text_openai(text, client, model)
    dim = max(int(dimensions), 8)
    vec = [0.0] * dim
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0:
        return vec
    return [x / norm for x in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


def _l2_normalize_vector(v: list[float]) -> list[float]:
    s = math.sqrt(sum(x * x for x in v))
    if s <= 1e-12:
        return list(v)
    return [x / s for x in v]


class VectorIndex:
    def __init__(
        self,
        records: Iterable[VectorRecord] = (),
        dimensions: int = 256,
        use_openai: bool = False,
        client: Optional[OpenAI] = None,
        model: str = "text-embedding-3-small",
        *,
        use_sentence_transformer: bool = False,
        sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        use_faiss: bool = False,
        use_faiss_hnsw: bool = False,
        faiss_hnsw_min_vectors: int = 256,
        faiss_hnsw_m: int = 32,
        faiss_hnsw_ef_construct: int = 64,
        faiss_hnsw_ef_search: int = 64,
    ) -> None:
        self.records = list(records)
        self.use_openai = bool(use_openai)
        self.client = client
        self.model = model
        self.use_sentence_transformer = bool(use_sentence_transformer) and not self.use_openai
        self.sentence_transformer_model = sentence_transformer_model
        self.use_faiss = bool(use_faiss)
        self.use_faiss_hnsw = bool(use_faiss_hnsw)
        self.faiss_hnsw_min_vectors = max(8, int(faiss_hnsw_min_vectors))
        self.faiss_hnsw_m = max(8, int(faiss_hnsw_m))
        self.faiss_hnsw_ef_construct = max(8, int(faiss_hnsw_ef_construct))
        self.faiss_hnsw_ef_search = max(8, int(faiss_hnsw_ef_search))
        self._faiss_index: Any = None
        self._faiss_dirty = True
        if self.records:
            d = len(self.records[0].vector)
            self.dimensions = d if d > 0 else dimensions
        else:
            self.dimensions = dimensions

    def add(self, record: VectorRecord) -> None:
        self.records.append(record)
        self._faiss_dirty = True

    def view_subset(self, records: list[VectorRecord]) -> "VectorIndex":
        """同一套嵌入/FAISS 配置下仅检索子集（用于元数据过滤等）。"""
        return VectorIndex(
            records,
            dimensions=self.dimensions,
            use_openai=self.use_openai,
            client=self.client,
            model=self.model,
            use_sentence_transformer=self.use_sentence_transformer,
            sentence_transformer_model=self.sentence_transformer_model,
            use_faiss=self.use_faiss,
            use_faiss_hnsw=self.use_faiss_hnsw,
            faiss_hnsw_min_vectors=self.faiss_hnsw_min_vectors,
            faiss_hnsw_m=self.faiss_hnsw_m,
            faiss_hnsw_ef_construct=self.faiss_hnsw_ef_construct,
            faiss_hnsw_ef_search=self.faiss_hnsw_ef_search,
        )

    def _encode_query(self, text: str) -> list[float]:
        if self.use_openai:
            return vectorize_text_openai(text, self.client, self.model)
        if self.use_sentence_transformer:
            return vectorize_text_sentence_transformer(text, self.sentence_transformer_model)
        return vectorize_text(text, self.dimensions)

    def _rebuild_faiss(self) -> None:
        self._faiss_index = None
        if not self.use_faiss or not self.records:
            self._faiss_dirty = False
            return
        try:
            import faiss
            import numpy as np
        except ImportError:
            self._faiss_dirty = False
            return
        dim = len(self.records[0].vector)
        mat = np.array([r.vector for r in self.records], dtype=np.float32)
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms = np.where(norms < 1e-12, 1.0, norms)
        mat = mat / norms
        n = int(mat.shape[0])
        if self.use_faiss_hnsw and n >= self.faiss_hnsw_min_vectors:
            index = faiss.IndexHNSWFlat(dim, self.faiss_hnsw_m)
            index.hnsw.efConstruction = self.faiss_hnsw_ef_construct
            index.add(mat)
            index.hnsw.efSearch = self.faiss_hnsw_ef_search
        else:
            index = faiss.IndexFlatIP(dim)
            index.add(mat)
        self._faiss_index = index
        self._faiss_dirty = False

    def _search_faiss(self, qv: list[float], top_k: int) -> list[tuple[float, VectorRecord]]:
        if self._faiss_dirty or self._faiss_index is None:
            self._rebuild_faiss()
        if self._faiss_index is None:
            return []
        import numpy as np

        q = np.array([_l2_normalize_vector(qv)], dtype=np.float32)
        k = min(max(int(top_k), 1), len(self.records))
        sims, idxs = self._faiss_index.search(q, k)
        row_sims = sims[0].tolist()
        row_idxs = idxs[0].tolist()
        out: list[tuple[float, VectorRecord]] = []
        for score, i in zip(row_sims, row_idxs):
            if i < 0:
                continue
            sc = float(score)
            if sc > 0:
                out.append((sc, self.records[i]))
        return out

    def _search_linear(self, qv: list[float], top_k: int) -> list[tuple[float, VectorRecord]]:
        scored = [(cosine_similarity(qv, record.vector), record) for record in self.records]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [(score, record) for score, record in scored[: max(int(top_k), 0)] if score > 0]

    def search(self, query: str, top_k: int = 5) -> list[tuple[float, VectorRecord]]:
        qv = self._encode_query(query)
        if self.use_faiss and len(self.records) > 0:
            try:
                hits = self._search_faiss(qv, top_k)
                if hits:
                    return hits
            except Exception:
                pass
        return self._search_linear(qv, top_k)

    def to_meta_dict(self) -> dict[str, Any]:
        return {
            "dimensions": self.dimensions,
            "use_openai": self.use_openai,
            "model": self.model,
            "use_sentence_transformer": self.use_sentence_transformer,
            "sentence_transformer_model": self.sentence_transformer_model,
            "use_faiss": self.use_faiss,
            "use_faiss_hnsw": self.use_faiss_hnsw,
            "faiss_hnsw_min_vectors": self.faiss_hnsw_min_vectors,
            "faiss_hnsw_m": self.faiss_hnsw_m,
            "faiss_hnsw_ef_construct": self.faiss_hnsw_ef_construct,
            "faiss_hnsw_ef_search": self.faiss_hnsw_ef_search,
        }

    def save_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for record in self.records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    @staticmethod
    def load_jsonl(
        path: Path,
        dimensions: int = 256,
        use_openai: bool = False,
        client: Optional[OpenAI] = None,
        model: str = "text-embedding-3-small",
        *,
        use_faiss: bool = False,
        use_sentence_transformer: bool = False,
        sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2",
        use_faiss_hnsw: bool = False,
        faiss_hnsw_min_vectors: int = 256,
        faiss_hnsw_m: int = 32,
        faiss_hnsw_ef_construct: int = 64,
        faiss_hnsw_ef_search: int = 64,
        auto_meta: bool = True,
    ) -> "VectorIndex":
        if auto_meta:
            meta_path = path.parent / "vector_meta.json"
            if meta_path.exists():
                try:
                    raw = json.loads(meta_path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        dimensions = int(raw.get("dimensions", dimensions))
                        use_openai = bool(raw.get("use_openai", use_openai))
                        model = str(raw.get("model", model))
                        use_faiss = bool(raw.get("use_faiss", use_faiss))
                        use_sentence_transformer = bool(
                            raw.get("use_sentence_transformer", use_sentence_transformer)
                        )
                        sentence_transformer_model = str(
                            raw.get("sentence_transformer_model", sentence_transformer_model)
                        )
                        use_faiss_hnsw = bool(raw.get("use_faiss_hnsw", use_faiss_hnsw))
                        faiss_hnsw_min_vectors = int(raw.get("faiss_hnsw_min_vectors", faiss_hnsw_min_vectors))
                        faiss_hnsw_m = int(raw.get("faiss_hnsw_m", faiss_hnsw_m))
                        faiss_hnsw_ef_construct = int(raw.get("faiss_hnsw_ef_construct", faiss_hnsw_ef_construct))
                        faiss_hnsw_ef_search = int(raw.get("faiss_hnsw_ef_search", faiss_hnsw_ef_search))
                except (json.JSONDecodeError, OSError, TypeError, ValueError):
                    pass
        records: list[VectorRecord] = []
        if not path.exists():
            return VectorIndex(
                dimensions=dimensions,
                use_openai=use_openai,
                client=client,
                model=model,
                use_sentence_transformer=use_sentence_transformer,
                sentence_transformer_model=sentence_transformer_model,
                use_faiss=use_faiss,
                use_faiss_hnsw=use_faiss_hnsw,
                faiss_hnsw_min_vectors=faiss_hnsw_min_vectors,
                faiss_hnsw_m=faiss_hnsw_m,
                faiss_hnsw_ef_construct=faiss_hnsw_ef_construct,
                faiss_hnsw_ef_search=faiss_hnsw_ef_search,
            )
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            records.append(
                VectorRecord(
                    record_id=str(data.get("record_id", "")),
                    text=str(data.get("text", "")),
                    metadata=dict(data.get("metadata") or {}),
                    vector=[float(x) for x in data.get("vector", [])],
                )
            )
        return VectorIndex(
            records,
            dimensions=dimensions,
            use_openai=use_openai,
            client=client,
            model=model,
            use_sentence_transformer=use_sentence_transformer,
            sentence_transformer_model=sentence_transformer_model,
            use_faiss=use_faiss,
            use_faiss_hnsw=use_faiss_hnsw,
            faiss_hnsw_min_vectors=faiss_hnsw_min_vectors,
            faiss_hnsw_m=faiss_hnsw_m,
            faiss_hnsw_ef_construct=faiss_hnsw_ef_construct,
            faiss_hnsw_ef_search=faiss_hnsw_ef_search,
        )


def build_vector_index(
    slices: Iterable[CodeSlice],
    dimensions: int = 256,
    use_openai: bool = False,
    client: Optional[OpenAI] = None,
    model: str = "text-embedding-3-small",
    *,
    use_sentence_transformer: bool = False,
    sentence_transformer_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    st_batch_size: int = 32,
    use_faiss: bool = False,
    use_faiss_hnsw: bool = False,
    faiss_hnsw_min_vectors: int = 256,
    faiss_hnsw_m: int = 32,
    faiss_hnsw_ef_construct: int = 64,
    faiss_hnsw_ef_search: int = 64,
) -> VectorIndex:
    slices_list = list(slices)
    records: list[VectorRecord] = []
    eff_dim = dimensions
    if not slices_list:
        return VectorIndex(
            dimensions=eff_dim,
            use_openai=use_openai,
            client=client,
            model=model,
            use_sentence_transformer=use_sentence_transformer and not use_openai,
            sentence_transformer_model=sentence_transformer_model,
            use_faiss=use_faiss,
            use_faiss_hnsw=use_faiss_hnsw,
            faiss_hnsw_min_vectors=faiss_hnsw_min_vectors,
            faiss_hnsw_m=faiss_hnsw_m,
            faiss_hnsw_ef_construct=faiss_hnsw_ef_construct,
            faiss_hnsw_ef_search=faiss_hnsw_ef_search,
        )
    if use_openai:
        for sl in slices_list:
            vector = vectorize_text_openai(sl.text, client, model)
            eff_dim = len(vector)
            records.append(
                VectorRecord(
                    record_id=sl.slice_id,
                    text=sl.text,
                    metadata={
                        "path": sl.path,
                        "language": sl.language,
                        "start_line": sl.start_line,
                        "end_line": sl.end_line,
                        "tokens": list(sl.tokens),
                    },
                    vector=vector,
                )
            )
    elif use_sentence_transformer:
        texts = [sl.text for sl in slices_list]
        vecs = encode_texts_sentence_transformer(texts, sentence_transformer_model, batch_size=st_batch_size)
        eff_dim = len(vecs[0])
        for sl, vector in zip(slices_list, vecs):
            records.append(
                VectorRecord(
                    record_id=sl.slice_id,
                    text=sl.text,
                    metadata={
                        "path": sl.path,
                        "language": sl.language,
                        "start_line": sl.start_line,
                        "end_line": sl.end_line,
                        "tokens": list(sl.tokens),
                    },
                    vector=vector,
                )
            )
    else:
        for sl in slices_list:
            vector = vectorize_text(sl.text, dimensions, False, None, model)
            records.append(
                VectorRecord(
                    record_id=sl.slice_id,
                    text=sl.text,
                    metadata={
                        "path": sl.path,
                        "language": sl.language,
                        "start_line": sl.start_line,
                        "end_line": sl.end_line,
                        "tokens": list(sl.tokens),
                    },
                    vector=vector,
                )
            )
    return VectorIndex(
        records,
        dimensions=eff_dim,
        use_openai=use_openai,
        client=client,
        model=model,
        use_sentence_transformer=use_sentence_transformer and not use_openai,
        sentence_transformer_model=sentence_transformer_model,
        use_faiss=use_faiss,
        use_faiss_hnsw=use_faiss_hnsw,
        faiss_hnsw_min_vectors=faiss_hnsw_min_vectors,
        faiss_hnsw_m=faiss_hnsw_m,
        faiss_hnsw_ef_construct=faiss_hnsw_ef_construct,
        faiss_hnsw_ef_search=faiss_hnsw_ef_search,
    )
