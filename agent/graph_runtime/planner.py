from __future__ import annotations

from typing import Any

from agent.graph_runtime.adapters import build_graph_store_adapter_plan
from agent.graph_runtime.property_graph import build_demo_agent_graph


def _runtime_nodes() -> list[dict[str, Any]]:
    return [
        {"id": "inspect_context", "type": "node", "state_read": ["workspace", "memory"], "state_write": ["context"]},
        {"id": "retrieve_graph_memory", "type": "node", "state_read": ["goal", "graph_db"], "state_write": ["evidence_subgraph"]},
        {"id": "plan_subgraph", "type": "node", "state_read": ["goal", "context"], "state_write": ["plan"]},
        {"id": "route_policy", "type": "conditional_node", "state_read": ["plan", "policy_version"], "state_write": ["route_choice"]},
        {"id": "execute_action", "type": "node", "state_read": ["route_choice", "supervisor"], "state_write": ["action_result"]},
        {"id": "human_interrupt", "type": "interrupt_node", "state_read": ["risk", "confidence"], "state_write": ["human_patch"]},
        {"id": "evaluate_reward", "type": "node", "state_read": ["action_result"], "state_write": ["reward", "trace"]},
        {"id": "persist_graph_memory", "type": "node", "state_read": ["trace", "evidence", "artifact"], "state_write": ["graph_db"]},
        {"id": "finalize", "type": "terminal_node", "state_read": ["reward", "artifact"], "state_write": ["answer"]},
    ]


def _runtime_edges() -> list[dict[str, Any]]:
    return [
        {"source": "__start__", "target": "inspect_context", "kind": "static"},
        {"source": "inspect_context", "target": "retrieve_graph_memory", "kind": "static"},
        {"source": "retrieve_graph_memory", "target": "plan_subgraph", "kind": "static"},
        {"source": "plan_subgraph", "target": "route_policy", "kind": "static"},
        {
            "source": "route_policy",
            "target": "execute_action",
            "kind": "conditional",
            "condition": "risk < threshold and confidence >= min_confidence",
        },
        {
            "source": "route_policy",
            "target": "human_interrupt",
            "kind": "conditional",
            "condition": "risk >= threshold or confidence < min_confidence",
        },
        {"source": "human_interrupt", "target": "execute_action", "kind": "resume_after_patch"},
        {"source": "execute_action", "target": "evaluate_reward", "kind": "static"},
        {"source": "evaluate_reward", "target": "persist_graph_memory", "kind": "static"},
        {
            "source": "evaluate_reward",
            "target": "route_policy",
            "kind": "conditional",
            "condition": "reward < repair_threshold and repair_budget remains",
        },
        {"source": "persist_graph_memory", "target": "finalize", "kind": "static"},
        {"source": "finalize", "target": "__end__", "kind": "static"},
    ]


def _graph_db_schema() -> dict[str, Any]:
    return {
        "schema": "agent_graph_db_schema.v1",
        "node_labels": [
            {
                "label": "AgentRun",
                "properties": ["run_id", "goal", "status", "started_at", "ended_at", "policy_version"],
                "indexes": ["run_id", "status", "policy_version"],
            },
            {
                "label": "WorkflowNode",
                "properties": ["node_id", "role", "subgraph", "risk_level"],
                "indexes": ["node_id", "role"],
            },
            {
                "label": "Decision",
                "properties": ["decision_id", "route_key", "choice", "confidence", "risk_level"],
                "indexes": ["route_key", "choice"],
            },
            {
                "label": "Action",
                "properties": ["action", "args_hash", "ok", "duration_ms", "error_code"],
                "indexes": ["action", "ok", "error_code"],
            },
            {
                "label": "Evidence",
                "properties": ["source", "path", "confidence", "checksum", "citation_label"],
                "indexes": ["source", "path", "checksum"],
            },
            {
                "label": "Artifact",
                "properties": ["path", "kind", "checksum", "created_by_action"],
                "indexes": ["path", "kind", "checksum"],
            },
            {
                "label": "Reward",
                "properties": ["total", "quality", "cost", "latency", "human_intervention_level"],
                "indexes": ["total", "human_intervention_level"],
            },
            {
                "label": "PolicyVersion",
                "properties": ["version", "family", "promoted_at", "canary_percent", "rollback_of"],
                "indexes": ["version", "family"],
            },
            {
                "label": "HumanReview",
                "properties": ["review_id", "level", "decision", "reason", "reviewer"],
                "indexes": ["level", "decision"],
            },
            {
                "label": "SimilarityCollapse",
                "properties": [
                    "alarm",
                    "severity",
                    "avg_pairwise_rationale_cosine",
                    "effective_rank_ratio",
                    "avg_evidence_jaccard",
                    "route_choice",
                ],
                "indexes": ["alarm", "severity"],
            },
            {
                "label": "DiversityRetention",
                "properties": ["input_count", "retained_count", "policy"],
                "indexes": ["retained_count"],
            },
        ],
        "relationships": [
            "STARTED_AT",
            "NEXT",
            "MADE",
            "ROUTED_TO",
            "EXECUTED",
            "CITED",
            "PRODUCED",
            "REWARDED_BY",
            "USED_POLICY",
            "REQUIRES_REVIEW",
            "PATCHED_STATE",
            "SIMILAR_FAILURE",
            "DETECTED",
            "HAS_QUALITY_RISK",
            "MITIGATED_BY",
            "CONTROLS_DIVERSITY",
        ],
        "constraints": [
            "AgentRun.run_id is unique",
            "PolicyVersion.version is unique",
            "Artifact.checksum + path identifies immutable output",
            "Evidence checksum is stored before model synthesis",
        ],
    }


