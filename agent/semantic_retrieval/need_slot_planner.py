from __future__ import annotations

from typing import Iterable

from agent.semantic_retrieval.schemas import NeedSlot, TaskSemanticFrame


def _unique(items: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if str(item).strip()))


def _slot(slot_id: str, slot_type: str, name: str, description: str, level: str, evidence: tuple[str, ...], terms: list[str]) -> NeedSlot:
    return NeedSlot(
        slot_id=slot_id,
        slot_type=slot_type,  # type: ignore[arg-type]
        name=name,
        description=description,
        necessity_level=level,  # type: ignore[arg-type]
        expected_evidence_types=evidence,  # type: ignore[arg-type]
        query_terms=_unique(terms),
    )


class NeedSlotPlanner:
    """Generate task-necessity slots before any retrieval happens."""

    def plan(self, frame: TaskSemanticFrame) -> list[NeedSlot]:
        slots: list[NeedSlot] = []
        patterns = set(frame.likely_patterns)
        capabilities = set(frame.required_capabilities)
        target = frame.target_module

        # Baseline slots for backend production tasks.
        if frame.product_type in {"backend_management_system", "microservice_system"}:
            slots += [
                _slot("slot_api_design", "api_design", "接口设计", "业务模块需要清晰 API 契约和错误返回。", "important", ("PatternCard", "CodeRef"), ["REST API", "controller", "DTO", "错误码"]),
                _slot("slot_database_design", "database_design", "数据库设计", "业务实体需要表结构、索引和约束。", "important", ("PatternCard", "CodeRef"), ["table design", "index", "foreign key", "schema"]),
                _slot("slot_exception_handling", "risk_case", "异常处理", "业务失败路径必须可控、可测试。", "important", ("PatternCard", "ErrorMemoryCard", "TestPoint"), ["exception", "error code", "rollback", "异常处理"]),
            ]

        if "multi_tenant_isolation" in patterns or "multi_tenant_data_isolation" in capabilities:
            slots += [
                _slot("slot_multi_tenant", "architecture_pattern", "多租户隔离", "SaaS 系统必须防止跨租户数据泄露。", "must_have", ("PatternCard", "CodeRef", "TestPoint"), ["tenant_id", "TenantContext", "multi tenant", "data isolation", "租户隔离", "cache tenant key"]),
                _slot("slot_tenant_constraint", "data_constraint", "tenant_id 数据约束", "核心业务表、查询和缓存必须携带 tenant_id。", "must_have", ("PatternCard", "CodeRef", "TestPoint"), ["tenant_id column", "query tenant filter", "MyBatis tenant interceptor", "租户字段"]),
                _slot("slot_cross_tenant_test", "test_point", "跨租户测试", "必须验证租户 A 不能访问租户 B 数据。", "must_have", ("TestPoint", "PatternCard"), ["cross tenant test", "tenant isolation test", "越权测试"]),
            ]
        if "RBAC" in patterns or "permission_control" in capabilities:
            slots.append(_slot("slot_rbac", "permission_rule", "RBAC 权限", "后台系统需要角色、权限、接口访问控制。", "must_have", ("PatternCard", "CodeRef", "TestPoint"), ["RBAC", "Role", "Permission", "permission interceptor", "权限控制"]))
        if target == "after_sales_ticket":
            slots += [
                _slot("slot_ticket_entity", "entity_model", "工单实体模型", "工单模块需要 Ticket、Comment、StatusLog 等实体。", "must_have", ("PatternCard", "CodeRef"), ["Ticket", "TicketComment", "TicketStatusLog", "工单实体"]),
                _slot("slot_ticket_state_machine", "workflow_rule", "工单状态机", "工单从创建到关闭必须限制合法状态流转。", "must_have", ("PatternCard", "CodeRef", "TestPoint"), ["ticket state machine", "status transition", "状态机", "from_status", "to_status"]),
                _slot("slot_ticket_status_log", "workflow_rule", "工单流转日志", "所有状态变更必须写入 TicketStatusLog。", "must_have", ("PatternCard", "CodeRef"), ["TicketStatusLog", "status log", "流转日志"]),
                _slot("slot_operator_audit", "architecture_pattern", "操作审计", "处理、关闭、分配等动作必须记录 OperatorLog。", "must_have", ("PatternCard", "CodeRef", "TestPoint"), ["OperatorLog", "audit log", "操作日志", "审计"]),
                _slot("slot_notification", "architecture_pattern", "消息通知", "工单创建/分配/关闭需要通知相关人员。", "important", ("PatternCard", "ModuleCard"), ["notification", "message", "工单通知"]),
                _slot("slot_status_transition_test", "test_point", "状态流转测试", "非法状态流转、关闭后处理、并发更新必须测试。", "must_have", ("TestPoint", "PatternCard"), ["invalid status transition", "concurrent update", "状态流转测试"]),
            ]
        if target == "seckill_order":
            slots += [
                _slot("slot_stock_pre_deduction", "workflow_rule", "库存预扣减", "秒杀必须先在 Redis/内存中原子预扣库存。", "must_have", ("PatternCard", "CodeRef", "TestPoint"), ["Redis stock", "decr", "库存预扣", "atomic stock"]),
                _slot("slot_redis_stock_cache", "architecture_pattern", "Redis 库存缓存", "高并发读写库存不能直接打数据库。", "must_have", ("PatternCard", "CodeRef"), ["Redis", "stock cache", "hot key", "库存缓存"]),
                _slot("slot_mq_async_order", "architecture_pattern", "消息队列异步下单", "下单链路应削峰，订单创建异步化。", "must_have", ("PatternCard", "CodeRef"), ["MQ", "RabbitMQ", "Kafka", "async order", "异步下单"]),
                _slot("slot_duplicate_order", "security_constraint", "防重复下单", "同一用户同一活动必须幂等。", "must_have", ("PatternCard", "TestPoint"), ["idempotent order", "duplicate order", "幂等", "防重复下单"]),
                _slot("slot_rate_limit", "security_constraint", "限流", "秒杀入口需要限流和熔断。", "important", ("PatternCard", "CodeRef"), ["rate limit", "token bucket", "限流"]),
                _slot("slot_order_timeout", "workflow_rule", "订单超时取消", "未支付订单需要超时取消并释放库存。", "must_have", ("PatternCard", "CodeRef"), ["order timeout", "cancel order", "订单超时"]),
                _slot("slot_stock_rollback", "workflow_rule", "库存回滚", "订单失败/取消时必须回滚库存。", "must_have", ("PatternCard", "TestPoint"), ["stock rollback", "库存回滚", "compensation"]),
                _slot("slot_high_concurrency_test", "test_point", "高并发测试", "压测库存不超卖、延迟和失败率。", "must_have", ("TestPoint", "PatternCard"), ["load test", "concurrency test", "高并发测试"]),
            ]
        if target == "auth_module":
            slots += [
                _slot("slot_user_table", "database_design", "用户表", "登录鉴权需要用户、角色、权限基础表。", "must_have", ("PatternCard", "CodeRef"), ["user table", "role table", "permission table", "用户表"]),
                _slot("slot_password_hash", "security_constraint", "密码加密", "密码必须使用安全 hash，不能明文存储。", "must_have", ("PatternCard", "CodeRef", "TestPoint"), ["BCrypt", "password hash", "salt", "密码加密"]),
                _slot("slot_login_api", "api_design", "登录接口", "登录接口需要校验、签发 token/session、结构化错误。", "must_have", ("PatternCard", "CodeRef"), ["login API", "AuthController", "登录接口"]),
                _slot("slot_jwt_session", "architecture_pattern", "JWT / Session", "需要 token 生成、校验、刷新和过期策略。", "must_have", ("PatternCard", "CodeRef"), ["JWT", "Session", "token refresh", "Token 刷新"]),
                _slot("slot_permission_interceptor", "permission_rule", "权限拦截器", "受保护接口必须统一鉴权，不能散落业务代码。", "must_have", ("PatternCard", "CodeRef", "TestPoint"), ["permission interceptor", "auth filter", "权限拦截器"]),
                _slot("slot_api_whitelist", "security_constraint", "接口白名单", "登录、健康检查、公开接口应白名单化。", "important", ("PatternCard", "TestPoint"), ["whitelist", "public API", "白名单"]),
                _slot("slot_redis_session", "architecture_pattern", "Redis 会话缓存", "分布式系统需要 Redis session/token blacklist。", "important", ("PatternCard", "CodeRef"), ["Redis session", "token blacklist", "会话缓存"]),
                _slot("slot_auth_security_test", "test_point", "鉴权安全测试", "测试密码泄露、Token 过期、越权访问等风险。", "must_have", ("TestPoint", "PatternCard"), ["privilege escalation", "expired token", "越权访问测试"]),
            ]
        return self._dedupe(slots)

    def _dedupe(self, slots: list[NeedSlot]) -> list[NeedSlot]:
        seen: set[str] = set()
        out: list[NeedSlot] = []
        for slot in slots:
            if slot.slot_id in seen:
                continue
            seen.add(slot.slot_id)
            out.append(slot)
        return out
