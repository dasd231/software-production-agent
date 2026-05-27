from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent.semantic_retrieval.retrievers.base import BaseRetriever, evidence_from_text, lexical_score, merge_evidence
from agent.semantic_retrieval.retrievers.keyword_retriever import TextDocument, _BUILTIN_DOCS
from agent.semantic_retrieval.schemas import CandidateEvidence, NeedSlot, TaskSemanticFrame


class VectorRetriever(BaseRetriever):
    """Local deterministic vector-retriever stand-in.

    The MVP intentionally avoids a heavyweight embedding dependency. It behaves
    like a vector channel from the service perspective, but final ranking is not
    allowed to trust this raw similarity score alone.
    """

    name = "vector"

    def __init__(self, documents: Sequence[TextDocument] | None = None, *, per_slot_top_k: int = 2, min_score: float = 0.03) -> None:
        self.documents = list(documents) if documents is not None else list(_BUILTIN_DOCS)
        self.per_slot_top_k = per_slot_top_k
        self.min_score = min_score

    def retrieve(
        self,
        slots: Sequence[NeedSlot],
        queries_by_slot: Mapping[str, Sequence[str]],
        frame: TaskSemanticFrame | None = None,
    ) -> list[CandidateEvidence]:
        by_doc: dict[str, CandidateEvidence] = {}
        for slot in slots:
            scored: list[tuple[float, TextDocument]] = []
            queries = [slot.name, slot.description, *slot.query_terms, *queries_by_slot.get(slot.slot_id, ())]
            for doc in self.documents:
                score = lexical_score(queries, doc.title + "\n" + doc.content)
                if score >= self.min_score:
                    scored.append((score, doc))
            for score, doc in sorted(scored, key=lambda item: item[0], reverse=True)[: self.per_slot_top_k]:
                candidate = evidence_from_text(
                    source_type=doc.source_type,
                    title=f"向量召回：{doc.title}",
                    content=doc.content,
                    matched_slot_ids=(slot.slot_id,),
                    raw_similarity_score=score,
                    verification_level=doc.verification_level,
                    source_ref=doc.source_ref,
                    metadata={"retriever": self.name, "doc_id": doc.doc_id, "vector_like": True},
                )
                existing = by_doc.get(doc.doc_id)
                if existing is None:
                    by_doc[doc.doc_id] = candidate
                else:
                    existing.matched_slot_ids = tuple(dict.fromkeys([*existing.matched_slot_ids, slot.slot_id]))
                    existing.raw_similarity_score = max(existing.raw_similarity_score, score)
        return merge_evidence(list(by_doc.values()))
