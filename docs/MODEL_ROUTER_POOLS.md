# Model Router Pools

目标：把输入上下文和业务类型先过一层准入计划，再进入模型服务。这样短 API 请求、长上下文 RAG、Agent 工具调用、离线训练批处理不会共用一个拥塞队列，也不会互相抢占 KV cache、prefill 时间和状态机资源。

## 链路

```text
request
  -> Token Estimator
     - prompt_tokens
     - max_output_tokens
     - business_type
  -> Model Router
     - short_pool
     - long_pool
     - agent_pool
     - training_batch_pool
  -> Admission Controller
     - per-pool lease
     - concurrency cap
     - backpressure / 429
  -> model gateway / vLLM / SGLang / batch worker
```

## 池子职责

| Pool | Runtime | 目标 | 核心限制 |
|------|---------|------|----------|
| `short_pool` | vLLM | 8K/16K 内短请求，高并发、低超时、多副本 | `max_num_seqs` 高，可重试，不保留状态 |
| `long_pool` | vLLM/SGLang | 32K/64K 长上下文、RAG、大方案文档 | 严格并发、chunked prefill、prefix caching、独立队列 |
| `agent_pool` | SGLang/Agent Service | 工具调用、状态机、多 Agent 编排、结构化输出 | token budget、工具调用限制、状态租约 |
| `training_batch_pool` | offline batch | SFT 数据生成、评测批处理、训练准备 | 低优先级、可 checkpoint、不抢占在线池 |

## 准入策略

`agent.scheduler.routing.build_model_route_plan()` 返回：

- `token_estimate`：prompt/output/total tokens。
- `business_type`：业务分类、置信度、命中信号。
- `selected_pool`：推荐池子。
- `queue_policy`：并发、超时、是否需要资源租约、是否可被抢占。
- `admission`：`admitted` 或 `blocked`，以及拒绝原因和拆分/摘要建议。

Action 示例：

```json
{"type":"action","action":"model_route_plan","args":{"goal":"长上下文RAG方案设计，要求结构化JSON输出","prompt":"...","require_json":true,"max_output_tokens":1800}}
```

API 示例：

```bash
curl -X POST http://127.0.0.1:8080/api/model-route-plan \
  -H "Content-Type: application/json" \
  -d '{"goal":"100+终端企业AI平台长上下文RAG请求","prompt":"...","max_output_tokens":2048}'
```

## 高并发准入

`agent.scheduler.admission.PoolAdmissionController` 在路由计划之后执行：

- 池子预算不满足：直接 `route_blocked`，返回拆分/摘要建议。
- 池子并发已满：返回 `pool_saturated`、`retry_after_s` 和 HTTP 429。
- 池子可用：发放 `lease_id`，调用方拿 lease 后才能转发 model gateway。
- 请求结束：调用 release 释放 lease；调用方异常退出时由 TTL 自动回收。
- 幂等：传 `idempotency_key` 时，重复 acquire 返回同一个活动 lease。

API：

```bash
curl -X POST http://127.0.0.1:8080/api/model-admission/acquire \
  -H "Content-Type: application/json" \
  -d '{"goal":"短API请求","max_output_tokens":256,"idempotency_key":"req-001"}'

curl -X POST http://127.0.0.1:8080/api/model-admission/release \
  -H "Content-Type: application/json" \
  -d '{"lease_id":"..."}'
```

## 抢占规避

1. 短请求进入 `short_pool`，允许高并发和快速失败重试。
2. 长上下文进入 `long_pool`，队列和 endpoint 独立，`max_num_seqs` 低，保护 prefill 和 KV cache。
3. Agent 请求进入 `agent_pool`，需要状态租约，工具调用和 token budget 独立限额。
4. 训练/评测批处理进入 `training_batch_pool`，默认不占在线模型池。
5. 超出池子预算时先返回 `blocked` 和 remediation，不把超长请求硬塞给在线池。

当前落地的是“路由 + 准入租约层”。默认 backend 是进程内 `local`，适合单副本和测试；多副本生产应把 lease 存储替换为 Redis、Postgres advisory lock 或 workflow queue，并按 `queue_policy.queue_key` 转发到各池 worker。
