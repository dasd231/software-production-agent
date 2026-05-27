# Operations Readiness + Multi-Agent Resilience

这块的目标不是“加几个日志字段”，而是把项目补成一个可上线、可答辩、可面试的运行可靠性控制面：应用健康能被探测，日志能串起证据链，监控能发现退化，多智能体池子能在节点挂掉时继续工作。

## 1. 当前落地模块

```text
agent/operations/
  health.py              # /healthz /readyz /startupz /metrics 的健康契约与聚合规则
  logging_contract.py    # 结构化日志字段、脱敏规则、保留策略
  monitoring.py          # SLO、Golden Signals、Prometheus 指标、告警、Dashboard
  multi_agent.py         # 多智能体 heartbeat / failover / idempotency / DLQ 方案
  planner.py             # 汇总成 operations_readiness_plan

tests/test_operations_readiness.py
```

新增 executor action：

```text
operations_readiness_plan
```

权限：

```text
ops:plan + workspace:write
```

## 2. 健康检查设计

应用健康分成三个端点，避免生产系统里最常见的误伤：

| Endpoint | 语义 | 失败后动作 | 不应该做什么 |
|---|---|---|---|
| `/healthz` | liveness，只证明进程/事件循环还活着 | 重启容器 | 不查慢依赖，不因 DB 慢就杀进程 |
| `/readyz` | readiness，判断能否接流量 | 从 Service Endpoints 摘除 | 不直接重启，给依赖恢复机会 |
| `/startupz` | startup，判断初始化是否完成 | 延迟 liveness 生效 | 不让冷启动阶段被 liveness 杀死 |
| `/metrics` | Prometheus scrape | 告警观测缺口 | 不因为 metrics 失败就盲目重启核心服务 |

聚合规则：

```text
critical check failed       -> unhealthy / ready=false / live=false
non-critical failed         -> degraded / ready=true
critical check slow         -> degraded / ready=true
all checks passed           -> healthy
```

当前建议的组件检查：

```text
process
workspace_fs
event_log_writer
model_router
graph_memory
solution_library
k8s_sandbox_dispatcher
payment_reconcile_worker
```

K8s 层补充：

```text
startupProbe -> /startupz
livenessProbe -> /healthz
readinessProbe -> /readyz
PodDisruptionBudget -> minAvailable=1
```

这能避免滚动发布或节点维护时把所有 Agent 副本一起打掉。
当前 `agent.platform.api` 已经接入了真实端点：

```text
GET /healthz   -> 只做轻量 liveness 聚合
GET /readyz    -> 依赖 readiness 聚合，失败时返回 503
GET /startupz  -> 启动完成度聚合，失败时返回 503
GET /metrics   -> Prometheus text exposition 原型
```

## 3. 日志：从“能看报错”升级到“能复盘决策”

结构化 JSON 日志强制字段：

```text
timestamp, level, service, environment,
trace_id, span_id, run_id, tenant_id, agent_id,
action, status, latency_ms, error_code
```

关联语义：

```text
trace_id  串起一次用户请求跨服务路径
run_id    串起一次 Agent 工作流
agent_id  定位多智能体池中的具体执行者
action    定位 executor 动作
span_id   定位某一步工具/模型/检索调用
```

脱敏规则已经落地到 `redact_log_payload()`，会递归处理：

```text
password / passwd / token / access_token / refresh_token / secret /
api_key / apikey / authorization / cookie / private_key
```

原则：任何日志、trace、graph property 写入前先脱敏。尤其是 prompt、provider token、用户代码片段里的私钥，不能原样落盘。

## 4. 监控指标与告警

SLO 默认：

```text
availability: 99.5%
p95_agent_run_latency_seconds: 120
p95_action_latency_seconds: 30
```

Golden Signals：

```text
latency / traffic / errors / saturation
```

Agent 专用指标：

```text
agent_runs_total{status,tenant,policy_version}
agent_action_total{action,status,error_code}
agent_action_latency_ms_bucket{action}
agent_supervisor_denials_total{reason}
agent_human_intervention_total{level}
agent_graph_rag_query_total{status}
agent_policy_canary_hold_total{reason}
agent_task_queue_depth{role,priority}
agent_heartbeat_staleness_seconds{agent_id,role}
agent_dead_letter_total{role,reason}
```

核心告警：

| Alert | 触发点 | 处理原则 |
|---|---|---|
| HighErrorRate | action error rate 过高 | 先降级/限流，再查最近发布 |
| AgentRunLatencyBurn | p95 run latency 超 SLO | 看队列深度、模型超时、检索退化 |
| SupervisorDenialSpike | 监督拒绝突增 | 检查攻击、prompt injection 或策略误伤 |
| HeartbeatStale | Agent 心跳过期 | fence lease，任务重分配 |
| DeadLetterGrowing | DLQ 增长 | 补对应角色副本或人工介入 |
| PolicyCanaryHold | 灰度策略被阻断 | 回看 replay/canary 证据 |
| GraphIngestFailure | 图事件写入失败 | 保护 `.agent_events.jsonl` 主证据链 |


云原生调度/存储/网络压力指标也进入统一监控契约：

```text
agent_cni_ip_pressure_ratio
agent_csi_attach_latency_seconds_bucket
agent_pod_overhead_cpu_pressure_ratio
agent_pod_overhead_memory_pressure_ratio
agent_scheduler_storage_topology_reject_total
```

它们补的是 Agent 平台的“底层运行时健康”：不是 API 活着就算健康，还要看 CNI/IPAM、CSI attach、RuntimeClass PodOverhead 是否正在吞掉调度容量。
## 5. 多智能体可用性与容错

多智能体系统的真正风险不是“某个 Agent 回答错”，而是：

