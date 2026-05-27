from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.graph_runtime.property_graph import PropertyGraph


_ALLOWED_NODE_LABELS = {
    "Action",
    "AgentRun",
    "Artifact",
    "CandidateEvidence",
    "Command",
    "ContextPackage",
    "Decision",
    "ErrorMemory",
    "Evidence",
    "GraphRelation",
    "HumanReview",
    "ModelArtifact",
    "NeedSlot",
    "PolicyVersion",
    "QualityMetric",
    "Reward",
    "SemanticContextPackage",
    "ReasoningContract",
    "FormatContract",
    "TaskContract",
    "GuardReport",
    "SkillBundle",
    "SkillCard",
    "SimilarityCollapse",
    "TaskSemanticFrame",
    "TrainingDataset",
    "WorkflowNode",
}
_ALLOWED_EDGE_TYPES = {
    "CITED",
    "DEPENDS_ON",
    "EVALUATED_BY",
    "EXECUTED",
    "FAILED_AT",
    "HAS_SLOT",
    "MADE",
    "MATCHED_EVIDENCE",
    "NEXT",
    "PATCHED_STATE",
    "PRODUCED",
    "REWARDED_BY",
    "ROUTED_TO",
    "SELECTED_FOR",
    "STARTED_AT",
    "TRAINED_ON",
    "VALIDATED_OUTPUT",
    "GUARDED_BY",
    "USED_SKILL",
    "USED_POLICY",
    "VALIDATED_BY",
}
_REQUIRED_PROPERTIES = {
    "AgentRun": ("goal",),
    "Decision": ("choice",),
    "Action": ("risk",),
    "NeedSlot": ("slot_id", "necessity_level"),
    "CandidateEvidence": ("source_type", "verification_level"),
    "ModelArtifact": ("target", "model_type"),
    "QualityMetric": ("name", "value"),
    "SkillCard": ("skill_id",),
    "GuardReport": ("ok",),
}


def build_agent_knowledge_graph_spec() -> dict[str, Any]:
    """Return the project-native LPG schema used by Agent memory and GraphRAG.

    The spec is intentionally backend-neutral: the same labels/edges can be
    enforced in the in-memory graph, Neo4j, Memgraph, AGE, or a future vector+KG
    hybrid store.
    """

    return {
        "schema": "agent_knowledge_graph_spec.v1",
        "positioning": "Labeled Property Graph for workflow traces, semantic retrieval evidence, model quality, and human feedback.",
        "node_labels": sorted(_ALLOWED_NODE_LABELS),
        "edge_types": sorted(_ALLOWED_EDGE_TYPES),
        "required_properties": {label: list(props) for label, props in sorted(_REQUIRED_PROPERTIES.items())},
        "indexes": [
            {"label": "AgentRun", "properties": ["run_id", "created_at"]},
            {"label": "NeedSlot", "properties": ["slot_id", "necessity_level"]},
            {"label": "CandidateEvidence", "properties": ["source_type", "verification_level", "final_score"]},
            {"label": "Action", "properties": ["action", "ok", "error_code"]},
            {"label": "ModelArtifact", "properties": ["target", "version", "status"]},
            {"label": "QualityMetric", "properties": ["name", "window", "value"]},
            {"label": "SkillCard", "properties": ["skill_id", "risk_level"]},
            {"label": "GuardReport", "properties": ["ok", "violation_count"]},
        ],
        "invariants": [
            "Every SemanticContextPackage must connect to at least one TaskSemanticFrame through SELECTED_FOR or PRODUCED.",
            "Every NeedSlot used in retrieval must be linked from exactly one TaskSemanticFrame through HAS_SLOT.",
            "CandidateEvidence must declare source_type and verification_level before it can be selected into context.",
            "ModelArtifact promotion requires TRAINED_ON TrainingDataset and EVALUATED_BY QualityMetric edges.",
            "HumanReview and Reward nodes must remain append-only to preserve auditability.",
            "Every AgentRun should connect to selected SkillCard through USED_SKILL before high-impact execution.",
        ],
        "graphrag_query_patterns": [
            {
                "name": "why_this_context",
                "cypher": "MATCH (f:TaskSemanticFrame)-[:HAS_SLOT]->(s:NeedSlot)<-[:MATCHED_EVIDENCE]-(e:CandidateEvidence) RETURN f,s,e ORDER BY e.final_score DESC",
            },
            {
                "name": "model_promotion_evidence",
                "cypher": "MATCH (m:ModelArtifact)-[:TRAINED_ON]->(d:TrainingDataset), (m)-[:EVALUATED_BY]->(q:QualityMetric) RETURN m,d,q",
            },
            {
                "name": "failure_to_policy_loop",
                "cypher": "MATCH (a:Action {ok:false})-[:REWARDED_BY]->(r:Reward)<-[:USED_POLICY]-(d:Decision) RETURN a,r,d",
            },
            {
                "name": "skill_runtime_guard",
                "cypher": "MATCH (run:AgentRun)-[:USED_SKILL]->(s:SkillCard), (run)-[:EVALUATED_BY]->(g:GuardReport) RETURN run,s,g",
            },
        ],
        "quality_gates": [
            "unknown verification evidence cannot be the only support for must_have NeedSlot",
            "GraphRAG answer must cite node ids and edge path, not only generated text",
            "schema drift requires migration notes before production ingestion",
            "SkillBundle selected before high-risk execution",
        ],
    }


def validate_property_graph_against_spec(graph: PropertyGraph, spec: Mapping[str, Any] | None = None) -> dict[str, Any]:
    spec = spec or build_agent_knowledge_graph_spec()
    allowed_labels = set(spec.get("node_labels", []))
    allowed_edges = set(spec.get("edge_types", []))
    required = {str(k): tuple(v) for k, v in dict(spec.get("required_properties", {})).items()}

    unknown_labels: list[dict[str, Any]] = []
    missing_properties: list[dict[str, Any]] = []
    for node in graph.nodes.values():
        labels = set(node.labels)
        unknown = sorted(labels - allowed_labels)
        if unknown:
            unknown_labels.append({"node_id": node.id, "unknown_labels": unknown})
        for label in labels:
            for prop in required.get(label, ()):
                if prop not in node.properties or node.properties.get(prop) in {None, ""}:
                    missing_properties.append({"node_id": node.id, "label": label, "property": prop})

    unknown_edge_types = [
        {"source": edge.source, "target": edge.target, "type": edge.type}
        for edge in graph.edges
        if edge.type not in allowed_edges
    ]
    ok = not unknown_labels and not unknown_edge_types and not missing_properties
    return {
        "schema": "agent_knowledge_graph_validation.v1",
        "ok": ok,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "unknown_labels": unknown_labels,
        "unknown_edge_types": unknown_edge_types,
        "missing_properties": missing_properties,
    }
