from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class GraphNode:
    id: str
    labels: tuple[str, ...]
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PropertyGraph:
    """Small dependency-free property graph.

    This is not trying to replace Neo4j. It gives the project a stable graph
    abstraction so runtime traces can be exported to Neo4j/Memgraph/AGE later
    without rewriting agent logic.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []

    def add_node(self, node_id: str, labels: tuple[str, ...] | list[str], **properties: Any) -> "PropertyGraph":
        existing = self.nodes.get(node_id)
        if existing:
            merged_labels = tuple(sorted(set(existing.labels) | {str(label) for label in labels}))
            merged_props = {**existing.properties, **properties}
            self.nodes[node_id] = GraphNode(node_id, merged_labels, merged_props)
        else:
            self.nodes[node_id] = GraphNode(node_id, tuple(str(label) for label in labels), dict(properties))
        return self

    def add_edge(self, source: str, edge_type: str, target: str, **properties: Any) -> "PropertyGraph":
        if source not in self.nodes:
            self.add_node(source, ("Unknown",))
        if target not in self.nodes:
            self.add_node(target, ("Unknown",))
        self.edges.append(GraphEdge(source, target, edge_type, dict(properties)))
        return self

    def nodes_by_label(self, label: str) -> list[GraphNode]:
        return [node for node in self.nodes.values() if label in node.labels]

    def neighbors(self, node_id: str, *, edge_type: str | None = None) -> list[GraphNode]:
        targets = [
            edge.target
            for edge in self.edges
            if edge.source == node_id and (edge_type is None or edge.type == edge_type)
        ]
        return [self.nodes[target] for target in targets if target in self.nodes]

    def shortest_path(self, source: str, target: str, *, max_depth: int = 6) -> list[str]:
        if source not in self.nodes or target not in self.nodes:
            return []
        queue: deque[tuple[str, list[str]]] = deque([(source, [source])])
        seen = {source}
        while queue:
            current, path = queue.popleft()
            if current == target:
                return path
            if len(path) > max_depth:
                continue
            for edge in self.edges:
                if edge.source != current or edge.target in seen:
                    continue
                seen.add(edge.target)
                queue.append((edge.target, [*path, edge.target]))
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "property_graph.v1",
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [edge.to_dict() for edge in self.edges],
        }

    def to_cypher_seed(self) -> str:
        """Export a readable Cypher seed script for Neo4j/Memgraph demos."""

        lines: list[str] = []
        for node in self.nodes.values():
            labels = ":".join(_safe_token(label) for label in node.labels if label)
            props = _cypher_props({"id": node.id, **node.properties})
            lines.append(f"MERGE (n:{labels} {{id: {props['id']}}}) SET n += {{{_props_body(props)}}};")
        for idx, edge in enumerate(self.edges):
            props = _cypher_props({"edge_id": f"e{idx}", **edge.properties})
            rel = _safe_token(edge.type)
            lines.append(
                "MATCH (a {id: "
                + _quote(edge.source)
                + "}), (b {id: "
                + _quote(edge.target)
                + f"}}) MERGE (a)-[r:{rel} {{edge_id: {props['edge_id']}}}]->(b) "
                + f"SET r += {{{_props_body(props)}}};"
            )
        return "\n".join(lines) + ("\n" if lines else "")

    def to_mermaid(self, *, max_edges: int = 80) -> str:
        """Render a compact Mermaid graph for docs and interviews."""

        lines = ["flowchart TD"]
        for node in self.nodes.values():
            label = "/".join(node.labels[:2]) if node.labels else "Node"
            title = str(node.properties.get("name") or node.properties.get("title") or node.properties.get("node_id") or node.id)
            lines.append(f"    {_mermaid_id(node.id)}[\"{_mermaid_text(label + ': ' + title)}\"]")
        for edge in self.edges[: max(int(max_edges), 1)]:
            lines.append(
                f"    {_mermaid_id(edge.source)} -- \"{_mermaid_text(edge.type)}\" --> {_mermaid_id(edge.target)}"
            )
        if len(self.edges) > max(int(max_edges), 1):
            omitted_id = "_omitted_edges"
            lines.append(f"    {omitted_id}[\"... {len(self.edges) - max_edges} more edges\"]")
        return "\n".join(lines) + "\n"


def _safe_token(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in str(value))
    return cleaned or "Unknown"


def _mermaid_id(value: str) -> str:
    return "n_" + _safe_token(value)


def _mermaid_text(value: str) -> str:
    return str(value).replace('"', "'").replace("\n", " ")[:120]


def _quote(value: Any) -> str:
    text = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def _cypher_props(props: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in props.items():
        if isinstance(value, bool):
            out[_safe_token(key)] = "true" if value else "false"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out[_safe_token(key)] = str(value)
        elif isinstance(value, (list, tuple)):
            out[_safe_token(key)] = "[" + ", ".join(_quote(item) for item in value) + "]"
        else:
            out[_safe_token(key)] = _quote(value)
    return out


def _props_body(props: dict[str, str]) -> str:
    return ", ".join(f"{_safe_token(key)}: {value}" for key, value in props.items() if key != "id")


def build_demo_agent_graph(goal: str = "优化软件生产 Agent") -> PropertyGraph:
    graph = PropertyGraph()
    graph.add_node("run:demo", ("AgentRun",), goal=goal, status="planned")
    graph.add_node("node:inspect_context", ("WorkflowNode",), role="context")
    graph.add_node("node:decide", ("WorkflowNode",), role="policy")
    graph.add_node("node:execute", ("WorkflowNode",), role="actuation")
    graph.add_node("decision:route", ("Decision",), route_key="execution_strategy", choice="safe_execute")
    graph.add_node("action:k8s_sandbox_plan", ("Action",), risk="medium", permission="sandbox:plan")
    graph.add_node("evidence:research", ("Evidence",), source="local_rag", confidence=0.82)
    graph.add_node("artifact:manifest", ("Artifact",), kind="k8s_manifest")
    graph.add_node("policy:v1", ("PolicyVersion",), family="adaptive_workflow")
    graph.add_edge("run:demo", "STARTED_AT", "node:inspect_context")
    graph.add_edge("node:inspect_context", "NEXT", "node:decide")
    graph.add_edge("node:decide", "MADE", "decision:route")
    graph.add_edge("decision:route", "USED_POLICY", "policy:v1")
    graph.add_edge("decision:route", "ROUTED_TO", "node:execute")
    graph.add_edge("node:execute", "EXECUTED", "action:k8s_sandbox_plan")
    graph.add_edge("action:k8s_sandbox_plan", "CITED", "evidence:research")
    graph.add_edge("action:k8s_sandbox_plan", "PRODUCED", "artifact:manifest")
    return graph
