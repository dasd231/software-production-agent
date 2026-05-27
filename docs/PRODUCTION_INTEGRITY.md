# Production Integrity：登录、数据库、安全与幂等规格

> 位置：`agent/platform/production_spec.py`  
> 目的：补齐“项目完整性”的企业级回答：登录用什么库、生产用什么库、安全怎么验、幂等怎么验、审计怎么留。

## 数据库选型

### 登录与权限库

- 本地：SQLite / in-memory fake，只用于单测和 smoke test。
- 生产：PostgreSQL `identity` schema。
- 表：`users / roles / permissions / user_roles / role_permissions / sessions / audit_login`。

原因：登录、权限、会话、审计需要事务、约束、迁移、备份、恢复，不能放在本地文件或纯缓存。

### 业务与 Agent 控制面库

- 本地：SQLite 或 docker-compose PostgreSQL。
- 生产：PostgreSQL HA。
- 表：`workflow_runs / workflow_events / guard_reports / skill_bundles / evidence_ledger / idempotency_records / outbox_events`。

原因：Agent 状态、证据链、幂等记录、outbox 都要求 ACID 和可审计。

### Redis 用途

- session/token blacklist；
- rate limit token bucket；
- distributed lock；
- short TTL idempotency cache；
- model admission leases。

注意：Redis 只承载短期高并发协调，长期幂等结果必须落 PostgreSQL。

## 安全验证

1. 密码：Argon2id/BCrypt，永不明文存储和日志输出。
2. Token：短 TTL access token + refresh rotation + Redis blacklist。
3. RBAC：User-Role-Permission + tenant-aware AuthContext。
4. 输入和 Prompt 安全：Pydantic DTO + SkillRuntime ContractGuard + evidence_id。
5. 日志脱敏：password/token/secret/api_key/private_key 递归清理。

## 幂等验证

1. HTTP 幂等：`Idempotency-Key + tenant_id + user_id + route + body_hash`，PostgreSQL unique constraint。
2. Outbox 去重：`event_id` unique，消费者按 `event_id/side_effect_key` 去重。
3. Workflow 节点幂等：`run_id + node + step_index + semantic_action_hash`。

验证规则：

- 同 key 同 body 返回同结果；
- 同 key 不同 body 返回 409；
- retry/resume 不重复执行副作用；
- 消息重复投递不重复调用外部系统。

## Release Gates

- migration rollback tested；
- auth/RBAC/idempotency tests pass；
- hallucination harness pass or explicit risk waiver；
- Prometheus metrics + audit log enabled；
- production database backup/restore drill completed。

## 面试讲法

> 登录和生产状态我会分层处理：认证权限用 PostgreSQL identity schema，Agent 控制面也用 PostgreSQL，因为 workflow、证据链、幂等、outbox 都需要 ACID 和审计；Redis 只做短 TTL 会话、黑名单、限流、锁和 lease。安全上密码用 BCrypt/Argon2id，Token 有 refresh rotation 和 blacklist，RBAC 带 tenant 上下文；幂等靠 Idempotency-Key、body_hash、unique constraint 和 outbox dedup。这样不是 Demo，而是按生产事故预防来设计。
