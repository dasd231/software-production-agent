"""Validate lightweight workflow specs before they become UI workflows."""

from __future__ import annotations

from typing import Any

from agent.chains.registry import get_chain


def _node_id(row: Any) -> str:
    if isinstance(row, str):
        return row
    if isinstance(row, dict):
        return str(row.get("id") or row.get("chain") or "").strip()
    return ""


def _node_chain(row: Any) -> str:
    if isinstance(row, str):
        return row
    if isinstance(row, dict):
        return str(row.get("chain") or row.get("action") or row.get("id") or "").strip()
    return ""


def _normalise_nodes(raw_nodes: Any) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    if not isinstance(raw_nodes, list):
        return nodes, ["nodes must be an array"]
    seen: set[str] = set()
    for i, raw in enumerate(raw_nodes):
        node_id = _node_id(raw)
        chain = _node_chain(raw)
        if not node_id:
            errors.append(f"nodes[{i}] missing id")
            continue
        if node_id in seen:
            errors.append(f"duplicate node id: {node_id}")
            continue
        seen.add(node_id)
        definition = get_chain(chain)
        if not definition:
            errors.append(f"unknown chain for node {node_id}: {chain}")
            nodes.append({"id": node_id, "chain": chain, "ok": False})
            continue
        nodes.append({"id": node_id, "chain": definition.name, "action": definition.action, "ok": True})
    return nodes, errors


def _normalise_edges(raw_edges: Any, node_ids: set[str]) -> tuple[list[tuple[str, str]], list[str]]:
    errors: list[str] = []
    edges: list[tuple[str, str]] = []
    if raw_edges in (None, ""):
        return edges, errors
    if not isinstance(raw_edges, list):
        return edges, ["edges must be an array"]
    for i, raw in enumerate(raw_edges):
        if isinstance(raw, dict):
            source = str(raw.get("from", "")).strip()
            target = str(raw.get("to", "")).strip()
        elif isinstance(raw, list | tuple) and len(raw) == 2:
            source = str(raw[0]).strip()
            target = str(raw[1]).strip()
        else:
            errors.append(f"edges[{i}] must be [from,to] or object")
            continue
        if source not in node_ids:
            errors.append(f"edge source not found: {source}")
        if target not in node_ids:
            errors.append(f"edge target not found: {target}")
        if source in node_ids and target in node_ids:
            edges.append((source, target))
    return edges, errors


def _toposort(node_ids: list[str], edges: list[tuple[str, str]]) -> tuple[list[str], bool]:
    incoming: dict[str, int] = {node: 0 for node in node_ids}
    outgoing: dict[str, list[str]] = {node: [] for node in node_ids}
    for source, target in edges:
        outgoing[source].append(target)
        incoming[target] += 1
    ready = [node for node in node_ids if incoming[node] == 0]
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in outgoing[node]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    return order, len(order) != len(node_ids)


def validate_workflow_spec(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        return {"ok": False, "schema": "workflow_validation.v1", "errors": ["spec must be object"]}
    nodes, node_errors = _normalise_nodes(spec.get("nodes"))
    node_ids = [str(node["id"]) for node in nodes]
    edges, edge_errors = _normalise_edges(spec.get("edges", []), set(node_ids))
    order, has_cycle = _toposort(node_ids, edges)
    errors = node_errors + edge_errors
    if not nodes:
        errors.append("workflow must contain at least one node")
    if has_cycle:
        errors.append("workflow graph has a cycle")
    definitions = [get_chain(str(node.get("chain", ""))) for node in nodes if node.get("ok")]
    permissions = sorted({perm for definition in definitions if definition for perm in definition.permissions})
    return {
        "ok": not errors,
        "schema": "workflow_validation.v1",
        "workflow_schema": str(spec.get("schema", "workflow.v1")),
        "nodes": nodes,
        "edges": [{"from": source, "to": target} for source, target in edges],
        "execution_order": order if not has_cycle else [],
        "permissions": permissions,
        "network_required": any(bool(definition and definition.network_allowed) for definition in definitions),
        "writes_files": any(bool(definition and definition.writes_files) for definition in definitions),
        "errors": errors,
        "warnings": [] if spec.get("version") else ["workflow version missing"],
    }
