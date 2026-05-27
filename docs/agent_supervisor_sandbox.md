# Agent Supervisor + K8s Sandbox

这层是把 Spring Security Filter Chain / AOP / Actuator 思想迁移到 Agent 系统里的监督辅助层。

## 目标

原来的执行链路大致是：

```text
AgentBrain -> action JSON -> executor.run_action_guarded -> tool / shell / chain
```

新增监督层后：

```text
AgentBrain
  -> action JSON
  -> SupervisorChain
      -> PermissionSupervisorFilter
      -> PathSafetySupervisorFilter
      -> CommandRiskSupervisorFilter
      -> ResourceBudgetSupervisorFilter
  -> executor.run_action_guarded
  -> result.preflight.supervisor
  -> .agent_events.jsonl audit summary
```

它的定位不是替代 executor，而是在 executor 前面增加一条可解释、可扩展、可审计的过滤链。

## Spring 思想如何缝合

### 1. Spring Security Filter Chain

对应代码：

```text
agent/supervisor/filter_chain.py
```

每个 filter 只负责一类判断：

```text
PermissionSupervisorFilter   权限与确认
PathSafetySupervisorFilter   路径是否逃逸 workspace
CommandRiskSupervisorFilter  命令风险、人工确认、沙盒建议
ResourceBudgetSupervisorFilter  资源预算与超时
```

这和 Spring Security 的“多个过滤器按顺序拦截请求”是同一种思想。

### 2. Spring AOP

AOP 的本质是：

```text
在业务执行前后插入横切逻辑
```

在这里就是：

```text
pre_check: 监督 action
execute:   原 executor 正常执行
post_check: 后续可接结果评分、审计、训练数据
```

当前已经实现了 pre_check audit events，后续可以继续扩展 post_check。

### 3. Spring Actuator

Supervisor 输出会进入：

```text
result.preflight.supervisor
.agent_events.jsonl result_summary
```

后续可直接做：

```text
/agent/supervisor/status
/agent/audit/events
/agent/sandbox/jobs
```

## K8s Security Context 能做到什么

K8s Security Context 不是完整沙盒，但它是沙盒的一层：

```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  seccompProfile:
    type: RuntimeDefault
containers:
  - securityContext:
      allowPrivilegeEscalation: false
      readOnlyRootFilesystem: true
      capabilities:
        drop: ["ALL"]
```

真正强一点的沙盒要叠加：

```text
SecurityContext
Resource requests/limits
NetworkPolicy 默认拒绝
ServiceAccount 最小权限 / automountServiceAccountToken=false
TTL 自动清理
独立 Namespace
可选 gVisor / Kata / Firecracker
准入策略禁止 privileged / hostPath
```

## K8s Sandbox Job 渲染器

对应代码：

```text
agent/sandbox/k8s_job.py
```

它可以把高风险 action 变成受限 Job manifest：

```python
from agent.sandbox import K8sSandboxSpec, render_sandbox_bundle

bundle = render_sandbox_bundle(
    {"type": "action", "action": "run_command", "args": {"command": "python train_model.py"}},
    spec=K8sSandboxSpec(namespace="agent-sandbox", network="none"),
)
```

默认安全点：

```text
automountServiceAccountToken=false
runAsNonRoot=true
allowPrivilegeEscalation=false
readOnlyRootFilesystem=true
capabilities.drop=ALL
seccompProfile=RuntimeDefault
activeDeadlineSeconds
TTLSecondsAfterFinished
NetworkPolicy 默认 deny ingress/egress
```

## Agent 动作：k8s_sandbox_plan

新增了一个安全的计划动作：

```json
{
  "type": "action",
  "action": "k8s_sandbox_plan",
  "args": {
    "command": "python train_model.py",
    "namespace": "agent-sandbox",
    "output_path": "sandbox/job.json"
  }
}
```

它只渲染 manifest，不直接提交到集群：

```text
render only, no kubectl apply
```

输出包含：

```text
Job manifest
默认 deny NetworkPolicy
SecurityContext hardening
resource requests/limits
TTL / activeDeadlineSeconds
```

这一步很关键：高风险命令不是立刻执行，而是先进入可审查的 sandbox plan。后续才可以接真正的 Kubernetes dispatcher。

## 执行器集成

`agent.core.executor.run_action_guarded` 现在会把监督结果写进：

```text
result["preflight"]["supervisor"]
```

例如：

```json
{
  "status": "allowed",
  "risk_level": "high",
  "sandbox_recommended": true,
  "warnings": ["command should run in k8s sandbox for resource and blast-radius isolation"]
}
```

显式要求沙盒时：

```json
{"type":"action","action":"run_command","args":{"command":"python train_model.py","sandbox":"k8s"}}
```

本地 executor 会返回：

```text
SUPERVISOR_SANDBOX_REQUIRED
recommended_action=dispatch_to_k8s_sandbox
```

这就是未来接 K8s dispatch 的接口。

如果希望 Agent 先生成可审查 manifest，可以使用：

```text
k8s_sandbox_plan
```

权限要求：

```text
sandbox:plan
workspace:write
```

## 面试表达

可以这样讲：

> 我借鉴 Spring Security Filter Chain 和 AOP 思想，在 Agent 执行器前增加 SupervisorChain。它会做权限、路径、命令风险、资源预算、沙盒建议等横切监督。普通动作仍走本地 executor；高风险动作会被标记为 sandbox_required，后续派发到 K8s SecurityContext 受限 Job。监督结果进入 preflight 和事件日志，能用于审计、指标和训练数据。

关键不是“用了 K8s SecurityContext”，而是：

```text
Agent 行为治理
+ 云原生隔离
+ 审计闭环
+ 可训练监督数据
```
