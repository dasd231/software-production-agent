from __future__ import annotations

from agent.graph_runtime import PropertyGraph, build_agent_knowledge_graph_spec, validate_property_graph_against_spec
from agent.local_training import build_training_quality_plan, evaluate_training_quality


def test_agent_knowledge_graph_spec_covers_semantic_retrieval_and_model_quality() -> None:
    spec = build_agent_knowledge_graph_spec()
    labels = set(spec["node_labels"])
    assert {"TaskSemanticFrame", "NeedSlot", "CandidateEvidence", "SemanticContextPackage"} <= labels
    assert {"ModelArtifact", "TrainingDataset", "QualityMetric"} <= labels
    assert {"SkillCard", "SkillBundle", "GuardReport"} <= labels
    assert {"HAS_SLOT", "MATCHED_EVIDENCE", "SELECTED_FOR", "TRAINED_ON", "EVALUATED_BY"} <= set(spec["edge_types"])
    assert {"USED_SKILL", "GUARDED_BY", "VALIDATED_OUTPUT"} <= set(spec["edge_types"])
    assert spec["indexes"]
    assert any("verification" in gate for gate in spec["quality_gates"])


def test_agent_knowledge_graph_validation_finds_schema_drift() -> None:
    graph = PropertyGraph()
    graph.add_node("frame:1", ("TaskSemanticFrame",), raw_requirement="做 SaaS 工单")
    graph.add_node("slot:tenant", ("NeedSlot",), slot_id="slot_multi_tenant", necessity_level="must_have")
    graph.add_node("evidence:1", ("CandidateEvidence",), source_type="pattern_card", verification_level="human_verified")
    graph.add_edge("frame:1", "HAS_SLOT", "slot:tenant")
    graph.add_edge("evidence:1", "MATCHED_EVIDENCE", "slot:tenant")
    ok = validate_property_graph_against_spec(graph)
    assert ok["ok"] is True

    graph.add_node("bad:1", ("RandomLabel",), foo="bar")
    graph.add_edge("bad:1", "RANDOM_EDGE", "frame:1")
    drift = validate_property_graph_against_spec(graph)
    assert drift["ok"] is False
    assert drift["unknown_labels"]
    assert drift["unknown_edge_types"]


def test_training_quality_plan_and_evaluation_gate_models() -> None:
    plan = build_training_quality_plan()
    targets = {item["target"] for item in plan["models"]}
    assert {"middle_model_rule_acceleration", "github_corpus_quality_evaluator"} <= targets
    assert "holdout_by_domain" in plan["dataset_quality"]["required_splits"]

    blocked = evaluate_training_quality(
        {
            "results": {
                "middle_model": {"status": "trained", "training_examples": 2, "metrics": {"accuracy": 1.0}},
                "github_evaluator": {"status": "needs_data", "training_examples": 0, "metrics": {"accuracy": 0.0}},
            }
        }
    )
    assert blocked["ok"] is False
    assert blocked["evaluations"]["middle_model"]["status"] == "blocked"
    assert blocked["evaluations"]["github_evaluator"]["status"] == "blocked"

    promotable = evaluate_training_quality(
        {
            "results": {
                "middle_model": {"status": "trained", "training_examples": 60, "metrics": {"accuracy": 0.8}},
                "github_evaluator": {"status": "trained", "training_examples": 100, "metrics": {"accuracy": 0.75}},
            }
        }
    )
    assert promotable["ok"] is True
