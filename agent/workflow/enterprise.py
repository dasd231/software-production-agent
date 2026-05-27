"""Enterprise workflow compiler for LangGraph-like second modifications.

The project already has a lightweight graph runtime.  This module adds the
missing enterprise control plane: it turns a Dify/YAML/business workflow shape
into an auditable contract with state schema, node runtime guarantees, route
policy expectations, human gates, graph-memory projection and delivery stages.

The goal is intentionally practical: make "LangGraph 二改" inspectable in code,
not only in interview prose.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from agent.graph_runtime.property_graph import PropertyGraph
from agent.graph_runtime.graph_rag import graph_rag_query

SCHEMA_VERSION = "enterprise_workflow_contract.v1"

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

SIDE_EFFECT_KEYWORDS = (
    "mes",
    "erp",
    "lims",
    "inventory",
    "stock",
    "order",
    "workorder",
    "webhook",
    "payment",
    "deploy",
    "write",
    "delete",
    "email",
    "external",
    "adapter",
    "submit",
    "commit",
)
EVIDENCE_KEYWORDS = ("rag", "search", "evidence", "sop", "paper", "patent", "history", "graph", "retrieval")
SAFETY_KEYWORDS = ("safety", "risk", "approval", "human", "critic", "review", "bio", "compliance")
GPU_KEYWORDS = ("model", "llm", "vllm", "embedding", "rerank", "train", "distill")
STORAGE_KEYWORDS = ("rag", "graph", "pv", "vector", "history", "artifact", "audit")
NETWORK_KEYWORDS = ("web", "external", "paper", "patent", "mes", "erp", "lims", "webhook")


@dataclass(frozen=True, slots=True)
class NormalizedNode:
    id: str
    kind: str
    title: str
    raw: dict[str, Any]


def import_dify_workflow(dify_export: dict[str, Any], *, name: str = "dify-imported-workflow") -> dict[str, Any]:
    """Convert a Dify-like workflow export into the compiler's neutral spec.

    Dify exports have changed shape across versions and deployments.  This
    importer intentionally accepts a broad graph shape:

    - ``{"graph": {"nodes": [...], "edges": [...]}}``
    - ``{"workflow": {"graph": ...}}``
    - ``{"nodes": [...], "edges": [...]}``

    Nodes may carry metadata in ``data``. Edges may use ``from/to`` or
    ``source/target``. Unknown node types are preserved as-is instead of
    silently dropped.
    """

    if not isinstance(dify_export, dict):
        raise TypeError("dify_export must be a dict")
    root = dify_export
    workflow = root.get("workflow")
    if isinstance(workflow, dict):
        root = workflow
    graph = root.get("graph") if isinstance(root.get("graph"), dict) else root
    raw_nodes = graph.get("nodes", []) if isinstance(graph, dict) else []
    raw_edges = graph.get("edges", []) if isinstance(graph, dict) else []

    nodes: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_nodes if isinstance(raw_nodes, list) else []):
        if not isinstance(raw, dict):
            node_id = str(raw or f"node_{index}")
            nodes.append({"id": node_id, "kind": "workflow_node", "title": node_id})
            continue
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        node_id = str(raw.get("id") or data.get("id") or data.get("title") or f"node_{index}")
        raw_type = str(
            data.get("type")
            or data.get("node_type")
            or raw.get("type")
            or raw.get("kind")
            or data.get("provider_type")
            or "workflow_node"
        )
        kind = _map_dify_node_kind(raw_type, data)
        title = str(data.get("title") or data.get("name") or raw.get("title") or node_id)
        node = {
            "id": node_id,
            "kind": kind,
            "title": title,
            "source": "dify",
            "dify_type": raw_type,
        }
        if kind in {"rag", "graph_rag", "llm_protocol"}:
            node["evidence"] = True
        if kind in {"human_review", "safety"}:
            node["human_gate"] = True
        if kind in {"external_adapter", "mes_erp_adapter"}:
            node["side_effect"] = True
            node["risk"] = "high"
        if kind == "safety":
            node["risk"] = "critical"
        nodes.append(node)

    edges: list[dict[str, str]] = []
    for raw in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("from") or raw.get("source") or raw.get("sourceNodeId") or "").strip()
        target = str(raw.get("to") or raw.get("target") or raw.get("targetNodeId") or "").strip()
        if not source or not target:
            continue
        route = str(
            raw.get("route")
            or raw.get("condition")
            or raw.get("sourceHandle")
            or raw.get("source_handle")
            or raw.get("branch")
            or "default"
        )
        edges.append({"from": source, "to": target, "route": route})

    return {
        "schema": "enterprise_workflow_input.v1",
        "name": str(root.get("name") or root.get("app_name") or dify_export.get("name") or name),
        "goal": str(root.get("description") or root.get("goal") or dify_export.get("description") or name),
        "nodes": nodes,
        "edges": edges,
        "source": "dify",
    }


def default_bioying_research_workflow(goal: str = "抗体表达实验助手") -> dict[str, Any]:
    """Return a realistic default workflow for interview/demo usage."""

    return {
        "schema": "enterprise_workflow_input.v1",
        "name": "bioying-research-agentos",
        "goal": goal,
        "nodes": [
            {"id": "intent_parser", "kind": "intent", "title": "解析抗体/宿主/表达系统约束"},
            {"id": "evidence_planner", "kind": "planner", "title": "规划 SOP/历史实验/文献/库存证据"},
            {"id": "sop_rag", "kind": "rag", "title": "检索内部 SOP 与历史批次", "evidence": True},
            {"id": "graph_rag", "kind": "graph_rag", "title": "检索抗体-宿主-条件-结果经验图", "evidence": True},
            {"id": "collapse_guard", "kind": "collapse_guard", "title": "检测证据同质化与多 Agent 复读"},
            {"id": "protocol_builder", "kind": "llm_protocol", "title": "生成实验方案草案", "evidence": True},
            {"id": "rule_compiler", "kind": "rule_compiler", "title": "规则编译为状态机/API/权限矩阵"},
            {"id": "safety_critic", "kind": "safety", "title": "生物安全/危险试剂/合规审查", "risk": "critical"},
            {"id": "human_review", "kind": "human_review", "title": "研究员/PI 审批与状态补丁", "human_gate": True},
            {
                "id": "mes_erp_adapter",
                "kind": "mes_erp_adapter",
                "title": "库存检查与 MES 工单生成",
                "side_effect": True,
                "risk": "high",
            },
            {"id": "audit_feedback", "kind": "audit", "title": "审计入图与实验结果回写"},
        ],
        "edges": [
            {"from": "intent_parser", "to": "evidence_planner"},
            {"from": "evidence_planner", "to": "sop_rag"},
            {"from": "evidence_planner", "to": "graph_rag"},
            {"from": "sop_rag", "to": "collapse_guard"},
            {"from": "graph_rag", "to": "collapse_guard"},
            {"from": "collapse_guard", "to": "protocol_builder", "route": "diverse_evidence_ok"},
            {"from": "collapse_guard", "to": "evidence_planner", "route": "collapse_alarm_rewind"},
            {"from": "protocol_builder", "to": "rule_compiler"},
            {"from": "rule_compiler", "to": "safety_critic"},
            {"from": "safety_critic", "to": "human_review", "route": "requires_approval"},
            {"from": "human_review", "to": "mes_erp_adapter", "route": "approved"},
            {"from": "mes_erp_adapter", "to": "audit_feedback"},
        ],
    }


def _map_dify_node_kind(raw_type: str, data: dict[str, Any]) -> str:
    text = " ".join([raw_type, str(data.get("title", "")), str(data.get("desc", ""))]).lower()
    text = text.replace("-", "_")
    if any(token in text for token in ("knowledge", "retrieval", "rag", "dataset")):
        return "rag"
    if "graph" in text and "rag" in text:
        return "graph_rag"
    if any(token in text for token in ("question_classifier", "classifier", "intent", "start")):
        return "intent"
    if any(token in text for token in ("if_else", "router", "condition", "branch")):
        return "router"
    if any(token in text for token in ("human", "approval", "review")):
        return "human_review"
    if any(token in text for token in ("safety", "critic", "compliance")):
        return "safety"
    if any(token in text for token in ("http", "tool", "api", "external", "webhook")):
        return "external_adapter"
    if any(token in text for token in ("mes", "erp", "lims", "inventory", "workorder")):
        return "mes_erp_adapter"
    if any(token in text for token in ("llm", "agent", "protocol", "answer", "generate")):
        return "llm_protocol"
    return raw_type or "workflow_node"


def _coerce_workflow_input(spec: dict[str, Any] | None, goal: str) -> dict[str, Any]:
    if not spec:
        return default_bioying_research_workflow(goal)
    # Dify-like exports often wrap graph under workflow/graph or store node
    # metadata in "data". Importing them first gives the enterprise compiler
    # stable node kinds without binding to a specific Dify version.
    nodes = spec.get("nodes")
    looks_like_dify = bool(spec.get("graph") or spec.get("workflow")) or (
        isinstance(nodes, list) and any(isinstance(node, dict) and isinstance(node.get("data"), dict) for node in nodes)
    )
    if looks_like_dify:
        return import_dify_workflow(spec, name=goal)
    return dict(spec)


def _text_blob(node: NormalizedNode | dict[str, Any]) -> str:
    if isinstance(node, NormalizedNode):
        raw = node.raw
        parts = [node.id, node.kind, node.title]
    else:
        raw = node
        parts = []
    for key in ("id", "kind", "type", "role", "title", "name", "chain", "action", "tool"):
        value = raw.get(key)
        if value is not None:
            parts.append(str(value))
    return " ".join(parts).lower()


def _node_id(raw: Any, index: int) -> str:
    if isinstance(raw, str):
        return raw.strip() or f"node_{index}"
    if isinstance(raw, dict):
        value = raw.get("id") or raw.get("name") or raw.get("node") or raw.get("chain") or raw.get("action")
        return str(value or f"node_{index}").strip()
    return f"node_{index}"


def _node_kind(raw: Any) -> str:
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, dict):
        value = raw.get("kind") or raw.get("type") or raw.get("role") or raw.get("chain") or raw.get("action")
        return str(value or "workflow_node").strip()
    return "workflow_node"


def _normalize_nodes(raw_nodes: Any) -> tuple[list[NormalizedNode], list[str]]:
    errors: list[str] = []
    if not isinstance(raw_nodes, list):
        return [], ["nodes must be an array"]
    nodes: list[NormalizedNode] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, (dict, str)):
            errors.append(f"nodes[{index}] must be object or string")
            continue
        node_id = _node_id(raw, index)
        if not node_id:
            errors.append(f"nodes[{index}] missing id")
            continue
        if node_id in seen:
            errors.append(f"duplicate node id: {node_id}")
            continue
        seen.add(node_id)
        raw_dict = dict(raw) if isinstance(raw, dict) else {"id": node_id, "kind": raw}
        title = str(raw_dict.get("title") or raw_dict.get("description") or node_id)
        nodes.append(NormalizedNode(id=node_id, kind=_node_kind(raw), title=title, raw=raw_dict))
    return nodes, errors


def _normalize_edges(raw_edges: Any, node_ids: list[str]) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    node_set = set(node_ids)
    if raw_edges in (None, ""):
        return [{"from": a, "to": b, "route": "default"} for a, b in zip(node_ids, node_ids[1:])], errors
    if not isinstance(raw_edges, list):
        return [], ["edges must be an array"]

    edges: list[dict[str, str]] = []
    for index, raw in enumerate(raw_edges):
        route = "default"
        if isinstance(raw, dict):
            source = str(raw.get("from") or raw.get("source") or "").strip()
            target = str(raw.get("to") or raw.get("target") or "").strip()
            route = str(raw.get("route") or raw.get("condition") or "default").strip() or "default"
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            source = str(raw[0]).strip()
            target = str(raw[1]).strip()
            if len(raw) >= 3:
                route = str(raw[2] or "default").strip() or "default"
        else:
            errors.append(f"edges[{index}] must be object or [from,to]")
            continue
        if source not in node_set:
            errors.append(f"edge source not found: {source}")
        if target not in node_set:
            errors.append(f"edge target not found: {target}")
        if source in node_set and target in node_set:
            edges.append({"from": source, "to": target, "route": route})
    return edges, errors


def _toposort(node_ids: list[str], edges: list[dict[str, str]]) -> tuple[list[str], bool]:
    incoming = {node_id: 0 for node_id in node_ids}
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source, target = edge["from"], edge["to"]
        outgoing[source].append(target)
        incoming[target] += 1
    ready = deque([node_id for node_id in node_ids if incoming[node_id] == 0])
    order: list[str] = []
    while ready:
        node_id = ready.popleft()
        order.append(node_id)
        for target in outgoing[node_id]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    return order, len(order) != len(node_ids)


def _has_path(edges: list[dict[str, str]], source: str, target: str) -> bool:
    outgoing: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        outgoing[edge["from"]].append(edge["to"])
    visited: set[str] = set()
    q = deque([source])
    while q:
        current = q.popleft()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        q.extend(outgoing.get(current, []))
    return False


def _has_controlled_loop(edges: list[dict[str, str]]) -> bool:
    loop_markers = ("rewind", "retry", "repair", "loop", "collapse_alarm")
    return any(any(marker in str(edge.get("route", "")).lower() for marker in loop_markers) for edge in edges)


def _infer_side_effect(node: NormalizedNode) -> bool:
    if isinstance(node.raw.get("side_effect"), bool):
        return bool(node.raw["side_effect"])
    blob = _text_blob(node)
    return any(keyword in blob for keyword in SIDE_EFFECT_KEYWORDS)


def _infer_evidence_required(node: NormalizedNode) -> bool:
    if isinstance(node.raw.get("evidence"), bool):
        return bool(node.raw["evidence"])
    blob = _text_blob(node)
    return any(keyword in blob for keyword in EVIDENCE_KEYWORDS) or "protocol" in blob


def _infer_human_gate(node: NormalizedNode, risk: str, side_effect: bool) -> bool:
    if isinstance(node.raw.get("human_gate"), bool):
        return bool(node.raw["human_gate"])
    blob = _text_blob(node)
    return "human" in blob or "approval" in blob or risk in {"high", "critical"} or side_effect


def _infer_risk(node: NormalizedNode) -> str:
    raw_risk = str(node.raw.get("risk") or "").lower().strip()
    if raw_risk in RISK_ORDER:
        return raw_risk
    blob = _text_blob(node)
    if any(keyword in blob for keyword in ("delete", "payment", "biohazard", "danger", "safety", "compliance")):
        return "critical"
    if _infer_side_effect(node) or any(keyword in blob for keyword in ("mes", "erp", "lims", "deploy", "inventory")):
        return "high"
    if any(keyword in blob for keyword in EVIDENCE_KEYWORDS + GPU_KEYWORDS + NETWORK_KEYWORDS):
        return "medium"
    return "low"


def _infer_permissions(node: NormalizedNode, *, side_effect: bool) -> list[str]:
    raw = node.raw.get("permissions")
    if isinstance(raw, list):
        return sorted({str(item) for item in raw if str(item).strip()})
    blob = _text_blob(node)
    perms = {"workflow:run"}
    if any(keyword in blob for keyword in EVIDENCE_KEYWORDS):
        perms.add("evidence:read")
    if "graph" in blob:
        perms.add("graph:read")
    if any(keyword in blob for keyword in NETWORK_KEYWORDS):
        perms.add("network:read")
    if side_effect:
        perms.add("tool:write")
    if any(keyword in blob for keyword in ("mes", "erp", "lims")):
        perms.add("enterprise_system:write")
    if any(keyword in blob for keyword in SAFETY_KEYWORDS):
        perms.add("human:review")
    return sorted(perms)


def _resource_class(node: NormalizedNode) -> str:
    blob = _text_blob(node)
    if any(keyword in blob for keyword in GPU_KEYWORDS):
        return "gpu_or_model_gateway"
    if any(keyword in blob for keyword in STORAGE_KEYWORDS):
        return "storage_and_index_io"
    if any(keyword in blob for keyword in NETWORK_KEYWORDS):
        return "network_io"
    return "cpu_control_plane"


def _retry_policy(risk: str, side_effect: bool) -> dict[str, Any]:
    if side_effect:
        return {"max_attempts": 1, "backoff": "manual_or_outbox_replay", "reason": "side effects must be idempotent"}
    if risk in {"high", "critical"}:
        return {"max_attempts": 2, "backoff": "exponential_jitter", "reason": "high risk requires bounded retry"}
    return {"max_attempts": 3, "backoff": "exponential_jitter", "reason": "safe automatic retry"}


def _timeout_s(node: NormalizedNode, risk: str) -> int:
    blob = _text_blob(node)
    if any(keyword in blob for keyword in ("rag", "graph", "search")):
        return 120
    if any(keyword in blob for keyword in GPU_KEYWORDS):
        return 300
    if risk in {"high", "critical"}:
        return 90
    return 60


def _node_contract(node: NormalizedNode) -> dict[str, Any]:
    risk = _infer_risk(node)
    side_effect = _infer_side_effect(node)
    evidence_required = _infer_evidence_required(node)
    human_interrupt = _infer_human_gate(node, risk, side_effect)
    permissions = _infer_permissions(node, side_effect=side_effect)
    node_id = node.id
    return {
        "id": node_id,
        "kind": node.kind,
        "title": node.title,
        "risk_level": risk,
        "resource_class": _resource_class(node),
        "permissions": permissions,
        "timeout_s": _timeout_s(node, risk),
        "retry_policy": _retry_policy(risk, side_effect),
        "checkpoint_policy": "before_and_after_node" if risk in {"high", "critical"} or side_effect else "after_node",
        "idempotency_key": f"{{run_id}}:{node_id}:{{input_hash}}" if side_effect else "optional_for_read_only_node",
        "side_effect_guard": {
            "enabled": side_effect,
            "requires_outbox": side_effect,
            "requires_deduplication": side_effect,
            "rollback_strategy": "compensating_action_or_manual_review" if side_effect else "not_required",
        },
        "evidence_contract": {
            "required": evidence_required,
            "min_citations": 2 if evidence_required else 0,
            "reject_uncited_answer": evidence_required,
            "evidence_budget_tokens": 2400 if evidence_required else 0,
        },
        "human_interrupt": {
            "required": human_interrupt,
            "reason": "high_risk_or_side_effect" if human_interrupt else "not_required",
            "patchable_fields": ["risk_level", "selected_protocol", "tool_permissions", "approval_status"]
            if human_interrupt
            else [],
        },
        "audit_event": {
            "event_type": f"workflow.node.{node_id}",
            "required_fields": ["run_id", "tenant_id", "node_id", "status", "latency_ms", "evidence_refs", "policy_version"],
        },
    }


def _state_schema(domain: str) -> dict[str, Any]:
    return {
        "schema": "enterprise_state_schema.v1",
        "domain": domain,
        "required_fields": [
            "run_id",
            "tenant_id",
            "user_id",
            "goal",
            "current_node",
            "risk_level",
            "evidence_budget",
            "tool_permissions",
            "human_review_status",
            "audit_refs",
            "cost_budget",
        ],
        "domain_fields": [
            "antibody_target",
            "host_cell",
            "expression_system",
            "protocol_version",
            "safety_constraints",
            "mes_workorder_id",
        ]
        if "bio" in domain.lower() or "research" in domain.lower()
        else [],
        "migration_policy": "schema_versioned_state_with_backward_compatible_defaults",
    }


def _langgraph_second_modifications() -> list[dict[str, str]]:
    return [
        {"layer": "State Schema", "modification": "add tenant/risk/evidence/tool/human-review fields", "why": "state becomes an enterprise contract"},
        {"layer": "Node Runtime", "modification": "timeout/retry/idempotency/side-effect guard", "why": "external tools and MES/ERP calls must be bounded"},
        {"layer": "Edge Policy", "modification": "risk/evidence/collapse-aware routing", "why": "route by quality and safety, not static prompt order"},
        {"layer": "Checkpoint", "modification": "checkpoint before side effects and human interrupts", "why": "long workflows need replay and recovery"},
        {"layer": "Event Ledger", "modification": "decision/action/evidence/reward/human review events", "why": "auditable graph memory"},
        {"layer": "Ops Runtime", "modification": "queue lease/DLQ/Prometheus/K8s sandbox", "why": "production-grade long-task reliability"},
    ]


def _graph_memory_projection() -> dict[str, Any]:
    return {
        "node_labels": [
            "AgentRun",
            "WorkflowNode",
            "Decision",
            "Evidence",
            "HumanReview",
            "SideEffect",
            "PolicyVersion",
            "ExperimentResult",
            "SimilarityCollapse",
        ],
        "edge_types": [
            "EXECUTED",
            "CITED",
            "APPROVED_BY",
            "PATCHED_STATE",
            "TRIGGERED_SIDE_EFFECT",
            "USED_POLICY",
            "OBSERVED_RESULT",
            "DETECTED_COLLAPSE",
        ],
        "graph_rag_queries": [
            "Find similar workflows that failed after a side-effect node.",
            "Find protocols with approved human review and high downstream reward.",
            "Find evidence sets that triggered similarity collapse alarms.",
        ],
    }


def enterprise_contract_to_property_graph(contract: dict[str, Any]) -> PropertyGraph:
    """Project a compiled workflow contract into the graph runtime model."""

    graph = PropertyGraph()
    workflow = contract.get("workflow") if isinstance(contract.get("workflow"), dict) else {}
    workflow_name = str(workflow.get("name") or "enterprise_workflow")
    workflow_id = f"workflow:{workflow_name}"
    graph.add_node(
        workflow_id,
        ("EnterpriseWorkflow", "AgentRunTemplate"),
        name=workflow_name,
        goal=str(workflow.get("goal", "")),
        domain=str(workflow.get("domain", "")),
        readiness=str(contract.get("assessment", {}).get("readiness", "")) if isinstance(contract.get("assessment"), dict) else "",
        score=contract.get("assessment", {}).get("score") if isinstance(contract.get("assessment"), dict) else None,
    )

    state_id = f"{workflow_id}:state_schema"
    graph.add_node(state_id, ("StateSchema",), schema=str(contract.get("state_schema", {}).get("schema", "")))
    graph.add_edge(workflow_id, "HAS_STATE_SCHEMA", state_id)

    nodes = contract.get("nodes") if isinstance(contract.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", ""))
        if not node_id:
            continue
        graph_node_id = f"workflow_node:{workflow_name}:{node_id}"
        labels = ["WorkflowNode"]
        risk = str(node.get("risk_level", "low"))
        if risk in {"high", "critical"}:
            labels.append("HighRiskNode")
        if node.get("side_effect_guard", {}).get("enabled") if isinstance(node.get("side_effect_guard"), dict) else False:
            labels.append("SideEffectNode")
        if node.get("human_interrupt", {}).get("required") if isinstance(node.get("human_interrupt"), dict) else False:
            labels.append("HumanInterruptNode")
        if node.get("evidence_contract", {}).get("required") if isinstance(node.get("evidence_contract"), dict) else False:
            labels.append("EvidenceRequiredNode")
        graph.add_node(
            graph_node_id,
            tuple(labels),
            workflow_node_id=node_id,
            kind=str(node.get("kind", "")),
            title=str(node.get("title", "")),
            risk_level=risk,
            timeout_s=node.get("timeout_s"),
            resource_class=str(node.get("resource_class", "")),
            permissions=node.get("permissions", []),
        )
        graph.add_edge(workflow_id, "HAS_NODE", graph_node_id)

        audit_id = f"audit_contract:{workflow_name}:{node_id}"
        graph.add_node(audit_id, ("AuditContract",), event_type=str(node.get("audit_event", {}).get("event_type", "")))
        graph.add_edge(graph_node_id, "EMITS_AUDIT", audit_id)

    for edge in contract.get("edges", []) if isinstance(contract.get("edges"), list) else []:
        if not isinstance(edge, dict):
            continue
        source = f"workflow_node:{workflow_name}:{edge.get('from')}"
        target = f"workflow_node:{workflow_name}:{edge.get('to')}"
        if source in graph.nodes and target in graph.nodes:
            graph.add_edge(source, "ROUTES_TO", target, route=str(edge.get("route", "default")))

    release_gates = contract.get("release_gates") if isinstance(contract.get("release_gates"), list) else []
    for index, gate in enumerate(release_gates):
        gate_id = f"release_gate:{workflow_name}:{index}"
        graph.add_node(gate_id, ("ReleaseGate",), description=str(gate))
        graph.add_edge(workflow_id, "REQUIRES_GATE", gate_id)

    stages = contract.get("enterprise_delivery_plan") if isinstance(contract.get("enterprise_delivery_plan"), list) else []
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        stage_id = f"delivery_stage:{workflow_name}:{stage.get('stage', index)}"
        graph.add_node(
            stage_id,
            ("DeliveryStage",),
            stage=str(stage.get("stage", "")),
            goal=str(stage.get("goal", "")),
            gate=str(stage.get("gate", "")),
        )
        graph.add_edge(workflow_id, "HAS_DELIVERY_STAGE", stage_id, order=index)

    findings = (
        contract.get("assessment", {}).get("findings", [])
        if isinstance(contract.get("assessment"), dict)
        else []
    )
    for index, finding in enumerate(findings if isinstance(findings, list) else []):
        if not isinstance(finding, dict):
            continue
        finding_id = f"finding:{workflow_name}:{index}"
        graph.add_node(
            finding_id,
            ("WorkflowFinding",),
            severity=str(finding.get("severity", "")),
            code=str(finding.get("code", "")),
            message=str(finding.get("message", "")),
        )
        graph.add_edge(workflow_id, "HAS_FINDING", finding_id)

    return graph


def query_enterprise_workflow_contract(
    contract: dict[str, Any],
    query: str,
    *,
    top_k: int = 5,
    neighbor_budget: int = 12,
) -> dict[str, Any]:
    """Run governance-oriented Graph-RAG over a compiled workflow contract."""

    graph = enterprise_contract_to_property_graph(contract)
    rag = graph_rag_query(graph, query, top_k=top_k, neighbor_budget=neighbor_budget)
    query_lower = query.lower()
    insights: list[dict[str, Any]] = []

    nodes = contract.get("nodes") if isinstance(contract.get("nodes"), list) else []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id", ""))
        side_effect = bool(node.get("side_effect_guard", {}).get("enabled")) if isinstance(node.get("side_effect_guard"), dict) else False
        human = bool(node.get("human_interrupt", {}).get("required")) if isinstance(node.get("human_interrupt"), dict) else False
        evidence = bool(node.get("evidence_contract", {}).get("required")) if isinstance(node.get("evidence_contract"), dict) else False
        risk = str(node.get("risk_level", "low"))

        if side_effect and any(term in query_lower for term in ("side", "副作用", "mes", "erp", "幂等", "idempot")):
            insights.append(
                {
                    "kind": "side_effect_control",
                    "node_id": node_id,
                    "risk_level": risk,
                    "human_interrupt": human,
                    "idempotency_key": node.get("idempotency_key"),
                    "outbox_required": node.get("side_effect_guard", {}).get("requires_outbox")
                    if isinstance(node.get("side_effect_guard"), dict)
                    else False,
                    "status": "controlled" if human and node.get("idempotency_key") else "needs_hardening",
                }
            )
        if human and any(term in query_lower for term in ("human", "人工", "审批", "interrupt", "review")):
            insights.append(
                {
                    "kind": "human_interrupt",
                    "node_id": node_id,
                    "risk_level": risk,
                    "patchable_fields": node.get("human_interrupt", {}).get("patchable_fields", [])
                    if isinstance(node.get("human_interrupt"), dict)
                    else [],
                }
            )
        if evidence and any(term in query_lower for term in ("evidence", "证据", "rag", "引用", "citation", "protocol")):
            insights.append(
                {
                    "kind": "evidence_contract",
                    "node_id": node_id,
                    "min_citations": node.get("evidence_contract", {}).get("min_citations")
                    if isinstance(node.get("evidence_contract"), dict)
                    else 0,
                    "evidence_budget_tokens": node.get("evidence_contract", {}).get("evidence_budget_tokens")
                    if isinstance(node.get("evidence_contract"), dict)
                    else 0,
                }
            )
        if risk in {"high", "critical"} and any(term in query_lower for term in ("risk", "风险", "critical", "高风险")):
            insights.append({"kind": "risk_node", "node_id": node_id, "risk_level": risk, "title": node.get("title", "")})

    release_gate_hits = []
    if any(term in query_lower for term in ("release", "gate", "上线", "production", "pilot")):
        release_gate_hits = [str(gate) for gate in contract.get("release_gates", []) if isinstance(gate, str)]
        insights.extend({"kind": "release_gate", "gate": gate} for gate in release_gate_hits)

    assessment = contract.get("assessment") if isinstance(contract.get("assessment"), dict) else {}
    return {
        "schema": "enterprise_workflow_graph_rag.v1",
        "query": query,
        "readiness": assessment.get("readiness"),
        "score": assessment.get("score"),
        "insights": insights[: max(1, top_k * 3)],
        "graph_rag": rag,
        "cypher_templates": [
            "MATCH (n:SideEffectNode) WHERE NOT (n)--(:HumanInterruptNode) RETURN n",
            "MATCH (n:EvidenceRequiredNode) RETURN n.node_id, n.title, n.risk_level",
            "MATCH (w:EnterpriseWorkflow)-[:REQUIRES_GATE]->(g:ReleaseGate) RETURN w,g",
            "MATCH (w:EnterpriseWorkflow)-[:HAS_FINDING]->(f:WorkflowFinding) RETURN f ORDER BY f.severity",
            "MATCH (n:HighRiskNode)-[:EMITS_AUDIT]->(a:AuditContract) RETURN n,a",
        ],
    }


def _delivery_plan() -> list[dict[str, Any]]:
    return [
        {
            "stage": "0_business_discovery",
            "goal": "map real process, data, permissions and non-automatable boundaries",
            "deliverables": ["process map", "data source inventory", "risk register", "success metrics"],
            "gate": "domain owner confirms workflow and high-risk boundaries",
        },
        {
            "stage": "1_poc",
            "goal": "prove value quickly with low-risk Dify/prototype workflow",
            "deliverables": ["prototype", "20-question evaluation set", "expert review sheet"],
            "gate": "domain expert accepts usefulness, not production readiness",
        },
        {
            "stage": "2_mvp",
            "goal": "convert demo into controlled LangGraph-like runtime",
            "deliverables": ["state schema", "node contracts", "checkpoint", "human gate", "RAG eval"],
            "gate": "all high-risk nodes have audit and interrupt controls",
        },
        {
            "stage": "3_pilot",
            "goal": "connect enterprise systems in shadow mode",
            "deliverables": ["MES/ERP sandbox adapter", "task queue", "metrics", "DLQ", "RBAC"],
            "gate": "shadow traffic has no production side effects and full traceability",
        },
        {
            "stage": "4_production",
            "goal": "serve department workflow with SLO and incident playbook",
            "deliverables": ["SSO", "Prometheus/Grafana", "rollback", "cost ledger", "runbook"],
            "gate": "SLO, cost and quality thresholds are measured with full denominator",
        },
        {
            "stage": "5_platform",
            "goal": "make workflows reusable across departments",
            "deliverables": ["workflow marketplace", "rule compiler", "graph memory", "multi-tenant quotas"],
            "gate": "new workflow can be onboarded without rewriting the runtime",
        },
    ]


def _assess_contract(
    nodes: list[NormalizedNode],
    edges: list[dict[str, str]],
    contracts: list[dict[str, Any]],
    errors: list[str],
    has_uncontrolled_cycle: bool,
) -> tuple[list[dict[str, Any]], int, str]:
    findings: list[dict[str, Any]] = []
    by_id = {node.id: node for node in nodes}
    human_nodes = [contract["id"] for contract in contracts if contract["human_interrupt"]["required"]]
    evidence_nodes = [contract["id"] for contract in contracts if contract["evidence_contract"]["required"]]

    for error in errors:
        findings.append({"severity": "blocker", "code": "schema_error", "message": error})
    if has_uncontrolled_cycle:
        findings.append(
            {
                "severity": "blocker",
                "code": "cycle_detected",
                "message": "workflow graph contains a cycle without explicit loop policy",
            }
        )

    for contract in contracts:
        node_id = contract["id"]
        if contract["side_effect_guard"]["enabled"]:
            if not any(_has_path(edges, human_id, node_id) for human_id in human_nodes if human_id != node_id):
                findings.append(
                    {
                        "severity": "high",
                        "code": "side_effect_without_upstream_human_gate",
                        "node_id": node_id,
                        "message": "side-effect node should be downstream of an explicit human review node",
                    }
                )
            if contract["idempotency_key"] == "optional_for_read_only_node":
                findings.append(
                    {
                        "severity": "high",
                        "code": "missing_idempotency_key",
                        "node_id": node_id,
                        "message": "side-effect node must have deterministic idempotency key",
                    }
                )
        if "protocol" in _text_blob(by_id[node_id]) and not evidence_nodes:
            findings.append(
                {
                    "severity": "medium",
                    "code": "protocol_without_evidence_contract",
                    "node_id": node_id,
                    "message": "protocol generation must cite SOP/literature/history evidence",
                }
            )

    score = 100
    penalty = {"blocker": 35, "high": 18, "medium": 8, "low": 3}
    for finding in findings:
        score -= penalty.get(str(finding.get("severity")), 5)
    score = max(0, min(100, score))
    if any(finding["severity"] == "blocker" for finding in findings):
        readiness = "blocked"
    elif score >= 90:
        readiness = "ready_for_pilot"
    elif score >= 75:
        readiness = "needs_hardening_before_pilot"
    else:
        readiness = "prototype_only"
    return findings, score, readiness


def compile_enterprise_workflow(
    spec: dict[str, Any] | None = None,
    *,
    goal: str = "企业级多智能体工作流",
    domain: str = "bio_research",
    include_delivery_plan: bool = True,
) -> dict[str, Any]:
    """Compile a workflow spec into an enterprise runtime contract.

    The input accepts a Dify-like or YAML-like shape:

    ``{"name": "...", "nodes": [{"id": "rag", "kind": "rag"}], "edges": [{"from": "rag", "to": "review"}]}``

    If no spec is provided, a BioYing research-agent workflow is generated.
    """

    raw_spec = _coerce_workflow_input(spec, goal)
    raw_spec.setdefault("goal", goal)
    raw_spec.setdefault("name", "enterprise-agent-workflow")
    nodes, node_errors = _normalize_nodes(raw_spec.get("nodes"))
    node_ids = [node.id for node in nodes]
    edges, edge_errors = _normalize_edges(raw_spec.get("edges"), node_ids)
    execution_order, has_cycle = _toposort(node_ids, edges)
    has_uncontrolled_cycle = has_cycle and not _has_controlled_loop(edges)
    errors = node_errors + edge_errors
    contracts = [_node_contract(node) for node in nodes]
    findings, score, readiness = _assess_contract(nodes, edges, contracts, errors, has_uncontrolled_cycle)

    risk_counts: dict[str, int] = {key: 0 for key in RISK_ORDER}
    for contract in contracts:
        risk_counts[str(contract["risk_level"])] += 1

    result = {
        "schema": SCHEMA_VERSION,
        "ok": not errors and not has_uncontrolled_cycle,
        "workflow": {
            "name": str(raw_spec.get("name")),
            "goal": str(raw_spec.get("goal") or goal),
            "domain": domain,
            "source_schema": str(raw_spec.get("schema", "workflow.v1")),
        },
        "state_schema": _state_schema(domain),
        "nodes": contracts,
        "edges": edges,
        "execution_order": [] if has_uncontrolled_cycle else (execution_order or node_ids),
        "langgraph_second_modifications": _langgraph_second_modifications(),
        "graph_memory_projection": _graph_memory_projection(),
        "runtime_controls": {
            "checkpoint": "checkpoint every node; force checkpoint before human interrupt and side-effect nodes",
            "routing": "route by risk_level, evidence_quality, cost_budget, collapse_alarm and human_review_status",
            "human_interrupt": "pause graph, persist state, accept reviewed patch, then resume from checkpoint",
            "idempotency": "side-effect nodes use run_id:node_id:input_hash and outbox deduplication",
            "observability": ["run_id", "trace_id", "node_id", "route_choice", "latency_ms", "risk_level", "evidence_refs"],
        },
        "release_gates": [
            "no blocker findings",
            "all high/critical nodes have human interrupt policy",
            "all side-effect nodes have idempotency and outbox/dedup guard",
            "RAG/protocol nodes enforce citation/evidence budget",
            "Prometheus metrics and DLQ runbook exist before pilot",
        ],
        "assessment": {
            "readiness": readiness,
            "score": score,
            "controlled_loop": bool(has_cycle and not has_uncontrolled_cycle),
            "risk_counts": risk_counts,
            "finding_count": len(findings),
            "findings": findings,
        },
    }
    if include_delivery_plan:
        result["enterprise_delivery_plan"] = _delivery_plan()
    graph = enterprise_contract_to_property_graph(result)
    result["graph_projection"] = graph.to_dict()
    result["cypher_seed"] = graph.to_cypher_seed()
    result["mermaid"] = graph.to_mermaid()
    return result


__all__ = [
    "SCHEMA_VERSION",
    "compile_enterprise_workflow",
    "default_bioying_research_workflow",
    "enterprise_contract_to_property_graph",
    "import_dify_workflow",
    "query_enterprise_workflow_contract",
]
