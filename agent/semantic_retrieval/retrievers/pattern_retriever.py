from __future__ import annotations

from collections.abc import Mapping, Sequence

from agent.semantic_retrieval.retrievers.base import BaseRetriever, evidence_from_text, lexical_score, merge_evidence
from agent.semantic_retrieval.schemas import CandidateEvidence, NeedSlot, PatternCard, TaskSemanticFrame


def _card_text(card: PatternCard) -> str:
    parts: list[str] = [
        card.name,
        card.category,
        *card.applicable_scenarios,
        card.problem,
        card.solution,
        *card.required_entities,
        *card.required_modules,
        *card.required_tables,
        *card.required_interfaces,
        *card.implementation_steps,
        *card.common_pitfalls,
        *card.test_points,
    ]
    return "\n".join(str(part) for part in parts if str(part).strip())


def builtin_pattern_cards() -> list[PatternCard]:
    """Human-curated seed pattern library for the first local MVP.

    These cards are deliberately implementation-heavy. Generic explanatory
    material is handled by vector/keyword retrievers and is penalized later.
    """
    return [
        PatternCard(
            pattern_id="pattern_multi_tenant_isolation",
            name="多租户数据隔离模式",
            category="backend_architecture",
            applicable_scenarios=("SaaS system", "multi-store management", "enterprise management platform"),
            problem="多个租户共享同一系统时，必须防止跨租户数据泄露。",
            solution="核心业务表增加 tenant_id；查询层统一注入 tenant filter；缓存 key 拼接 tenant_id；跨租户管理员操作必须审计。",
            required_entities=("Tenant", "User", "Role"),
            required_modules=("tenant_context", "permission_filter", "query_interceptor", "audit_log"),
            required_tables=("tenant", "user", "role", "tenant_scoped_business_table"),
            required_interfaces=("TenantContext.getTenantId", "TenantFilterInterceptor"),
            implementation_steps=(
                "所有租户域表设计 tenant_id NOT NULL，并建立 tenant_id + business_key 联合索引。",
                "在 Repository/MyBatis/JPA 层统一注入 tenant_id 条件，禁止业务代码手写散落过滤。",
                "Redis/cache key 统一加入 tenant_id 前缀，避免缓存串租户。",
                "跨租户管理能力走显式白名单和 OperatorLog 审计。",
            ),
            common_pitfalls=(
                "只在业务代码手动拼 tenant_id，新增查询容易遗漏。",
                "缓存 key 不区分 tenant_id 会导致租户数据污染。",
                "超级管理员跨租户查询缺少审计，事后不可追溯。",
            ),
            test_points=(
                "租户 A 不能查询租户 B 的业务数据。",
                "缓存隔离测试：同一业务 id 在不同 tenant_id 下不能互相命中。",
                "管理员跨租户操作必须留下 OperatorLog。",
            ),
            source_refs=("local_pattern_library://multi_tenant_isolation",),
            confidence=0.96,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_rbac_permission",
            name="RBAC 权限控制模式",
            category="security_architecture",
            applicable_scenarios=("backend management system", "SaaS", "enterprise platform"),
            problem="后台系统必须把用户、角色、权限、接口访问控制统一建模，避免散落 if 判断。",
            solution="User-Role-Permission 三层模型，接口通过权限注解/拦截器统一校验，越权访问统一拒绝并记录审计。",
            required_entities=("User", "Role", "Permission"),
            required_modules=("permission_interceptor", "auth_context", "operator_log"),
            required_tables=("user", "role", "permission", "user_role", "role_permission"),
            required_interfaces=("PermissionInterceptor", "AuthContext", "GET /roles", "POST /role-permissions"),
            implementation_steps=(
                "建立 user_role 与 role_permission 关系表。",
                "受保护接口走统一 PermissionInterceptor/Filter。",
                "权限缓存需要按 user_id + tenant_id 维度失效。",
            ),
            common_pitfalls=("只在 Controller 内判断角色导致规则不可复用。", "权限缓存失效不及时导致越权窗口。"),
            test_points=("无权限用户访问接口返回 403。", "角色权限变更后缓存立即失效。", "租户间角色权限不能互相污染。"),
            source_refs=("local_pattern_library://rbac",),
            confidence=0.94,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_ticket_entity_model",
            name="售后工单实体建模模式",
            category="domain_model",
            applicable_scenarios=("after-sales ticket", "service desk", "unmanned store operations"),
            problem="工单模块不是一张 Ticket 表，必须表达评论、状态历史、处理人、设备/门店归属和审计。",
            solution="以 Ticket 为聚合根，配套 TicketComment、TicketStatusLog、OperatorLog；SaaS 场景所有表带 tenant_id。",
            required_entities=("Ticket", "TicketComment", "TicketStatusLog", "Device", "Store", "Customer", "OperatorLog"),
            required_modules=("ticket_service", "status_log_service", "audit_service"),
            required_tables=("ticket", "ticket_comment", "ticket_status_log", "operator_log"),
            required_interfaces=("POST /tickets", "POST /tickets/{id}/comments", "POST /tickets/{id}/status"),
            implementation_steps=(
                "Ticket 保存当前状态、创建人、处理人、优先级、tenant_id、store_id/device_id。",
                "TicketStatusLog 保存 from_status、to_status、operator_id、reason、created_at。",
                "TicketComment 支持内部备注与客户可见评论分离。",
            ),
            common_pitfalls=("只记录当前状态，无法追踪流转历史。", "评论和状态变更混在一张表导致查询与权限复杂。"),
            test_points=("创建工单后必须有初始状态。", "状态变更后必须新增 TicketStatusLog。", "不同租户工单不可互查。"),
            source_refs=("local_pattern_library://ticket_entity_model",),
            confidence=0.93,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_ticket_state_machine_audit",
            name="工单状态机与审计模式",
            category="workflow_rule",
            applicable_scenarios=("ticket system", "approval workflow", "after-sales service"),
            problem="工单状态不能任意跳转；关闭后继续处理、并发覆盖状态都会造成业务错误。",
            solution="定义 from_status -> to_status 白名单，状态变更在事务内写 TicketStatusLog 和 OperatorLog，并使用 version 乐观锁防并发覆盖。",
            required_entities=("Ticket", "TicketStatusLog", "OperatorLog"),
            required_modules=("state_machine", "audit_log", "optimistic_lock"),
            required_tables=("ticket", "ticket_status_log", "operator_log"),
            required_interfaces=("TicketStateMachine.canTransit", "TicketService.changeStatus"),
            implementation_steps=(
                "用枚举/配置表声明 CREATED -> ASSIGNED -> PROCESSING -> RESOLVED -> CLOSED 等合法路径。",
                "状态流转必须校验 from_status 与当前状态一致。",
                "同一事务内更新 Ticket、插入 TicketStatusLog、插入 OperatorLog。",
                "并发处理使用 version 字段或 compare-and-set 更新。",
            ),
            common_pitfalls=("状态跳转规则散落在多个接口。", "关闭工单后仍允许追加处理动作。", "并发更新导致最后写覆盖。"),
            test_points=("非法状态流转必须失败。", "关闭工单后不能继续处理。", "并发处理同一工单只能成功一次。"),
            source_refs=("local_pattern_library://ticket_state_machine_audit",),
            confidence=0.95,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_ticket_notification",
            name="工单消息通知模式",
            category="integration_pattern",
            applicable_scenarios=("ticket assignment", "after-sales workflow", "operation platform"),
            problem="工单创建、分配、超时、关闭需要通知责任人，否则 SLA 不可控。",
            solution="领域事件 TicketCreated/TicketAssigned/TicketClosed 触发站内信、企业微信、短信或邮件；通知失败进入重试/死信。",
            required_entities=("Ticket", "User", "Notification"),
            required_modules=("domain_event", "notification_service", "retry_queue"),
            required_tables=("notification", "notification_retry"),
            required_interfaces=("NotificationService.send", "TicketEventConsumer"),
            implementation_steps=("状态变更发布领域事件。", "通知通道与业务事务解耦。", "通知失败写重试队列并设置最大重试次数。"),
            common_pitfalls=("同步调用外部通知拖慢主链路。", "通知失败无补偿导致用户无感知。"),
            test_points=("分配工单后处理人收到通知。", "通知通道失败后进入重试。"),
            source_refs=("local_pattern_library://ticket_notification",),
            confidence=0.86,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_seckill_redis_stock",
            name="秒杀 Redis 库存预扣模式",
            category="high_concurrency",
            applicable_scenarios=("seckill", "flash sale", "limited inventory"),
            problem="高并发秒杀直接扣数据库库存会锁冲突、超卖或击穿数据库。",
            solution="活动开始前预热库存到 Redis；请求用 Lua/原子 DECR 预扣；预扣成功后写入 MQ 异步创建订单。",
            required_entities=("SeckillActivity", "Stock", "Order", "User"),
            required_modules=("redis_stock_cache", "lua_deduct", "mq_producer"),
            required_tables=("seckill_activity", "seckill_order", "stock_flow"),
            required_interfaces=("POST /seckill/{activityId}/orders", "StockLuaScript.deduct"),
            implementation_steps=(
                "Redis key 按 activity_id 分片，活动前预热库存。",
                "Lua 脚本检查库存 > 0 且用户未下单，再原子扣减。",
                "预扣成功写 MQ，由消费者落库订单。",
            ),
            common_pitfalls=("Redis 扣减和用户幂等分开执行导致重复下单。", "活动热 key 未限流导致 Redis 抖动。"),
            test_points=("高并发压测不超卖。", "库存为 0 时立即失败。", "同一用户不能重复扣减。"),
            source_refs=("local_pattern_library://seckill_redis_stock",),
            confidence=0.95,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_seckill_mq_async_order",
            name="秒杀 MQ 异步下单模式",
            category="high_concurrency",
            applicable_scenarios=("seckill", "flash sale", "order peak shaving"),
            problem="秒杀入口同步完成全部下单逻辑会拖垮数据库和支付链路。",
            solution="入口只完成资格校验、限流、库存预扣与消息投递；订单消费者异步落库，失败写补偿任务。",
            required_entities=("Order", "Stock", "Payment"),
            required_modules=("message_queue", "order_consumer", "dead_letter_queue", "retry_policy"),
            required_tables=("order", "stock_flow", "mq_retry_log"),
            required_interfaces=("OrderConsumer.consume", "DeadLetterHandler"),
            implementation_steps=("消息体携带 request_id/user_id/activity_id。", "消费者保证幂等落库。", "失败消息进入重试/死信并触发库存回滚。"),
            common_pitfalls=("MQ 投递成功但业务未记录 request_id。", "消费者重复消费导致重复订单。"),
            test_points=("MQ 重复投递不生成重复订单。", "消费者失败后进入死信并触发库存回滚。"),
            source_refs=("local_pattern_library://seckill_mq_async_order",),
            confidence=0.93,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_seckill_idempotency_rollback",
            name="秒杀幂等与库存回滚模式",
            category="consistency_pattern",
            applicable_scenarios=("seckill", "order compensation", "payment timeout"),
            problem="订单失败、超时未支付、重复请求都会造成库存和订单状态不一致。",
            solution="以 user_id + activity_id/request_id 建唯一约束；订单超时取消触发库存回滚；失败补偿记录可重放。",
            required_entities=("Order", "StockFlow", "User"),
            required_modules=("idempotency_key", "timeout_cancel_job", "stock_compensation"),
            required_tables=("order", "stock_flow", "idempotency_record"),
            required_interfaces=("IdempotencyService.check", "StockRollbackService.rollback"),
            implementation_steps=("唯一索引防重复订单。", "订单未支付超时取消。", "取消/失败时按 stock_flow 精确回滚。"),
            common_pitfalls=("只靠前端按钮置灰防重复。", "取消订单未回滚 Redis 与数据库双侧库存。"),
            test_points=("重复下单测试。", "订单超时取消释放库存。", "支付失败库存回滚。"),
            source_refs=("local_pattern_library://seckill_idempotency_rollback",),
            confidence=0.94,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_rate_limit_load_test",
            name="限流熔断与高并发测试模式",
            category="resilience_testing",
            applicable_scenarios=("seckill", "hot API", "traffic peak"),
            problem="没有限流和压测指标，系统只是在正常流量下看似可用。",
            solution="入口令牌桶/漏桶限流，关键依赖熔断降级；压测观察 QPS、P99、失败率、库存一致性。",
            required_modules=("rate_limiter", "circuit_breaker", "load_test"),
            implementation_steps=("对活动入口按用户/IP/活动维度限流。", "依赖抖动时快速失败。", "压测报告必须包含不超卖断言。"),
            common_pitfalls=("只看平均响应时间，不看 P99。", "压测不校验库存一致性。"),
            test_points=("高并发压测。", "限流阈值测试。", "依赖超时降级测试。"),
            source_refs=("local_pattern_library://rate_limit_load_test",),
            confidence=0.9,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_auth_identity_tables",
            name="登录鉴权基础模型",
            category="security_architecture",
            applicable_scenarios=("login", "authentication", "authorization"),
            problem="登录鉴权模块需要用户、角色、权限、会话/Token 等核心结构，不能只做一个登录接口。",
            solution="设计 user/role/permission/user_role/role_permission 表，登录成功后签发 JWT 或 Session，并在受保护接口统一校验。",
            required_entities=("User", "Role", "Permission", "Token", "Session"),
            required_modules=("auth_service", "permission_interceptor", "session_store"),
            required_tables=("user", "role", "permission", "user_role", "role_permission"),
            required_interfaces=("POST /auth/login", "POST /auth/refresh", "GET /auth/me"),
            implementation_steps=("用户表保存 password_hash。", "登录接口返回 token 与过期时间。", "权限模型与接口资源绑定。"),
            common_pitfalls=("只返回用户 id，不做受保护接口校验。", "角色和权限混在字符串字段中不可治理。"),
            test_points=("登录成功返回 token。", "未登录访问受保护接口返回 401。", "无权限访问返回 403。"),
            source_refs=("local_pattern_library://auth_identity_tables",),
            confidence=0.94,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_password_hashing",
            name="密码安全存储模式",
            category="security_constraint",
            applicable_scenarios=("login", "register", "account system"),
            problem="明文或弱 hash 存储密码，一旦数据库泄露会直接导致账号沦陷。",
            solution="使用 BCrypt/Argon2/PBKDF2 加盐慢 hash；登录时恒定路径校验；禁止日志输出密码。",
            required_entities=("User",),
            required_modules=("password_encoder", "security_log_redactor"),
            required_tables=("user",),
            required_interfaces=("PasswordEncoder.encode", "PasswordEncoder.matches"),
            implementation_steps=("注册/重置密码只存 password_hash。", "登录使用 matches 校验。", "密码字段不进入日志和审计明文。"),
            common_pitfalls=("使用 MD5/SHA1 无盐 hash。", "登录失败日志打印明文密码。"),
            test_points=("数据库不出现明文密码。", "同一密码多次 hash 结果不同。", "错误密码登录失败。"),
            source_refs=("local_pattern_library://password_hashing",),
            confidence=0.96,
            verification_level="human_verified",
        ),
        PatternCard(
            pattern_id="pattern_jwt_session_interceptor",
            name="JWT/Session 与权限拦截模式",
            category="security_architecture",
            applicable_scenarios=("distributed auth", "Spring Security", "API gateway"),
            problem="Token 生成容易，难点是刷新、过期、黑名单、白名单和受保护接口统一校验。",
            solution="认证 Filter/Interceptor 解析 token，加载 AuthContext；登录/健康检查走白名单；Redis 维护 session/token blacklist；刷新 token 有过期策略。",
            required_entities=("Token", "Session", "Permission"),
            required_modules=("auth_filter", "token_service", "redis_session_cache", "api_whitelist"),
            required_interfaces=("AuthFilter", "TokenService.refresh", "WhitelistMatcher"),
            implementation_steps=("白名单路径先放行。", "受保护接口解析 token 并注入 AuthContext。", "登出/封禁时写 Redis token blacklist。"),
            common_pitfalls=("只在登录接口生成 JWT，后续接口不校验。", "Token 过期和刷新策略不清导致安全窗口。", "白名单过宽导致越权。"),
            test_points=("Token 过期后访问失败。", "登出后旧 token 失效。", "白名单接口无需 token，非白名单必须鉴权。"),
            source_refs=("local_pattern_library://jwt_session_interceptor",),
            confidence=0.94,
            verification_level="human_verified",
        ),
    ]


