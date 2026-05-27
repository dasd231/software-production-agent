from __future__ import annotations

from typing import Any

from agent.graph_runtime.property_graph import GraphNode, PropertyGraph


def _incoming(graph: PropertyGraph, node_id: str, edge_type: str | None = None):
    return [edge for edge in graph.edges if edge.target == node_id and (edge_type is None or edge.type == edge_type)]


def _outgoing(graph: PropertyGraph, node_id: str, edge_type: str | None = None):
    return [edge for edge in graph.edges if edge.source == node_id and (edge_type is None or edge.type == edge_type)]


def _runs_for_decision(graph: PropertyGraph, decision_id: str) -> set[str]:
    return {edge.source for edge in _incoming(graph, decision_id, "MADE") if edge.source in graph.nodes}


def _selected_actions(graph: PropertyGraph, decision_id: str) -> list[GraphNode]:
    nodes: list[GraphNode] = []
    for edge in _outgoing(graph, decision_id, "SELECTED"):
        node = graph.nodes.get(edge.target)
        if node and "Action" in node.labels:
            nodes.append(node)
    return nodes


def review_policy_versions(
    graph: PropertyGraph,
    *,
    min_decisions: int = 5,
    max_failed_action_rate: float = 0.20,
    max_human_review_rate: float = 0.15,
) -> dict[str, Any]:
    reviews: list[dict[str, Any]] = []
    human_review_count = len(graph.nodes_by_label("HumanReview"))
    run_count = max(1, len(graph.nodes_by_label("AgentRun")))
    human_review_rate = human_review_count / run_count

    for policy in graph.nodes_by_label("PolicyVersion"):
        decision_edges = _incoming(graph, policy.id, "USED_POLICY")
        decision_ids = [edge.source for edge in decision_edges if edge.source in graph.nodes]
        run_ids: set[str] = set()
        selected_actions: list[GraphNode] = []
        for decision_id in decision_ids:
            run_ids.update(_runs_for_decision(graph, decision_id))
            selected_actions.extend(_selected_actions(graph, decision_id))

        failed_actions = [
            action
            for action in selected_actions
            if action.properties.get("ok") is False or bool(action.properties.get("error_code"))
        ]
        decision_count = len(decision_ids)
        failed_action_rate = len(failed_actions) / decision_count if decision_count else 0.0
        findings: list[dict[str, str]] = []
        if decision_count < min_decisions:
            findings.append(
                {
                    "severity": "hold",
                    "code": "low_replay_coverage",
                    "message": f"Only {decision_count} decisions use this policy; require >= {min_decisions}.",
                }
            )
        if failed_action_rate > max_failed_action_rate:
            findings.append(
                {
                    "severity": "hold",
                    "code": "high_failed_action_rate",
                    "message": f"Failed action rate {failed_action_rate:.2%} exceeds {max_failed_action_rate:.2%}.",
                }
            )
        if human_review_rate > max_human_review_rate:
            findings.append(
                {
                    "severity": "hold",
                    "code": "high_human_review_rate",
                    "message": f"Human review rate {human_review_rate:.2%} exceeds {max_human_review_rate:.2%}.",
                }
            )

        status = "canary_ready" if not findings else "hold"
        if status == "canary_ready" and decision_count >= min_decisions * 3 and failed_action_rate <= max_failed_action_rate / 2:
            status = "promotion_candidate"

        reviews.append(
            {
                "policy_node": policy.id,
                "version": str(policy.properties.get("version") or policy.id),
                "status": status,
                "decision_count": decision_count,
                "run_count": len(run_ids),
                "selected_action_count": len(selected_actions),
                "failed_action_count": len(failed_actions),
                "failed_action_rate": round(failed_action_rate, 4),
                "human_review_rate": round(human_review_rate, 4),
                "findings": findings,
            }
        )

    return {
        "schema": "graph_policy_version_review.v1",
        "min_decisions": max(1, int(min_decisions)),
        "max_failed_action_rate": max_failed_action_rate,
        "max_human_review_rate": max_human_review_rate,
        "policy_reviews": reviews,
        "summary": {
            "policy_count": len(reviews),
            "canary_ready": sum(1 for item in reviews if item["status"] == "canary_ready"),
            "promotion_candidate": sum(1 for item in reviews if item["status"] == "promotion_candidate"),
            "hold": sum(1 for item in reviews if item["status"] == "hold"),
        },
    }

