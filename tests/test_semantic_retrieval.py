from __future__ import annotations

from agent.graph_runtime import graph_rag_query, validate_property_graph_against_spec
from agent.semantic_retrieval import (
    SemanticRetrievalRequest,
    SemanticRetrievalService,
    semantic_context_graph_bundle,
    semantic_context_to_property_graph,
)


def _resolve(requirement: str, tech_stack: tuple[str, ...] = ("Java", "Spring Boot", "MySQL", "Redis")):
    return SemanticRetrievalService().resolve(
        SemanticRetrievalRequest(
            task_id="test_task",
            user_requirement=requirement,
            project_type="backend_management_system",
            tech_stack=tech_stack,
            existing_project_summary="已有用户、角色、门店、设备基础模块",
            max_context_items=20,
        )
    )


def _slot_names(package) -> set[str]:
    return {slot.name for slot in package.need_slots}


def _joined(package) -> str:
    return "\n".join(
        [
            package.task_summary,
            *package.constraints,
            *package.risk_warnings,
            *package.implementation_suggestions,
            *package.test_suggestions,
            *(item.get("name", "") for item in package.selected_patterns),
            *(item.get("content", "") for item in package.selected_code_refs),
        ]
    )


def test_semantic_retrieval_resolves_saas_ticket_by_need_slots_not_generic_similarity() -> None:
    package = _resolve("帮我做一个无人门店 SaaS 售后工单系统")
    slots = _slot_names(package)
    assert {"多租户隔离", "RBAC 权限", "工单实体模型", "工单状态机", "工单流转日志", "操作审计", "消息通知", "跨租户测试", "状态流转测试"} <= slots
    assert package.coverage_report is not None
    assert package.coverage_report.must_have_coverage_rate >= 0.9
    assert not package.coverage_report.has_missing_must_have

    text = _joined(package)
    assert "tenant_id" in text
    assert "TicketStatusLog" in text
    assert "OperatorLog" in text
    assert "非法状态流转" in text or "状态流转" in text
    assert "租户 A 不能查询租户 B" in text

    titles = [e.title for e in package.selected_evidence]
    assert not titles or titles[0] != "SaaS 是什么：通用介绍"
    assert any("多租户" in title for title in titles)


def test_semantic_retrieval_resolves_seckill_order_with_consistency_and_pressure_slots() -> None:
    package = _resolve("帮我做一个秒杀下单模块", tech_stack=("Java", "Spring Boot", "Redis", "RabbitMQ", "MySQL"))
    slots = _slot_names(package)
    assert {"库存预扣减", "Redis 库存缓存", "消息队列异步下单", "防重复下单", "限流", "订单超时取消", "库存回滚", "高并发测试"} <= slots
    assert package.coverage_report is not None
    assert package.coverage_report.must_have_coverage_rate >= 0.9

    text = _joined(package)
    assert "Redis" in text
    assert "MQ" in text or "RabbitMQ" in text
    assert "幂等" in text
    assert "库存回滚" in text
    assert "高并发压测" in text or "高并发测试" in text


def test_semantic_retrieval_resolves_auth_with_security_slots() -> None:
    package = _resolve("帮我做一个登录鉴权模块", tech_stack=("Java", "Spring Boot", "Redis", "MySQL"))
    slots = _slot_names(package)
    assert {"用户表", "密码加密", "登录接口", "JWT / Session", "权限拦截器", "接口白名单", "RBAC 权限", "Redis 会话缓存", "鉴权安全测试"} <= slots
    assert package.coverage_report is not None
    assert package.coverage_report.must_have_coverage_rate >= 0.9

    text = _joined(package)
    assert "BCrypt" in text
    assert "JWT" in text or "Session" in text
    assert "白名单" in text
    assert "blacklist" in text or "Redis" in text
    assert "越权" in text or "403" in text


def test_semantic_context_package_is_structured_not_chunk_list() -> None:
    package = _resolve("帮我做一个 SaaS 工单系统")
    data = package.to_dict()
    assert data["schema"] == "semantic_context_package.v1"
    assert data["task_frame"]["target_module"] == "after_sales_ticket"
    assert data["selected_patterns"]
    assert data["implementation_suggestions"]
    assert data["risk_warnings"]
    assert data["test_suggestions"]
    assert all("source_type" in item for item in data["selected_evidence"])
    assert all("verification_level" in item for item in data["selected_evidence"])


def test_semantic_context_projects_to_valid_lpg_and_graph_rag_can_query_need_slots() -> None:
    package = SemanticRetrievalService().resolve(
        SemanticRetrievalRequest(
            task_id="kg_projection",
            user_requirement="帮我做一个无人门店 SaaS 售后工单系统",
            project_type="backend_management_system",
            tech_stack=("Java", "Spring Boot", "MySQL", "Redis"),
            max_context_items=20,
        )
    )
    graph = semantic_context_to_property_graph(package)
    validation = validate_property_graph_against_spec(graph)
    assert validation["ok"] is True

    labels = {label for node in graph.nodes.values() for label in node.labels}
    assert {"TaskSemanticFrame", "NeedSlot", "CandidateEvidence", "SemanticContextPackage", "QualityMetric"} <= labels
    edge_types = {edge.type for edge in graph.edges}
    assert {"HAS_SLOT", "MATCHED_EVIDENCE", "SELECTED_FOR", "EVALUATED_BY"} <= edge_types

    result = graph_rag_query(graph, "多租户 NeedSlot 证据 tenant_id", top_k=4)
    assert result["anchor_nodes"]
    assert result["subgraph"]["edges"]

    bundle = semantic_context_graph_bundle(package)
    assert "MERGE" in bundle["cypher_seed"]
    assert "flowchart" in bundle["mermaid"]