```text
重复执行副作用
任务被挂死
多个 orchestrator 分裂脑
某个角色全挂导致全链路阻塞
模型供应商 timeout 引发级联失败
```

当前方案把 Agent 池抽象成：

```text
orchestrator     # 全局调度、策略版本、准入控制
planner          # 拆任务、生成图
researcher       # RAG/Web/GitHub 证据
coder           # 有边界地改代码
verifier         # 测试、scorecard、证据验货
sandbox_runner   # 高风险动作进 K8s 隔离执行
```

核心机制：

```text
heartbeat + lease per agent
single-writer lease + epoch fencing
durable task queue + visibility timeout
idempotency key on every task and side effect
work stealing from stale leases
dead letter queue for tasks with no healthy role owner
bulkhead isolation by role and tenant
circuit breaker around model providers/tools
backpressure through global admission controller
checkpoint/resume for graph state
```

### Failover 决策

`build_multi_agent_failover_decision()` 会根据：

```text
status == healthy
last_seen_seconds <= stale_after_seconds
load <= max_load
```

判断 Agent 是否可用。任务如果分配给 stale/unhealthy/overloaded Agent，会优先找同角色健康 Agent；没有同角色时退化到任意健康 Agent，并带上 idempotency key 防重复执行。没有可用 Agent 时进入 DLQ。

### 为什么要 idempotency key

Agent 系统经常会遇到：

```text
请求超时，但实际已经执行
worker 重启后任务被重新投递
webhook 重放
human retry
```

没有 idempotency key，就会出现重复提交 PR、重复扣费、重复写数据库、重复发消息。这里要求每个 task 和副作用都带：

```text
idempotency_key = tenant_id + run_id + action_name + deterministic_input_hash
```

## 6. 推荐的持久化表/队列模型

后续如果落到 Postgres/Redis，可以用下面这个结构：

```sql
agent_instance(
  agent_id text primary key,
  role text not null,
  status text not null,
  lease_owner text,
  lease_epoch bigint not null,
  last_heartbeat_at timestamptz not null,
  load numeric not null,
  metadata jsonb not null default '{}'
);

agent_task(
  task_id text primary key,
  run_id text not null,
  required_role text not null,
  state text not null,
  priority int not null default 0,
  assigned_agent_id text,
  visibility_deadline timestamptz,
  idempotency_key text not null unique,
  attempt_count int not null default 0,
  payload jsonb not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);

agent_dead_letter(
  dlq_id text primary key,
  task_id text not null,
  reason text not null,
  payload jsonb not null,
  created_at timestamptz not null
);
```

Redis 也可以先做轻量版本：

```text
agent:heartbeat:{agent_id} -> TTL key
agent:lease:{task_id}      -> SET NX PX + fencing token
queue:{role}:{priority}    -> stream/list
idempotency:{key}          -> completed result pointer
```

## 7. Executor 使用方式

示例 action：

```json
{"type":"action","action":"operations_readiness_plan","args":{"service_name":"software-production-agent","replicas":3,"slo_target":0.995,"output_path":"plans/operations_readiness.json"}}
```

执行后会生成：

```text
health.contract
health.snapshot
health.k8s
logging
monitoring
multi_agent.resilience_plan
multi_agent.failover_decision
release_gates
implementation_order
```

这相当于给项目加了一个“上线前运维体检单”。

## 8. 下一步真实工程化

优先级按能快速展示和真实收益排序：

1. 已完成 FastAPI `/healthz`、`/readyz`、`/startupz`、`/metrics` 原型；下一步把更多依赖检查接入。
2. executor 每次 action 输出结构化 log，并写入 `.agent_events.jsonl`。
3. 扩展 Prometheus exporter，把 executor/action/supervisor/graph/task queue 指标真正 emit 出去。
4. 给多智能体调度接 Redis/Postgres task queue。
5. 每个 Agent worker 加 heartbeat、lease、visibility timeout 和 idempotency store。
6. 接 Grafana dashboard 与 Alertmanager runbook。

## 9. 面试/答辩表达

可以这样讲：

> 我们不是只做一个能跑 demo 的 Agent，而是把它当成长期运行的分布式应用来设计。健康检查区分 liveness/readiness/startup，避免依赖慢导致误杀；日志强制 trace_id/run_id/action 关联，能回放决策证据链；监控围绕 SLO、error budget 和 Agent 特有指标；多智能体调度使用 heartbeat、lease、visibility timeout、idempotency、DLQ 和 bulkhead，解决 crash、重复执行、分裂脑、角色池不可用和供应商退化问题。

这句话比较关键：**Agent 的可靠性不是靠“模型更聪明”解决的，而是靠分布式系统的契约、观测、隔离和恢复机制兜底。**

## 10. 本轮补齐：任务队列与 Grafana/Alertmanager 契约

新增：

```text
agent/operations/task_queue.py
agent/operations/dashboards.py
```

`InMemoryAgentTaskQueue` 是 Redis/Postgres 后端前的可靠性语义原型，已经覆盖：

```text
heartbeat
lease
visibility timeout
idempotency_key
delete/complete/fail
expired lease requeue
dead letter queue
```

这对应生产落库模型：

```text
agent_instance
agent_task
agent_dead_letter
```

同时 `build_grafana_alertmanager_bundle()` 给出三组 Dashboard：

```text
Agent Executive Overview
Multi-Agent Runtime Pool
Cloud Native Scheduling Pressure
```

核心告警包括：

```text
HighErrorRate
HeartbeatStale
DeadLetterGrowing
CniIpPressure
CsiAttachLatencyHigh
PodOverheadPressure
```

它把“Agent 不崩”这件事从口号推进到可观测、可告警、可排障的运维契约。
