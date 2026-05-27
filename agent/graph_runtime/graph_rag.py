from __future__ import annotations

import re
from typing import Any

from agent.graph_runtime.property_graph import GraphEdge, GraphNode, PropertyGraph


def _terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", str(text or ""))
    }


def _node_text(node: GraphNode) -> str:
    return " ".join([node.id, " ".join(node.labels), " ".join(str(v) for v in node.properties.values())]).lower()


def _score_node(query_terms: set[str], node: GraphNode) -> float:
    text = _node_text(node)
    score = sum(2.0 for term in query_terms if term in text)
    if "Action" in node.labels and any(term in {"失败", "failed", "error", "错误"} for term in query_terms):
        if node.properties.get("ok") is False or node.properties.get("error_code"):
            score += 4.0
    if "Evidence" in node.labels and any(term in {"证据", "evidence", "citation"} for term in query_terms):
        score += 3.0
    if "PolicyVersion" in node.labels and any(term in {"策略", "policy", "版本", "rollback"} for term in query_terms):
        score += 3.0
    if "HumanReview" in node.labels and any(term in {"人工", "human", "介入", "review"} for term in query_terms):
        score += 3.0
    if "SimilarityCollapse" in node.labels and any(
        term in {"collapse", "similarity", "相似", "塌缩", "同质", "diversity", "rewind"} for term in query_terms
    ):
        score += 5.0
    return score


def _incident_edges(graph: PropertyGraph, node_id: str) -> list[GraphEdge]:
    return [edge for edge in graph.edges if edge.source == node_id or edge.target == node_id]


def graph_rag_query(graph: PropertyGraph, query: str, *, top_k: int = 5, neighbor_budget: int = 12) -> dict[str, Any]:
    query_terms = _terms(query)
    scored: list[tuple[float, GraphNode]] = []
    for node in graph.nodes.values():
        score = _score_node(query_terms, node)
        if score > 0:
            scored.append((score, node))
    scored.sort(key=lambda item: (-item[0], item[1].id))
    anchors = [node for _, node in scored[: max(1, int(top_k))]]
    sub_nodes: dict[str, GraphNode] = {node.id: node for node in anchors}
    sub_edges: list[GraphEdge] = []

    for anchor in anchors:
        for edge in _incident_edges(graph, anchor.id):
            if len(sub_edges) >= max(1, int(neighbor_budget)):
                break
            sub_edges.append(edge)
            if edge.source in graph.nodes:
                sub_nodes[edge.source] = graph.nodes[edge.source]
            if edge.target in graph.nodes:
                sub_nodes[edge.target] = graph.nodes[edge.target]

    answer_hints = []
    for anchor in anchors:
        labels = "/".join(anchor.labels)
        answer_hints.append(
            {
                "node_id": anchor.id,
                "labels": list(anchor.labels),
                "score": next(score for score, node in scored if node.id == anchor.id),
                "why": f"Matched query terms in {labels} node",
                "properties": anchor.properties,
            }
        )

    return {
        "schema": "graph_rag_result.v1",
        "query": query,
        "anchor_nodes": answer_hints,
        "subgraph": {
            "nodes": [node.to_dict() for node in sub_nodes.values()],
            "edges": [edge.to_dict() for edge in sub_edges],
        },
        "query_plan": {
            "strategy": "keyword_plus_label_boost_property_graph_retrieval",
            "steps": [
                "tokenize query",
                "score nodes by label/property overlap",
                "expand one-hop incident edges around anchors",
                "return evidence subgraph for planning or explanation",
            ],
        },
        "cypher_templates": [
            "MATCH (a:Action {ok:false})-[:REWARDED_BY]->(r:Reward) RETURN a,r ORDER BY r.total ASC LIMIT 20",
            "MATCH (d:Decision)-[:USED_POLICY]->(p:PolicyVersion) RETURN d,p LIMIT 20",
            "MATCH (a:Action)-[:CITED]->(e:Evidence) RETURN a,e LIMIT 20",
            "MATCH (h:HumanReview)-[:PATCHED_STATE]->(run:AgentRun) RETURN h,run LIMIT 20",
        ],
    }