def _second_modification_points() -> list[dict[str, str]]:
    return [
        {
            "name": "GraphState schema hardening",
            "idea": "LangGraph State is extended with typed evidence_subgraph, policy_version, risk, reward and graph_checkpoint pointers.",
        },
        {
            "name": "Graph database checkpointer",
            "idea": "checkpoint is not only JSON state; every node/edge execution is persisted as property graph lineage.",
        },
        {
            "name": "Conditional edge optimizer",
            "idea": "conditional edges are parameterized by route policy, optimized from Reward/Decision/Action subgraphs.",
        },
        {
            "name": "Human interrupt as graph patch",
            "idea": "human review creates HumanReview node and PATCHED_STATE relation, so intervention is measurable.",
        },
        {
            "name": "Subgraph contracts",
            "idea": "research, coding, sandbox, training and PV slicing become subgraphs with explicit input/output schemas.",
        },
        {
            "name": "Replay / canary / rollback",
            "idea": "PolicyVersion nodes connect to historical runs; replay coverage decides whether a route policy canary is safe.",
        },
        {
            "name": "Graph-RAG for Agent memory",
            "idea": "before planning, retrieve similar failed/successful subgraphs instead of plain text memory only.",
        },
        {
            "name": "Similarity-collapse control edge",
            "idea": "multi-agent rationale/evidence collapse is stored as SimilarityCollapse nodes and can route workflow to rewind_blind_fanout.",
        },
    ]


def _query_catalog() -> list[dict[str, str]]:
    return [
        {
            "question": "为什么这次选择 safe_execute 而不是 fast_execute？",
            "graph_pattern": "(run)-[:MADE]->(decision)-[:USED_POLICY]->(policy), (decision)-[:ROUTED_TO]->(node)",
        },
        {
            "question": "最终产物引用了哪些证据？",
            "graph_pattern": "(action)-[:PRODUCED]->(artifact)<-[:PRODUCED]-(), (action)-[:CITED]->(evidence)",
        },
        {
            "question": "哪类失败反复发生？",
            "graph_pattern": "(a:Action {ok:false})-[:REWARDED_BY]->(r:Reward), (a)-[:SIMILAR_FAILURE]->(b)",
        },
        {
            "question": "哪个策略版本导致了低分路由？",
            "graph_pattern": "(policy)<-[:USED_POLICY]-(decision)-[:ROUTED_TO]->(node), (decision)<-[:MADE]-(run)",
        },
        {
            "question": "人工介入是否真的降低了风险？",
            "graph_pattern": "(review:HumanReview)-[:PATCHED_STATE]->(run)-[:REWARDED_BY]->(reward)",
        },
        {
            "question": "哪些运行触发了多智能体相似性塌缩并如何恢复？",
            "graph_pattern": "(run)-[:HAS_QUALITY_RISK]->(risk:SimilarityCollapse)-[:MITIGATED_BY]->(retention:DiversityRetention)",
        },
    ]


def build_graph_runtime_plan(goal: str = "软件生产 Agent 图运行时二改", *, include_cypher: bool = True) -> dict[str, Any]:
    demo_graph = build_demo_agent_graph(goal)
    return {
        "schema": "graph_runtime_plan.v1",
        "positioning": "LangGraph-like second modification + graph database memory/control plane",
        "goal": goal,
        "why_it_matters": [
            "LangGraph gives graph execution; this project adds optimization, evidence lineage and graph-memory retrieval.",
            "Graph database makes Agent decisions explainable: action, evidence, artifact, reward and policy become queryable.",
            "二改重点不是会调用 LangGraph，而是把它变成可观测、可回放、可学习、可治理的生产运行时。",
        ],
        "langgraph_second_modifications": _second_modification_points(),
        "runtime_graph": {
            "nodes": _runtime_nodes(),
            "edges": _runtime_edges(),
            "interrupt_policy": {
                "triggers": ["low confidence", "high risk action", "missing evidence", "policy canary uncertainty"],
                "resume_contract": "human patch creates HumanReview node and resumes from the interrupted node",
            },
            "checkpoint_policy": {
                "state_checkpoint": "JSON state snapshot per node",
                "graph_checkpoint": "property graph lineage per node/edge/action/evidence/reward",
            },
        },
        "graph_db_schema": _graph_db_schema(),
        "graph_store_adapters": build_graph_store_adapter_plan(),
        "graph_query_catalog": _query_catalog(),
        "demo_property_graph": demo_graph.to_dict(),
        "cypher_seed": demo_graph.to_cypher_seed() if include_cypher else "",
        "integration_plan": [
            "Keep agent.workflow as local graph runtime for tests and deterministic demos.",
            "Add graph_db adapter interface: in-memory now, Neo4j/Memgraph later.",
            "Persist .agent_events.jsonl into property graph nodes and relationships.",
            "Use graph queries as Graph-RAG memory before plan_subgraph.",
            "Promote route policies only when replay coverage and graph risk checks pass.",
        ],
        "interview_pitch": [
            "我不是简单写 LangGraph demo，而是把 Agent loop 改造成图运行时。",
            "二改点在于：checkpoint 不只是状态快照，还写入图数据库 lineage。",
            "每个决策都能追到证据、产物、奖励、策略版本和人工介入。",
            "图数据库不是摆设，它服务 Graph-RAG、失败模式挖掘、policy replay/canary 和论文指标。",
        ],
    }
