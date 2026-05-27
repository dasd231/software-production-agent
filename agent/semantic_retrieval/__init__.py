"""Task-necessity semantic retrieval.

This module solves similarity disaster for software-production tasks by moving
from query->topK chunks to:

TaskSemanticFrame -> NeedSlot -> MultiRetriever -> NecessityReranker ->
CoverageEvaluator -> SemanticContextPackage.

It intentionally does not implement Agent Runtime, code generation, tools or
sandbox execution.
"""

from agent.semantic_retrieval.schemas import (
    CandidateEvidence,
    CoverageReport,
    NeedSlot,
    PatternCard,
    SemanticContextPackage,
    SemanticRetrievalRequest,
    TaskSemanticFrame,
)
from agent.semantic_retrieval.graph_projection import semantic_context_graph_bundle, semantic_context_to_property_graph
from agent.semantic_retrieval.service import SemanticRetrievalService

__all__ = [
    "CandidateEvidence",
    "CoverageReport",
    "NeedSlot",
    "PatternCard",
    "SemanticContextPackage",
    "SemanticRetrievalRequest",
    "SemanticRetrievalService",
    "semantic_context_graph_bundle",
    "semantic_context_to_property_graph",
    "TaskSemanticFrame",
]

