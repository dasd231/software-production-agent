"""研究向 RAG 检索管线：多查询 + 稠密/BM25 多列表 RRF、交叉编码器重排、Lost-in-the-Middle 编排。

设计对齐常见论文与工业界强基线（便于消融与复现）：
- **Hybrid**：稠密向量 + BM25，**RRF** 融合多路排序（Cormack et al., Reciprocal Rank Fusion）。
- **Multi-query**：对查询做轻量变体，多路召回后 RRF（类似 RAG-Fusion / 多视角查询思路，此处为无 LLM 的启发式变体）。
- **Rerank**：可选 **Cross-Encoder**（Nogueira & Cho 风格二阶段精排；默认 ms-marco MiniLM）。
- **LIM**：证据块 **U 形重排** 再写入提示，缓解 Liu et al. “Lost in the Middle” 现象。

依赖：`rank-bm25`；交叉编码器需可选安装 `sentence-transformers`（体积较大，默认尝试导入，失败则跳过精排）。
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from typing import Any

from agent.learning.schemas import VectorRecord
from agent.learning.vector_store import VectorIndex

try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = None


@dataclass(frozen=True)
class ResearchRAGConfig:
    """发刊/消融实验用：所有字段应可 JSON 序列化（便于附录复现实验配置）。"""

    multi_query: bool = False
    retrieve_multiplier: int = 6
    rrf_k: int = 60
    cross_encoder_model: str | None = None
    lost_in_middle: bool = False
    abstain_confidence_below: float | None = None
    path_prefixes: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    small_to_big: bool = False
    small_to_big_child_multiplier: int = 4
    small_to_big_parent_top_k: int | None = None

    def to_trace_dict(self) -> dict[str, Any]:
        return dict(asdict(self))


def benchmark_research_config() -> ResearchRAGConfig:
    """强基线预设：混合 + 多查询 RRF + CE 精排 + LIM（需安装 sentence-transformers 才有 CE）。"""
    return ResearchRAGConfig(
        multi_query=True,
        retrieve_multiplier=8,
        rrf_k=60,
        cross_encoder_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        lost_in_middle=True,
        small_to_big=True,
        abstain_confidence_below=None,
    )


def reciprocal_rank_fusion(
    ranked_lists: list[list[VectorRecord]],
    *,
    top_k: int,
    rrf_k: int = 60,
) -> list[tuple[float, VectorRecord]]:
    scores: dict[str, float] = {}
    by_id: dict[str, VectorRecord] = {}
    for ranked in ranked_lists:
        for rank, record in enumerate(ranked):
            rid = record.record_id
            by_id[rid] = record
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (rrf_k + rank + 1)
    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)[: max(1, top_k)]
    return [(sc, by_id[rid]) for rid, sc in merged if rid in by_id]


def bm25_hits(question: str, records: list[VectorRecord], top_k: int) -> list[tuple[float, VectorRecord]]:
    if not BM25Okapi or not records or not question.strip():
        return []
    corpus = [r.text for r in records]
    tokenized_corpus = [doc.split() for doc in corpus]
    bm25 = BM25Okapi(tokenized_corpus)
    tokenized_query = question.split()
    doc_scores = bm25.get_scores(tokenized_query)
    scored = [(float(score), record) for score, record in zip(doc_scores, records)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(score, record) for score, record in scored[:top_k] if score > 0]


def query_variants(question: str, *, max_variants: int = 4) -> list[str]:
    """无 LLM 的轻量多查询：原句、小写、按标点拆子句（适配中英混合 FAQ）。"""
    t = question.strip()
    if not t:
        return []
    variants: list[str] = [t]
    lo = t.lower()
    if lo != t:
        variants.append(lo)
    parts: list[str] = []
    for sep in ("。", "？", "?", ".", ";", "；", "\n"):
        for chunk in re.split(re.escape(sep), t):
            c = chunk.strip()
            if len(c) >= 6:
                parts.append(c)
    variants.extend(parts[: max(0, max_variants - len(variants))])
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        key = v.casefold()
        if key in seen or not v:
            continue
        seen.add(key)
        out.append(v)
        if len(out) >= max_variants:
            break
    return out[:max_variants]


def _norm_rel_path(p: str) -> str:
    return str(p).replace("\\", "/").strip()


def _path_matches_prefixes(path: str, prefixes: tuple[str, ...]) -> bool:
    if not prefixes:
        return True
    p = _norm_rel_path(path)
    for raw in prefixes:
        pref = _norm_rel_path(raw).strip("/")
        if not pref:
            continue
        if p == pref or p.startswith(pref + "/"):
            return True
    return False


def _language_matches(meta: dict[str, Any], languages: tuple[str, ...]) -> bool:
    if not languages:
        return True
    lg = str(meta.get("language", "")).lower()
    return lg in {str(x).lower() for x in languages if str(x).strip()}


def maybe_path_filtered_index(
    vector_index: VectorIndex,
    research: ResearchRAGConfig,
) -> tuple[VectorIndex, dict[str, Any]]:
    """按 path 前缀与 language 元数据缩小检索语料（仅 research 路径使用）。"""
    prefs = tuple(x for x in research.path_prefixes if _norm_rel_path(x))
    langs = tuple(x for x in research.languages if str(x).strip())
    if not prefs and not langs:
        return vector_index, {}
    kept: list[VectorRecord] = []
    for r in vector_index.records:
        p = str(r.metadata.get("path", ""))
        if not _path_matches_prefixes(p, prefs):
            continue
        if not _language_matches(r.metadata, langs):
            continue
        kept.append(r)
    trace: dict[str, Any] = {
        "path_prefix_filter": list(prefs),
        "language_filter": list(langs),
        "records_pre_filter": len(vector_index.records),
        "records_post_filter": len(kept),
    }
    if len(kept) == len(vector_index.records):
        return vector_index, trace
    return vector_index.view_subset(kept), trace


def lost_in_middle_reorder(records: list[VectorRecord]) -> list[VectorRecord]:
    """按相关性已降序的 `records`，重排为 U 形：强证据靠近上下文首尾（Liu et al.）。"""
    n = len(records)
    if n <= 2:
        return list(records)
    result: list[VectorRecord | None] = [None] * n
    left, right = 0, n - 1
    for i, doc in enumerate(records):
        if i % 2 == 0:
            result[left] = doc
            left += 1
        else:
            result[right] = doc
            right -= 1
    return [r for r in result if r is not None]


def cross_encoder_rerank(
    query: str,
    candidates: list[VectorRecord],
    *,
    model_name: str,
    top_k: int,
    max_doc_chars: int = 1800,
) -> list[tuple[float, VectorRecord]]:
    try:
        from sentence_transformers import CrossEncoder
    except ImportError:
        return [(float(max(0, 1.0 - i * 1e-4)), r) for i, r in enumerate(candidates[: max(1, top_k)])]
    model = CrossEncoder(model_name)
    pairs = [[query, (r.text or "")[:max_doc_chars]] for r in candidates]
    raw = model.predict(pairs, show_progress_bar=False, convert_to_numpy=True)
    try:
        import numpy as np

        scores = [float(x) for x in np.asarray(raw, dtype=float).reshape(-1).tolist()]
    except Exception:
        scores = [float(raw)] * len(candidates)
    if len(scores) != len(candidates):
        scores = (scores + [0.0] * len(candidates))[: len(candidates)]
    ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)
    return [(s, r) for s, r in ranked[: max(1, top_k)]]


def retrieve_evidence_unified(
    question: str,
    vector_index: VectorIndex,
    *,
    top_k: int,
    use_bm25: bool,
    research: ResearchRAGConfig | None,
) -> tuple[list[tuple[float, VectorRecord]], dict[str, Any]]:
    """统一检索出口：baseline 或研究配置；返回 (带分证据, 可写入论文附录的 trace)。"""
    trace: dict[str, Any] = {"baseline_hybrid_only": research is None}
    work_index = vector_index
    if research is not None:
        work_index, ftrace = maybe_path_filtered_index(vector_index, research)
        trace.update(ftrace)
    t0 = time.perf_counter()
    if research is None:
        fetch_k = max(top_k * 3, top_k)
        vector_hits = work_index.search(question, top_k=fetch_k)
        if not use_bm25 or not work_index.records:
            trace.update({"mode": "dense_only" if not use_bm25 else "dense", "fetch_k": fetch_k})
            trace["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            return vector_hits[:top_k], trace
        bm25_list = bm25_hits(question, work_index.records, top_k=fetch_k)
        vec_order = [r for _, r in vector_hits]
        bm_order = [r for _, r in bm25_list]
        if not vec_order and not bm_order:
            trace.update({"mode": "hybrid", "fetch_k": fetch_k})
            trace["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            return [], trace
        if not vec_order:
            trace.update({"mode": "bm25_fallback"})
            trace["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            return bm25_list[:top_k], trace
        if not bm_order:
            trace.update({"mode": "dense_fallback"})
            trace["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 3)
            return vector_hits[:top_k], trace
        fused = reciprocal_rank_fusion([vec_order, bm_order], top_k=top_k, rrf_k=60)
        trace.update({"mode": "hybrid_rrf", "fetch_k": fetch_k, "rrf_k": 60})
        trace["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return fused, trace

    # --- Research path ---
    mult = max(int(research.retrieve_multiplier), 2)
    fetch_k = max(top_k * mult, top_k)
    variants = query_variants(question, max_variants=4) if research.multi_query else [question]
    trace["query_variants"] = list(variants)
    trace["rrf_k"] = int(research.rrf_k)

    lists_to_fuse: list[list[VectorRecord]] = []
    for qv in variants:
        vh = work_index.search(qv, top_k=fetch_k)
        lists_to_fuse.append([r for _, r in vh])
        if use_bm25 and work_index.records:
            bh = bm25_hits(qv, work_index.records, top_k=fetch_k)
            lists_to_fuse.append([r for _, r in bh])
    lists_to_fuse = [lst for lst in lists_to_fuse if lst]
    if not lists_to_fuse:
        trace["mode"] = "empty"
        trace["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 3)
        return [], trace

    fused = reciprocal_rank_fusion(lists_to_fuse, top_k=fetch_k, rrf_k=int(research.rrf_k))
    trace["mode"] = "multi_rrf" if research.multi_query else "hybrid_rrf"
    trace["pre_fusion_lists"] = len(lists_to_fuse)
    trace["pre_rerank"] = len(fused)

    records = [r for _, r in fused]
    if research.cross_encoder_model and records:
        reranked = cross_encoder_rerank(
            question,
            records,
            model_name=research.cross_encoder_model,
            top_k=top_k,
        )
        trace["cross_encoder"] = research.cross_encoder_model
        evidence = reranked
    else:
        trace["cross_encoder"] = None
        evidence = fused[:top_k]

    if research.lost_in_middle and len(evidence) > 2:
        recs = [r for _, r in evidence]
        lim = lost_in_middle_reorder(recs)
        id_to_score = {r.record_id: float(s) for s, r in evidence}
        evidence = [(id_to_score.get(r.record_id, 0.0), r) for r in lim]
        trace["lost_in_middle"] = True
    else:
        trace["lost_in_middle"] = False

    trace["research_config"] = research.to_trace_dict()
    trace["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    return evidence[:top_k], trace
