from __future__ import annotations

import json
from pathlib import Path

from agent.command_api import build_command_api_plan, command_api_to_property_graph
from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded


def test_command_api_plan_centralizes_large_project_commands() -> None:
    plan = build_command_api_plan("大项目治理")

    assert plan["schema"] == "command_api_plan.v1"
    assert len(plan["commands"]) >= 8
    assert any(cmd["action"] == "enterprise_workflow_compile" for cmd in plan["commands"])
    assert any(ctx["name"] == "workflow_control_plane" for ctx in plan["bounded_contexts"])
    assert plan["anti_looseness_rules"]
    assert "flowchart TD" in plan["mermaid"]
    assert "MERGE" in plan["cypher_seed"]


def test_command_api_property_graph_has_command_context_and_permissions() -> None:
    graph = command_api_to_property_graph()
    labels = {label for node in graph.nodes.values() for label in node.labels}
    edge_types = {edge.type for edge in graph.edges}

    assert {"CommandAPI", "BoundedContext", "Command", "Permission"} <= labels
    assert {"HAS_CONTEXT", "OWNS_COMMAND", "REQUIRES_PERMISSION"} <= edge_types


def test_command_api_action_writes_file_and_respects_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"command_api_plan","args":'
        '{"goal":"CommandAPI 大项目治理","output_path":"plans/command-api.json"}}'
    )
    result = run_action(tmp_path, action)
    assert result["ok"] is True
    assert result["summary"]["command_count"] >= 8
    assert (tmp_path / "plans" / "command-api.json").exists()

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
        limits=ExecutionLimits(granted_permissions=frozenset({"architecture:plan", "workspace:write"})),
    )
    assert allowed["ok"] is True


def test_enterprise_workflow_query_action(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"enterprise_workflow_query","args":'
        '{"query":"MES ERP 副作用 幂等 人工审批","output_path":"plans/workflow-query.json"}}'
    )
    result = run_action(tmp_path, action)
    assert result["ok"] is True
    assert result["summary"]["insight_count"] >= 1
    payload = json.loads((tmp_path / "plans" / "workflow-query.json").read_text(encoding="utf-8"))
    assert payload["schema"] == "enterprise_workflow_graph_rag.v1"
