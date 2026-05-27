# CommandAPI：大项目集中治理与 LangGraph 工作流边界

> 目标：解决“大项目能力越来越多、action 越来越散、workflow 越来越像意大利面”的问题。  
> 代码位置：`agent/command_api/`  
> Action：`command_api_plan`

## 1. 核心判断

LangGraph 很强，强在 **状态图、条件路由、Command goto、checkpoint、interrupt、可恢复执行**。但大项目不能只靠“节点自己 goto”，否则能力越多越松散：

```text
prompt 散落
工具散落
action 名字散落
权限散落
副作用散落
监控指标散落
```

所以项目里补了 `CommandAPI`：

```text
CommandAPI：定义稳定能力边界
LangGraph-like Runtime：动态编排这些能力
Enterprise Workflow Compiler：把业务流程编译成可上线契约
Graph Memory：记录 command/workflow/risk/release gate 经验
Operations：兜底健康、队列、DLQ、SLO
```

一句话：

> LangGraph 解决“工作流怎么跑”，CommandAPI 解决“大项目能力怎么不散”。

## 2. CommandContract

每个能力必须声明：

```text
name
bounded_context
intent
action
permissions
input_schema
output_schema
side_effect
risk_level
workflow_phase
release_gates
observability
```

这让项目从“很多函数”升级成“能力地图”。

## 3. 当前 CommandAPI 覆盖的上下文

```text
workflow_control_plane
workflow_graph_rag
graph_memory
operations
cloud_native_runtime
business_semantics
sandbox_runtime
long_context_storage
evaluation
```

典型命令：

| Command | 作用 |
|---|---|
| CompileEnterpriseWorkflow | Dify/YAML -> 企业级 LangGraph-like 契约 |
| QueryEnterpriseWorkflowGraph | 查询 workflow 图里的风险、审批、副作用、release gate |
| PlanGraphRuntime | LangGraph 二改 + 图数据库 memory plane |
| BuildOperationsReadiness | 监控、日志、健康、多 Agent 容错 |
| PlanCloudNativeDeepDive | K8s 调度、PV/CSI/CNI/etcd 优化 |
| CompileBusinessRule | 业务规则 -> 状态机/API/权限矩阵 |
| PlanK8sSandbox | 高风险命令沙盒化 |
| PlanContextPV | 超长上下文 PV 切片 |
| PlanAutomationScorecard | 就业/竞赛/论文指标反作弊 |

## 4. 图结构可视化

`command_api_plan` 会输出：

```text
graph_projection
cypher_seed
mermaid
```

Mermaid 里可以看到：

```text
CommandAPI
  -> BoundedContext
  -> Command
  -> ExecutorAction
  -> Permission / ReleaseGate
```

这让架构可以被文档、图数据库和面试同时复用。

## 5. 大项目反松散规则

1. 新 action 先注册 `CommandContract`，再接 executor。
2. side-effect command 必须声明 idempotency/outbox/human/release gate 策略。
3. workflow 必须经过 `enterprise_workflow_compile`，才能进入 pilot。
4. command、workflow、release gate、finding 全部可投影为 property graph。
5. 小模型只负责高频路由/判别，大模型负责复杂推理，工具负责确定性执行。

## 6. LangChain / LangGraph 开发问题怎么体现

### LangChain 常见问题

```text
链式调用容易变长
隐式状态多
工具/Prompt/Memory 容易散
复杂分支难维护
生产观测需要额外补
```

项目应对：

```text
CommandAPI 统一能力边界
Enterprise Workflow Compiler 统一状态契约
Graph Memory 统一证据和审计
Operations 统一可观测性
```

### LangGraph 常见问题

```text
图很强，但节点太自由可能变成 goto spaghetti
状态 schema 如果不治理，长期会漂移
interrupt/resume 如果不入图，人工介入不可量化
workflow 很快跑起来，但上线门槛缺失
```

项目应对：

```text
CommandContract 限制节点能力边界
state_schema 固化 tenant/risk/evidence/tool/human 字段
HumanReview -> PATCHED_STATE 入图
release_gates 控制 PoC -> Production
```

## 7. 面试讲法

> 我把项目分成两层：LangGraph-like 负责动态 workflow，CommandAPI 负责大项目能力治理。LangGraph 的 Command API 很适合让节点根据状态决定下一跳，但企业项目里不能让 goto 无约束扩散。所以我设计 CommandContract，要求每个能力声明 bounded context、权限、输入输出、风险、副作用、release gate 和观测字段。这样既能利用 LangGraph 快速构建复杂多 Agent 工作流，又能保持大项目长期可维护。
