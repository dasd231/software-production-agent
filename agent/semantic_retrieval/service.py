from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent.semantic_retrieval.builders import ContextPackageBuilder
from agent.semantic_retrieval.evaluators import CoverageEvaluator
from agent.semantic_retrieval.need_slot_planner import NeedSlotPlanner
from agent.semantic_retrieval.query_expander import QueryExpander
from agent.semantic_retrieval.rerankers import DiversityReranker, NecessityReranker
from agent.semantic_retrieval.retrievers import BaseRetriever, KeywordRetriever, PatternRetriever, VectorRetriever
from agent.semantic_retrieval.retrievers.base import merge_evidence
from agent.semantic_retrieval.schemas import CandidateEvidence, NeedSlot, SemanticContextPackage, SemanticRetrievalRequest
from agent.semantic_retrieval.task_parser import TaskParser


class SemanticRetrievalService:
    """Task-necessity retrieval service.

    Standard flow:
    request -> TaskSemanticFrame -> NeedSlot -> expanded slot queries ->
    multi-retriever -> necessity rerank -> diversity select -> coverage check ->
    structured SemanticContextPackage.
    """

    def __init__(
        self,
        *,
        task_parser: TaskParser | None = None,
        need_slot_planner: NeedSlotPlanner | None = None,
        query_expander: QueryExpander | None = None,
        retrievers: Sequence[BaseRetriever] | None = None,
        necessity_reranker: NecessityReranker | None = None,
        diversity_reranker: DiversityReranker | None = None,
        coverage_evaluator: CoverageEvaluator | None = None,
        context_package_builder: ContextPackageBuilder | None = None,
    ) -> None:
        self.task_parser = task_parser or TaskParser()
        self.need_slot_planner = need_slot_planner or NeedSlotPlanner()
        self.query_expander = query_expander or QueryExpander()
        self.retrievers = list(retrievers) if retrievers is not None else [PatternRetriever(), KeywordRetriever(), VectorRetriever()]
        self.necessity_reranker = necessity_reranker or NecessityReranker()
        self.diversity_reranker = diversity_reranker or DiversityReranker()
        self.coverage_evaluator = coverage_evaluator or CoverageEvaluator()
        self.context_package_builder = context_package_builder or ContextPackageBuilder()

    def resolve(self, request: SemanticRetrievalRequest | dict) -> SemanticContextPackage:
        req = request if isinstance(request, SemanticRetrievalRequest) else SemanticRetrievalRequest.from_dict(request)
        frame = self.task_parser.parse(req)
        slots = self.need_slot_planner.plan(frame)
        queries_by_slot = self.query_expander.expand_all(slots, frame, req.tech_stack)

        candidates = self._retrieve(slots, queries_by_slot, frame)
        ranked = self.necessity_reranker.rerank(frame=frame, slots=slots, candidates=candidates)
        selected = self.diversity_reranker.select(ranked=ranked, slots=slots, max_items=req.max_context_items)
        coverage = self.coverage_evaluator.evaluate(slots=slots, selected=selected)

        if coverage.has_missing_must_have:
            weak_or_missing_ids = set(coverage.missing_slots) | set(coverage.weak_slots)
            missing_slots = [slot for slot in slots if slot.slot_id in weak_or_missing_ids]
            if missing_slots:
                extra_queries = self.query_expander.expand_all(missing_slots, frame, req.tech_stack)
                extra_candidates = self._retrieve(missing_slots, extra_queries, frame)
                merged = self._merge_candidates([*selected, *extra_candidates, *candidates])
                ranked = self.necessity_reranker.rerank(frame=frame, slots=slots, candidates=merged)
                selected = self.diversity_reranker.select(ranked=ranked, slots=slots, max_items=req.max_context_items)
                coverage = self.coverage_evaluator.evaluate(slots=slots, selected=selected)

        return self.context_package_builder.build(frame=frame, slots=slots, selected=selected, coverage=coverage)

    def _retrieve(
        self,
        slots: Sequence[NeedSlot],
        queries_by_slot: Mapping[str, Sequence[str]],
        frame,
    ) -> list[CandidateEvidence]:
        candidates: list[CandidateEvidence] = []
        for retriever in self.retrievers:
            candidates.extend(retriever.retrieve(slots=slots, queries_by_slot=queries_by_slot, frame=frame))
        return self._merge_candidates(candidates)

    def _merge_candidates(self, candidates: Sequence[CandidateEvidence]) -> list[CandidateEvidence]:
        return merge_evidence(candidates)
