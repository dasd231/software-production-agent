from __future__ import annotations

import json
from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.graph_runtime.adapters import CypherGraphStoreAdapter, build_graph_store_adapter_plan, render_cypher_import_bundle
from agent.graph_runtime.graph_rag import graph_rag_query
from agent.graph_runtime.ingest import agent_events_to_property_graph
from agent.graph_runtime.policy_review import review_policy_versions
from agent.recorder import build_event_row


def _sample_events() -> list[dict]:
    return [
        build_event_row("loop_start", {"run_id": "r1", "goal": "修复 run_command 失败"}, ts=1.0),
        build_event_row(
            "decision_policy",
            {
                "run_id": "r1",
                "iteration": 0,
                "decision": {
                    "strategy": "implement",
                    "selected_action": "run_command",
                    "selected_score": 0.7,
                    "reason": "need test command",
                },
            },
            ts=2.0,
        ),
        build_event_row(
            "decide",
            {"run_id": "r1", "iteration": 0, "action_summary": {"action": "run_command"}},
            ts=3.0,
        ),
        build_event_row(
            "execute",
            {
                "run_id": "r1",
                "iteration": 0,
                "result_summary": {
                    "action": "run_command",
                    "ok": False,
                    "duration_ms": 120,
                    "error_code": "TEST_FAILED",
                },
            },
            ts=4.0,
        ),
        build_event_row(
            "reward_signal",
            {
                "run_id": "r1",
                "iteration": 0,
                "reward": {"total": -0.5, "ok": False, "source": "test", "components": {"ci": -1}},
            },
            ts=5.0,
        ),
        build_event_row(
            "human_gate",
            {"run_id": "r1", "level": "L2", "decision": "patch_required", "reason": "test failed"},
            ts=6.0,
        ),
    ]


def _collapse_workflow_events() -> list[dict]:
    return [
        {
            "run_id": "wf-collapse",
            "step_index": 3,
            "node": "assess_similarity_collapse",
            "status": "ok",
            "route_key": "collapse_route",
            "route_choice": "rewind_blind_fanout",
            "score": 0.35,
            "confidence": 0.35,
            "metadata": {"message": "collapse alarm handled"},
            "similarity_collapse_assessment": {
                "schema": "similarity_collapse_assessment.v1",
                "alarm": True,
                "severity": "warning",
                "metrics": {
                    "avg_pairwise_rationale_cosine": 0.96,
                    "max_pairwise_rationale_cosine": 1.0,
                    "effective_rank": 1.0,
                    "effective_rank_ratio": 0.33,
                    "avg_evidence_jaccard": 0.9,
                },
            },
            "diversity_retention_decision": {
                "schema": "diversity_retention_decision.v1",
                "input_count": 3,
                "retained_count": 2,
                "policy": "retain messages farthest from majority rationale and evidence set",
            },
        }
    ]


def test_agent_events_to_property_graph_builds_lineage() -> None:
    graph, summary = agent_events_to_property_graph(_sample_events())

    assert summary["event_count"] == 6
    assert summary["run_count"] == 1
    assert summary["failed_actions"] == 1
    assert summary["human_reviews"] == 1
    labels = {label for node in graph.nodes.values() for label in node.labels}
    assert {"AgentRun", "Event", "Decision", "Action", "Reward", "HumanReview"} <= labels
    edge_types = {edge.type for edge in graph.edges}
    assert {"HAS_EVENT", "MADE", "SELECTED", "EXECUTED", "REWARDED_BY", "PATCHED_STATE"} <= edge_types


def test_graph_rag_returns_failure_subgraph() -> None:
    graph, _summary = agent_events_to_property_graph(_sample_events())
    result = graph_rag_query(graph, "run_command 失败 error 人工介入", top_k=4)

    assert result["anchor_nodes"]
    labels = {label for item in result["anchor_nodes"] for label in item["labels"]}
    assert "Action" in labels or "HumanReview" in labels
    assert result["subgraph"]["edges"]
    assert result["cypher_templates"]


def test_workflow_collapse_route_ingests_as_quality_risk_graph() -> None:
    graph, summary = agent_events_to_property_graph(_collapse_workflow_events())
    result = graph_rag_query(graph, "similarity collapse rewind diversity", top_k=3)

    labels = {label for node in graph.nodes.values() for label in node.labels}
    edge_types = {edge.type for edge in graph.edges}
    assert summary["collapse_alarms"] == 1
    assert summary["diversity_rewinds"] == 1
    assert {"SimilarityCollapse", "QualityRisk", "DiversityRetention", "Decision"} <= labels
    assert {"DETECTED", "HAS_QUALITY_RISK", "MITIGATED_BY", "CONTROLS_DIVERSITY"} <= edge_types
    assert any("SimilarityCollapse" in item["labels"] for item in result["anchor_nodes"])


def test_cypher_graph_store_adapter_exports_constraints_indexes_and_seed() -> None:
    graph, _summary = agent_events_to_property_graph(_sample_events())
    bundle = render_cypher_import_bundle(graph, dialect="neo4j")
    memgraph_bundle = CypherGraphStoreAdapter(dialect="memgraph").export(graph)
    adapter_plan = build_graph_store_adapter_plan()

    assert bundle["schema"] == "graph_store_import_bundle.v1"
    assert bundle["constraints"]
    assert bundle["indexes"]
    assert "MERGE" in bundle["cypher"]
    assert memgraph_bundle["dialect"] == "memgraph"
    assert any(item["name"] == "CypherGraphStoreAdapter" for item in adapter_plan["adapters"])


def test_policy_version_review_holds_low_coverage_or_failed_policy() -> None:
    graph, _summary = agent_events_to_property_graph(_sample_events())
    review = review_policy_versions(graph, min_decisions=2, max_failed_action_rate=0.1, max_human_review_rate=0.9)

    assert review["policy_reviews"]
    item = review["policy_reviews"][0]
    assert item["status"] == "hold"
    assert item["decision_count"] == 1
    codes = {finding["code"] for finding in item["findings"]}
    assert "low_replay_coverage" in codes


def test_graph_events_ingest_action_writes_graph_and_respects_permissions(tmp_path: Path) -> None:
    events_path = tmp_path / ".agent_events.jsonl"
    events_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in _sample_events()) + "\n", encoding="utf-8")

    action = parse_action(
        '{"type":"action","action":"graph_events_ingest","args":'
        '{"events_path":".agent_events.jsonl","query":"run_command failed human",'
        '"output_path":"plans/event-graph.json"}}'
    )
    direct = run_action(tmp_path, action)
    assert direct["ok"] is True
    assert direct["summary"]["event_count"] == 6
    assert direct["summary"]["graph_rag_anchor_count"] > 0
    assert direct["graph_store_import"]["constraints"]
    assert direct["policy_review"]["policy_reviews"]
    assert (tmp_path / "plans" / "event-graph.json").exists()

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
        limits=ExecutionLimits(granted_permissions=frozenset({"graph:write", "workspace:read", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"
