# Resilience: Payment Disconnects, Attack Resistance and Anti-Crawl

这个模块给项目补“极端场景抗性”：用户支付中途断线、攻击流量进入、防爬/限流触发时，系统不能靠口头承诺，必须有状态机、幂等、补偿、观测和演练。

入口：

```text
agent/resilience/
tests/test_resilience_plan.py
```

executor action：

```json
{
  "type": "action",
  "action": "resilience_plan",
  "args": {
    "surface": "agent-saas",
    "payment_enabled": true,
    "payment_provider": "generic",
    "threat_level": "internet",
    "output_path": "plans/resilience.json"
  }
}
```

权限要求：

```text
workspace:read + security:plan
```

## 1. 支付断线：不能失败，也不能重复交付

核心代码：

```text
agent/resilience/payments.py
```

支付状态机：

```text
initiated -> pending -> paid
                    -> failed
paid -> refund_pending -> refunded
```

关键规则：

- `client_disconnect` 不把订单标记为失败，只进入 `pending + requires_reconciliation`。
- provider webhook / reconcile job 都走同一套幂等状态机。
- `event_id` 做 inbox 去重。
- `outbox` 和状态变更在同一事务边界内产生。
- `fulfill_order` 用 `idempotency_key` 保证只发一次。

这能扛住：

- 用户关闭浏览器
- provider webhook 重复发送
- webhook 先于客户端回调到达
- provider 查询超时
- 交付消息重试

## 2. 攻击抵抗：分层防御

核心代码：

```text
agent/resilience/security.py
```

分层：

- edge：WAF、TLS、request size、bot score、IP reputation
- identity：短 token、refresh rotation、角色/租户 claim
- application：schema validation、CSRF、SSRF allowlist、prompt evidence isolation
- runtime：K8s SecurityContext、只读根文件系统、drop ALL capabilities、默认 deny NetworkPolicy
- data：KMS、最小权限 DB、audit log

特别贴合本项目的点：

- prompt injection：证据块隔离 + citation-required answer
- command injection：SupervisorChain 拦截
- 高风险自动化：转 K8s sandbox
- K8s escape：禁止 hostPath/privileged/serviceAccount token

## 3. 防爬/限流：渐进式响应

核心代码：

```text
agent/resilience/anticrawl.py
```

不是“一刀切封 IP”，而是风险评分 + 渐进响应：

```text
0-30   allow
31-60  soft throttle + cache-only response
61-80  challenge / require login
81-100 deny + audit + temporary token revocation
```

限流维度：

- IP
- account
- tenant
- expensive_agent_action

信号：

- request velocity
- path entropy
- session age
- token spend velocity
- same query across many accounts
- failed challenge ratio

## 4. 可观测与混沌演练

指标：

- `payment_attempts_total{status,provider}`
- `payment_reconcile_lag_seconds{provider}`
- `outbox_dispatch_failures_total{type}`
- `auth_failures_total{reason}`
- `rate_limited_requests_total{scope}`
- `bot_risk_score_bucket{surface}`
- `supervisor_denials_total{reason}`

混沌演练：

- payment client disconnect
- duplicate webhook
- bot spike
- WAF false positive
- sandbox escape attempt

## 当前边界

完成的是韧性控制面和可测试状态机。还未接真实支付 SDK、真实数据库唯一索引、真实 Redis 限流器、真实 WAF provider。下一步应该把这些 plan 落到 FastAPI middleware / DB migration / Redis token bucket / K8s ingress annotations。