class PatternRetriever(BaseRetriever):
    name = "pattern"

    def __init__(self, cards: Sequence[PatternCard] | None = None, *, min_score: float = 0.08) -> None:
        self.cards = list(cards) if cards is not None else builtin_pattern_cards()
        self.min_score = min_score

    def retrieve(
        self,
        slots: Sequence[NeedSlot],
        queries_by_slot: Mapping[str, Sequence[str]],
        frame: TaskSemanticFrame | None = None,
    ) -> list[CandidateEvidence]:
        candidates: list[CandidateEvidence] = []
        for card in self.cards:
            content = _card_text(card)
            matched_slot_ids: list[str] = []
            best_score = 0.0
            for slot in slots:
                queries = list(queries_by_slot.get(slot.slot_id, ())) + list(slot.query_terms) + [slot.name, slot.description]
                score = lexical_score(queries, content)
                if self._semantic_hint_match(slot, card):
                    score = max(score, 0.72)
                if score >= self.min_score:
                    matched_slot_ids.append(slot.slot_id)
                    best_score = max(best_score, score)
            if not matched_slot_ids:
                continue
            candidates.append(
                evidence_from_text(
                    source_type="pattern_card",
                    title=card.name,
                    content=content,
                    matched_slot_ids=matched_slot_ids,
                    raw_similarity_score=best_score,
                    verification_level=card.verification_level,
                    source_ref=card.source_refs[0] if card.source_refs else f"pattern://{card.pattern_id}",
                    metadata={"pattern_card": card.to_dict(), "retriever": self.name, "confidence": card.confidence},
                )
            )
        return merge_evidence(candidates)

    def _semantic_hint_match(self, slot: NeedSlot, card: PatternCard) -> bool:
        sid = slot.slot_id
        pid = card.pattern_id
        return any(
            [
                sid in {"slot_multi_tenant", "slot_tenant_constraint", "slot_cross_tenant_test"} and "multi_tenant" in pid,
                sid == "slot_rbac" and "rbac" in pid,
                sid == "slot_ticket_entity" and "ticket_entity" in pid,
                sid in {"slot_ticket_state_machine", "slot_ticket_status_log", "slot_operator_audit", "slot_status_transition_test"}
                and "ticket_state_machine" in pid,
                sid == "slot_notification" and "notification" in pid,
                sid in {"slot_stock_pre_deduction", "slot_redis_stock_cache"} and "redis_stock" in pid,
                sid == "slot_mq_async_order" and "mq_async" in pid,
                sid in {"slot_duplicate_order", "slot_order_timeout", "slot_stock_rollback"} and "idempotency_rollback" in pid,
                sid in {"slot_rate_limit", "slot_high_concurrency_test"} and "rate_limit" in pid,
                sid in {"slot_user_table", "slot_login_api"} and "auth_identity" in pid,
                sid == "slot_password_hash" and "password_hashing" in pid,
                sid in {"slot_jwt_session", "slot_permission_interceptor", "slot_api_whitelist", "slot_redis_session", "slot_auth_security_test"}
                and "jwt_session" in pid,
            ]
        )
