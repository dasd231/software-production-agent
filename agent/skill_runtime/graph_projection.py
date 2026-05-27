from __future__ import annotations

import hashlib
from typing import Any, Mapping

from agent.graph_runtime.property_graph import PropertyGraph


def _node_id(prefix: str, value: str) -> str:
    return f"{prefix}:{hashlib.sha1(str(value).encode('utf-8', errors='ignore')).hexdigest()[:14]}"


def skill_runtime_to_property_graph(
    *,
    run_id: str,
    node_name: str,
    skill_bundle: Mapping[str, Any],
    guard_report: Mapping[str, Any] | None = None,
) -> PropertyGraph:
    """Project SkillBundle/GuardReport into the project LPG."""

    graph = PropertyGraph()
    run_node = f"run:{run_id}"
    workflow_node = f"workflow_node:{node_name}"
    bundle_id = _node_id("skill_bundle", f"{run_id}:{node_name}:{skill_bundle}")
    graph.add_node(run_node, ("AgentRun",), goal=str(skill_bundle.get("task_contract", {}).get("user_goal", "")))
    graph.add_node(workflow_node, ("WorkflowNode",), workflow_node_id=node_name, role="skill_guarded_node")
    graph.add_node(bundle_id, ("SkillBundle",), schema=str(skill_bundle.get("schema", "skill_bundle.v1")))
    graph.add_edge(run_node, "GUARDED_BY", bundle_id)
    graph.add_edge(run_node, "STARTED_AT", workflow_node)

    task_contract = skill_bundle.get("task_contract", {}) if isinstance(skill_bundle.get("task_contract"), Mapping) else {}
    if task_contract:
        contract_id = _node_id("task_contract", f"{run_id}:{node_name}:{task_contract.get('task_id', '')}")
        graph.add_node(
            contract_id,
            ("TaskContract",),
            task_id=str(task_contract.get("task_id", "")),
            task_type=str(task_contract.get("task_type", "")),
            user_goal=str(task_contract.get("user_goal", "")),
        )
        graph.add_edge(bundle_id, "GUARDED_BY", contract_id)

    fmt = skill_bundle.get("format_contract", {}) if isinstance(skill_bundle.get("format_contract"), Mapping) else {}
    if fmt:
        fmt_id = _node_id("format_contract", f"{run_id}:{node_name}:{fmt.get('schema_name', '')}")
        graph.add_node(fmt_id, ("FormatContract",), schema_name=str(fmt.get("schema_name", "")))
        graph.add_edge(bundle_id, "GUARDED_BY", fmt_id)

    reasoning = skill_bundle.get("reasoning_contract", {}) if isinstance(skill_bundle.get("reasoning_contract"), Mapping) else {}
    if reasoning:
        reasoning_id = _node_id("reasoning_contract", f"{run_id}:{node_name}:{reasoning.get('mode', '')}")
        graph.add_node(
            reasoning_id,
            ("ReasoningContract",),
            mode=str(reasoning.get("mode", "")),
            expose_hidden_chain_of_thought=bool(reasoning.get("expose_hidden_chain_of_thought", False)),
        )
        graph.add_edge(bundle_id, "GUARDED_BY", reasoning_id)

    for skill in skill_bundle.get("selected_skills", []) if isinstance(skill_bundle.get("selected_skills"), list) else []:
        if not isinstance(skill, Mapping):
            continue
        skill_id = str(skill.get("skill_id", ""))
        if not skill_id:
            continue
        skill_node = f"skill:{skill_id}"
        graph.add_node(
            skill_node,
            ("SkillCard",),
            skill_id=skill_id,
            name=str(skill.get("name", "")),
            risk_level=str(skill.get("risk_level", "low")),
            output_contract=str(skill.get("output_contract", "")),
        )
        graph.add_edge(run_node, "USED_SKILL", skill_node, node=node_name)
        graph.add_edge(bundle_id, "USED_SKILL", skill_node)

    if guard_report is not None:
        report_id = _node_id("guard_report", f"{run_id}:{node_name}:{guard_report}")
        violations = guard_report.get("violations", []) if isinstance(guard_report.get("violations"), list) else []
        graph.add_node(
            report_id,
            ("GuardReport", "QualityMetric"),
            ok=bool(guard_report.get("ok", False)),
            name="skill_guard_ok",
            value=1.0 if guard_report.get("ok") else 0.0,
            violation_count=len(violations),
        )
        graph.add_edge(run_node, "EVALUATED_BY", report_id)
        graph.add_edge(report_id, "VALIDATED_OUTPUT", bundle_id)
        for idx, violation in enumerate(violations):
            if not isinstance(violation, Mapping):
                continue
            violation_id = _node_id("evidence", f"{run_id}:{node_name}:violation:{idx}:{violation}")
            graph.add_node(
                violation_id,
                ("Evidence",),
                source_type="guard_violation",
                verification_level="static_verified",
                title=str(violation.get("code", "violation")),
                severity=str(violation.get("severity", "medium")),
                message=str(violation.get("message", "")),
            )
            graph.add_edge(violation_id, "CITED", report_id)
    return graph


def skill_runtime_graph_bundle(
    *,
    run_id: str,
    node_name: str,
    skill_bundle: Mapping[str, Any],
    guard_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    graph = skill_runtime_to_property_graph(
        run_id=run_id,
        node_name=node_name,
        skill_bundle=skill_bundle,
        guard_report=guard_report,
    )
    return {
        "schema": "skill_runtime_graph_bundle.v1",
        "graph": graph.to_dict(),
        "cypher_seed": graph.to_cypher_seed(),
        "mermaid": graph.to_mermaid(max_edges=120),
    }

