from __future__ import annotations

import hashlib
from typing import Any

from agent.graph_runtime.property_graph import PropertyGraph
from agent.semantic_retrieval.schemas import SemanticContextPackage


def _id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(str(value).encode("utf-8", errors="ignore")).hexdigest()[:14]
    return f"{prefix}:{digest}"


def semantic_context_to_property_graph(package: SemanticContextPackage) -> PropertyGraph:
    """Project a SemanticContextPackage into the Agent LPG.

    This bridges task-necessity retrieval with GraphRAG: later queries can inspect
    which NeedSlot existed, which evidence matched it, which evidence was selected,
    and whether coverage was good enough for autonomous downstream work.
    """

    graph = PropertyGraph()
    frame = package.task_frame
    frame_id = _id("task_frame", frame.raw_requirement + frame.target_module)
    package_id = _id("semantic_context", package.task_summary + frame.raw_requirement)

    graph.add_node(
        frame_id,
        ("TaskSemanticFrame",),
        raw_requirement=frame.raw_requirement,
        task_type=frame.task_type,
        domain=frame.domain,
        product_type=frame.product_type,
        target_module=frame.target_module,
    )
    graph.add_node(
        package_id,
        ("SemanticContextPackage", "ContextPackage"),
        task_summary=package.task_summary,
        missing_slots=list(package.missing_slots),
        selected_evidence_count=len(package.selected_evidence),
    )
    graph.add_edge(package_id, "SELECTED_FOR", frame_id)

    slot_node_ids: dict[str, str] = {}
    for slot in package.need_slots:
        slot_id = f"need_slot:{slot.slot_id}"
        slot_node_ids[slot.slot_id] = slot_id
        graph.add_node(
            slot_id,
            ("NeedSlot",),
            slot_id=slot.slot_id,
            slot_type=slot.slot_type,
            name=slot.name,
            necessity_level=slot.necessity_level,
            expected_evidence_types=list(slot.expected_evidence_types),
        )
        graph.add_edge(frame_id, "HAS_SLOT", slot_id)

    for evidence in package.selected_evidence:
        evidence_id = f"candidate_evidence:{evidence.evidence_id}"
        graph.add_node(
            evidence_id,
            ("CandidateEvidence", "Evidence"),
            evidence_id=evidence.evidence_id,
            title=evidence.title,
            source_type=evidence.source_type,
            verification_level=evidence.verification_level,
            final_score=round(float(evidence.final_score), 6),
            source_ref=evidence.source_ref,
        )
        graph.add_edge(evidence_id, "SELECTED_FOR", package_id, final_score=round(float(evidence.final_score), 6))
        for matched_slot_id in evidence.matched_slot_ids:
            slot_node_id = slot_node_ids.get(matched_slot_id)
            if slot_node_id:
                graph.add_edge(evidence_id, "MATCHED_EVIDENCE", slot_node_id, final_score=round(float(evidence.final_score), 6))

    if package.coverage_report is not None:
        report = package.coverage_report
        for name, value in (
            ("coverage_rate", report.coverage_rate),
            ("must_have_coverage_rate", report.must_have_coverage_rate),
        ):
            metric_id = _id("quality_metric", f"{package_id}:{name}:{value}")
            graph.add_node(metric_id, ("QualityMetric",), name=name, value=round(float(value), 6), window="single_context_package")
            graph.add_edge(package_id, "EVALUATED_BY", metric_id)
        if report.has_missing_must_have:
            warning_id = _id("evidence", package_id + ":missing_must_have")
            graph.add_node(
                warning_id,
                ("Evidence",),
                source_type="coverage_report",
                verification_level="static_verified",
                title="missing_must_have_or_weak_slots",
                missing_slots=list(report.missing_slots),
                weak_slots=list(report.weak_slots),
            )
            graph.add_edge(warning_id, "CITED", package_id)
    return graph


def semantic_context_graph_bundle(package: SemanticContextPackage) -> dict[str, Any]:
    graph = semantic_context_to_property_graph(package)
    return {
        "schema": "semantic_context_graph_bundle.v1",
        "graph": graph.to_dict(),
        "cypher_seed": graph.to_cypher_seed(),
        "mermaid": graph.to_mermaid(max_edges=120),
    }
