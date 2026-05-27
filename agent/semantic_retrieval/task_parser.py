from __future__ import annotations

import re
from typing import Iterable

from agent.semantic_retrieval.schemas import SemanticRetrievalRequest, TaskSemanticFrame


def _has(text: str, *terms: str) -> bool:
    lower = text.lower()
    return any(term.lower() in lower for term in terms)


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if str(item).strip()))


class TaskParser:
    """Rule-first parser for software-production task semantics."""

    def parse(self, request: SemanticRetrievalRequest | dict) -> TaskSemanticFrame:
        req = request if isinstance(request, SemanticRetrievalRequest) else SemanticRetrievalRequest.from_dict(request)
        raw = req.user_requirement.strip()
        text = " ".join([raw, req.project_type, req.existing_project_summary])
        entities: list[str] = []
        relations: list[str] = []
        constraints: list[str] = []
        capabilities: list[str] = []
        patterns: list[str] = []
        risks: list[str] = []

        task_type = "generate_business_module"
        domain = "general_software"
        product_type = req.project_type or "backend_management_system"
        target_module = "business_module"

        if _has(text, "saas", "租户", "tenant", "无人门店", "门店"):
            domain = "unmanned_store_saas" if _has(text, "无人", "门店", "store") else "saas"
            entities += ["Tenant", "User", "Role"]
            constraints += ["all business data must be tenant-isolated", "cross-tenant access is forbidden"]
            capabilities += ["multi_tenant_data_isolation", "permission_control"]
            patterns += ["multi_tenant_isolation", "RBAC"]
            risks += ["cross_tenant_data_leak", "cache_cross_tenant_pollution"]
        if _has(text, "工单", "ticket", "售后"):
            target_module = "after_sales_ticket"
            entities += ["Ticket", "TicketComment", "TicketStatusLog", "Customer", "OperatorLog"]
            relations += [
                "Customer creates Ticket",
                "User handles Ticket",
                "Ticket has TicketStatusLog",
                "Ticket belongs to Tenant",
            ]
            constraints += ["ticket status transitions must be auditable", "operator actions must be logged"]
            capabilities += ["state_transition", "audit_logging", "notification"]
            patterns += ["state_machine", "audit_log", "notification"]
            risks += ["invalid_status_transition", "missing_operation_log", "concurrent_ticket_update"]
        if _has(text, "秒杀", "seckill", "抢购", "高并发下单"):
            domain = "ecommerce_high_concurrency"
            product_type = "microservice_system" if product_type == "" else product_type
            target_module = "seckill_order"
            entities += ["User", "Product", "Stock", "Order", "Payment", "SeckillActivity"]
            relations += ["User creates Order", "Order reserves Stock", "SeckillActivity owns Product"]
            constraints += ["stock deduction must be atomic", "duplicate order is forbidden", "failed orders must rollback stock"]
            capabilities += ["async_processing", "idempotency", "rate_limiting", "stock_pre_deduction"]
            patterns += ["redis_stock_cache", "mq_async_order", "idempotent_order", "rate_limit", "stock_rollback"]
            risks += ["oversold_stock", "duplicate_order", "message_loss", "hot_key_breakdown", "stock_rollback_missing"]
        if _has(text, "登录", "鉴权", "认证", "jwt", "session", "auth"):
            domain = "identity_access_management" if domain == "general_software" else domain
            target_module = "auth_module"
            entities += ["User", "Role", "Permission", "Token", "Session"]
            relations += ["User owns Role", "Role grants Permission", "User obtains Token"]
            constraints += ["passwords must be hashed", "protected APIs require authentication", "public APIs need whitelist"]
            capabilities += ["authentication", "authorization", "session_management", "permission_interceptor"]
            patterns += ["password_hashing", "JWT", "RBAC", "permission_interceptor", "redis_session_cache"]
            risks += ["password_leak", "token_expiry", "privilege_escalation", "replay_attack"]
        if _has(text, "修改", "改造", "已有"):
            task_type = "modify_existing_module"
        if _has(text, "前端", "页面", "vue", "react"):
            product_type = "web_app"
            task_type = "generate_frontend_page" if task_type != "modify_existing_module" else task_type
        if _has(text, "api", "接口"):
            task_type = "generate_backend_api"

        # Generic backend-management defaults: useful but lower priority than domain rules.
        if product_type in {"backend_management_system", "microservice_system", ""}:
            capabilities += ["api_design", "database_design", "exception_handling", "test_design"]
            constraints += ["API errors must be structured", "critical operations must be testable"]
            patterns += ["layered_architecture", "structured_error_handling"]

        return TaskSemanticFrame(
            raw_requirement=raw,
            task_type=task_type,
            domain=domain,
            product_type=product_type or "backend_management_system",
            target_module=target_module,
            entities=_unique(entities),
            relations=_unique(relations),
            constraints=_unique(constraints),
            required_capabilities=_unique(capabilities),
            likely_patterns=_unique(patterns),
            risk_points=_unique(risks),
        )
