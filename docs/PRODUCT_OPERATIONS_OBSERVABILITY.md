# 产品运行态可观测与任务韧性

本轮补强目标：让“软件工坊”不只是能生成页面，而是能解释线上运行时发生了什么、失败任务怎么处理、用户操作如何追溯。

## 1. 任务队列：从异步到可恢复

`ProductTaskQueue` 现在支持：

```text
queued -> running -> finished
queued -> running -> queued(retry)
queued -> running -> dead_letter
```

关键字段：

```text
attempts          当前执行次数
max_attempts      最大重试次数
errors            每次失败的错误栈摘要
dead_letter       是否进入死信队列
duration_ms       实际执行耗时
owner_key         用户隔离
```

为什么重要：

- 临时错误不应直接让任务失败；
- 多次失败必须进入死信队列，避免无限重试；
- 任务必须能按用户隔离查询，避免串数据；
- 后续替换 Redis/Celery/RQ 时 API 形态不变。

## 2. 审计日志：关键操作可追溯

新增 append-only JSONL：

```text
product_runs/.agent_audit.jsonl
```

记录事件：

```text
payment_order_created
payment_order_confirmed
payment_order_reconciled
simple_job_submitted
simple_package_downloaded
rate_limited
```

查询接口：

```text
GET /api/audit/events?limit=100
```

管理员可加：

```text
GET /api/audit/events?all=1
```

## 3. 运维快照

新增：

```text
GET /api/ops/snapshot
```

返回：

```text
queue          队列状态、死信任务、近期任务
billing        token 余额与消耗
rate_limiter   防刷窗口统计
audit_tail     最近审计事件
```

这相当于一个轻量控制台，适合本地展示；生产环境可以接 Prometheus/Grafana/Loki。

## 4. 面试讲法

> 我没有把任务队列停留在“异步执行”这个层面，而是补了 retry、dead-letter、owner isolation 和 duration tracking；同时把支付、任务提交、打包下载、限流这些关键动作写入 append-only audit log。这样系统出了问题可以回答：谁在什么时候做了什么、任务失败了几次、是否进入死信、是否被限流、token 有没有重复发放。

## 5. 后续生产替换点

```text
ProductTaskQueue    -> Redis Queue / Celery / Temporal
ApiRateLimiter      -> Redis sliding window / API Gateway / WAF
.agent_audit.jsonl  -> Postgres audit table / Loki / Kafka topic
/api/ops/snapshot   -> Prometheus + Grafana dashboard
```
