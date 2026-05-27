from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.workflow import (
    compile_enterprise_workflow,
    default_bioying_research_workflow,
    enterprise_contract_to_property_graph,
    import_dify_workflow,
    query_enterprise_workflow_contract,
)


def test_enterprise_workflow_contract_default_bioying_has_second_mod_controls() -> None:
    contract = compile_enterprise_workflow(goal="百英科研实验 Agent", domain="bio_research")

    assert contract["schema"] == "enterprise_workflow_contract.v1"
    assert contract["ok"] is True
    assert contract["assessment"]["readiness"] in {"ready_for_pilot", "needs_hardening_before_pilot"}
    assert contract["assessment"]["controlled_loop"] is True
    assert len(contract["langgraph_second_modifications"]) == 6
    assert "SimilarityCollapse" in contract["graph_memory_projection"]["node_labels"]

    nodes = {node["id"]: node for node in contract["nodes"]}
    assert nodes["mes_erp_adapter"]["side_effect_guard"]["enabled"] is True
    assert nodes["mes_erp_adapter"]["idempotency_key"].startswith("{run_id}:mes_erp_adapter")
    assert nodes["human_review"]["human_interrupt"]["required"] is True
    assert nodes["protocol_builder"]["evidence_contract"]["required"] is True
    assert any(stage["stage"] == "4_production" for stage in contract["enterprise_delivery_plan"])
    assert contract["graph_projection"]["nodes"]
    assert "MERGE" in contract["cypher_seed"]
    assert "flowchart TD" in contract["mermaid"]


def test_enterprise_workflow_contract_flags_uncontrolled_cycle_and_missing_human_gate() -> None:
    spec = {
        "name": "unsafe-direct-tool-call",
        "nodes": [
            {"id": "plan", "kind": "planner"},
            {"id": "submit_mes", "kind": "mes_adapter", "side_effect": True},
        ],
        "edges": [
            {"from": "plan", "to": "submit_mes"},
            {"from": "submit_mes", "to": "plan"},
        ],
    }

    contract = compile_enterprise_workflow(spec, domain="bio_research")

    assert contract["ok"] is False
    findings = {finding["code"] for finding in contract["assessment"]["findings"]}
    assert "cycle_detected" in findings
    assert "side_effect_without_upstream_human_gate" in findings
    assert contract["assessment"]["readiness"] == "blocked"


def test_enterprise_workflow_compile_action_writes_file_and_respects_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"enterprise_workflow_compile","args":'
        '{"goal":"百英科研 AgentOS","domain":"bio_research","output_path":"plans/enterprise-workflow.json"}}'
    )

    direct = run_action(tmp_path, action)
    assert direct["ok"] is True
    assert direct["summary"]["node_count"] >= 8
    assert direct["summary"]["delivery_stage_count"] == 6
    assert (tmp_path / "plans" / "enterprise-workflow.json").exists()

    denied = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "PERMISSION_DENIED"

    allowed = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"workflow:compile", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"


def test_default_bioying_workflow_is_dify_like_input_shape() -> None:
    spec = default_bioying_research_workflow("抗体表达")

    assert spec["schema"] == "enterprise_workflow_input.v1"
    assert any(node["id"] == "collapse_guard" for node in spec["nodes"])
    assert any(edge.get("route") == "collapse_alarm_rewind" for edge in spec["edges"])


def test_dify_like_workflow_import_compiles_to_enterprise_contract() -> None:
    dify_export = {
        "name": "research-assistant",
        "graph": {
            "nodes": [
                {"id": "start", "data": {"type": "start", "title": "输入实验目标"}},
                {"id": "kb", "data": {"type": "knowledge-retrieval", "title": "检索 SOP"}},
                {"id": "llm", "data": {"type": "llm", "title": "生成 protocol"}},
                {"id": "review", "data": {"type": "human-review", "title": "PI 审批"}},
                {"id": "submit", "data": {"type": "http-request", "title": "提交 MES 工单"}},
            ],
            "edges": [
                {"source": "start", "target": "kb"},
                {"source": "kb", "target": "llm"},
                {"source": "llm", "target": "review", "sourceHandle": "needs_review"},
                {"source": "review", "target": "submit", "sourceHandle": "approved"},
            ],
        },
    }

    imported = import_dify_workflow(dify_export)
    assert imported["source"] == "dify"
    assert any(node["kind"] == "rag" for node in imported["nodes"])
    assert any(node["kind"] == "human_review" for node in imported["nodes"])

    contract = compile_enterprise_workflow(dify_export, domain="bio_research")
    submit = {node["id"]: node for node in contract["nodes"]}["submit"]
    assert submit["side_effect_guard"]["enabled"] is True
    assert submit["human_interrupt"]["required"] is True
    assert contract["graph_projection"]["edges"]


def test_enterprise_contract_to_property_graph_contains_release_gates_and_routes() -> None:
    contract = compile_enterprise_workflow(goal="百英科研实验 Agent", domain="bio_research")
    graph = enterprise_contract_to_property_graph(contract)

    labels = {label for node in graph.nodes.values() for label in node.labels}
    edge_types = {edge.type for edge in graph.edges}
    assert {"EnterpriseWorkflow", "WorkflowNode", "ReleaseGate", "DeliveryStage"} <= labels
    assert {"HAS_NODE", "ROUTES_TO", "REQUIRES_GATE", "HAS_DELIVERY_STAGE"} <= edge_types
    assert "MERGE" in graph.to_cypher_seed()
    assert "flowchart TD" in graph.to_mermaid()


def test_enterprise_workflow_graph_rag_query_surfaces_side_effect_controls() -> None:
    contract = compile_enterprise_workflow(goal="百英科研实验 Agent", domain="bio_research")
    result = query_enterprise_workflow_contract(contract, "MES ERP 副作用 幂等 人工审批", top_k=4)

    assert result["schema"] == "enterprise_workflow_graph_rag.v1"
    assert result["insights"]
    assert any(item["kind"] == "side_effect_control" for item in result["insights"])
    assert result["graph_rag"]["anchor_nodes"]
