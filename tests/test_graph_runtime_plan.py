from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.graph_runtime import PropertyGraph, build_demo_agent_graph, build_graph_runtime_plan


def test_property_graph_supports_neighbors_shortest_path_and_cypher() -> None:
    graph = PropertyGraph()
    graph.add_node("run:1", ("AgentRun",), goal="demo")
    graph.add_node("decision:1", ("Decision",), choice="safe_execute")
    graph.add_node("artifact:1", ("Artifact",), path="out.json")
    graph.add_edge("run:1", "MADE", "decision:1")
    graph.add_edge("decision:1", "PRODUCED", "artifact:1")

    assert graph.neighbors("run:1", edge_type="MADE")[0].id == "decision:1"
    assert graph.shortest_path("run:1", "artifact:1") == ["run:1", "decision:1", "artifact:1"]
    cypher = graph.to_cypher_seed()
    assert "MERGE" in cypher
    assert "AgentRun" in cypher


def test_graph_runtime_plan_makes_langgraph_and_graphdb_explicit() -> None:
    plan = build_graph_runtime_plan("面试解释 LangGraph 二改和图数据库记忆")

    assert plan["schema"] == "graph_runtime_plan.v1"
    names = {item["name"] for item in plan["langgraph_second_modifications"]}
    assert "Graph database checkpointer" in names
    assert "Graph-RAG for Agent memory" in names
    labels = {item["label"] for item in plan["graph_db_schema"]["node_labels"]}
    assert {"AgentRun", "Decision", "Evidence", "PolicyVersion", "HumanReview", "SimilarityCollapse"} <= labels
    edge_kinds = {edge["kind"] for edge in plan["runtime_graph"]["edges"]}
    assert "conditional" in edge_kinds
    assert "Cypher" not in plan["positioning"]  # plan is backend-agnostic, cypher is only an export artifact
    assert "MERGE" in plan["cypher_seed"]


def test_demo_agent_graph_connects_action_to_evidence_and_artifact() -> None:
    graph = build_demo_agent_graph("demo")
    data = graph.to_dict()

    edge_types = {edge["type"] for edge in data["edges"]}
    assert {"CITED", "PRODUCED", "USED_POLICY"} <= edge_types
    assert graph.shortest_path("run:demo", "artifact:manifest")


def test_graph_runtime_plan_action_writes_file_and_respects_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"graph_runtime_plan","args":'
        '{"goal":"LangGraph 二改 + 图数据库 Agent memory","output_path":"plans/graph-runtime.json"}}'
    )
    result = run_action(tmp_path, action)
    assert result["ok"] is True
    assert result["summary"]["graph_label_count"] >= 5
    assert (tmp_path / "plans" / "graph-runtime.json").exists()

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
        limits=ExecutionLimits(granted_permissions=frozenset({"graph:plan", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"
