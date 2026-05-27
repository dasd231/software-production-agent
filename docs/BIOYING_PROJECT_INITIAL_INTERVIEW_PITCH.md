# 百英生物初试项目讲解对齐方案

> 目标：把 `software-production-agent` 讲成“可迁移到生物科研 Agent 平台”的项目，而不是泛泛的软件自动化工具。

## 1. 一句话定位

我的项目是一个面向复杂企业流程的 **多智能体软件生产平台**：底层有 LangGraph-like 工作流、RAG/Graph-RAG 证据链、多 Agent 任务队列与容错、K8s 云原生运行时。迁移到百英场景时，它可以变成“科研实验 Agent 平台”：把文献检索、内部 SOP 检索、实验方案生成、安全审查、MES/ERP 工单转换串成可审计状态机。

## 2. 和百英 JD 的对应关系

| 百英岗位关键词 | 项目里对应能力 | 讲解重点 |
|---|---|---|
| 多智能体平台从 0 到 1 | `agent.workflow`、`agent.operations`、task queue | Supervisor/Planner/Researcher/Coder/Verifier/Sandbox Runner 可映射到科研 Agent |
| LangChain/LangGraph 二次开发 | `agent.workflow`、`agent.graph_runtime` | 自研轻量 StateGraph + route policy + checkpoint + graph memory，不是只会调库 |
| RAG 相似性灾难治理 | `agent.cloud_native.collapse`、`agent.graph_runtime` | pairwise cosine/effective rank/evidence Jaccard 触发 collapse_alarm 和 blind fanout rewind |
| Dify 改造 | workflow spec / action protocol / evidence ledger | 保留 Prompt/知识库资产，改造成代码级状态机和异步任务 |
| K8s 云原生部署 | `agent.sandbox`、`agent.context_pv`、`agent.cloud_native` | SecurityContext、PV 切片、CSI/CNI/PodOverhead 调度指标 |
| MES/ERP 集成 | `agent.rule_compiler`、`resilience`、outbox 思路 | 自然语言规则 -> API 契约/状态机/权限矩阵；对接系统用适配器 + 幂等 |
| 稳定性/工程化 | `agent.operations` | health/readiness/startup、Prometheus、DLQ、lease、idempotency |

## 3. 3 分钟项目讲解稿

我做的项目叫 `software-production-agent`，它本质上是一个面向企业复杂流程的多智能体自动化平台。最开始目标是让 Agent 能理解一个软件项目并自动完成开发任务，但我后来把它抽象成了更通用的 AgentOS：它有状态图编排、证据检索、工具调用、安全监督、云原生执行和评估闭环。

如果放到百英生物场景，我会把它迁移成“科研实验 Agent 平台”。比如研究员输入“我要设计 anti-HER2 抗体表达方案”，系统不是直接让大模型生成答案，而是走一个 LangGraph-like 状态机：需求解析、内部 SOP/RAG 检索、文献检索、实验方案生成、安全审查、库存/MES/ERP 检查、人工确认、最后生成可执行工单。

我在项目里重点做了三块和这个岗位相关的深度：第一是工作流二改，我没有只用普通链式调用，而是做了可 checkpoint、可 replay、可 canary 的图运行时，并把每次决策、动作、证据、人工介入写成 property graph，后续能做 Graph-RAG 和审计。第二是相似性灾难治理，因为科研 protocol 很容易高度雷同，Top-K 检索可能全是相似 SOP。我做了 pairwise cosine、effective rank、evidence Jaccard 的 collapse alarm，触发后会回滚到 blind fanout，并用 diversity-aware retention 保留差异化证据。第三是工程化稳定性，包括 health/readiness/startup、任务队列 lease、visibility timeout、idempotency、DLQ、Prometheus 指标和 K8s 运行时约束。

所以这个项目不是一个简单 ChatBot，而是一个能落到企业内部系统的 Agent 平台雏形。百英如果要从 Dify 工作流演进到深度定制的 LangGraph/LangChain 平台，我认为这套项目经验是可以直接迁移的。

## 4. 5 分钟系统设计展开

### 4.1 架构图口述

```text
Web/企业微信
  -> API Gateway / Auth
  -> Agent Orchestrator (LangGraph-like workflow)
      -> Intent Parser
      -> RAG Service: SOP/历史实验/论文/专利
      -> Tool Registry: ERP库存、MES工单、剂量计算、安全规则
      -> Safety/Critic Agent
      -> Human Review
  -> Event Bus / Task Queue
  -> Graph Memory / Audit Ledger
  -> K8s Worker Pool / Sandbox Job
```

### 4.2 状态机

```text
需求解析
  -> 内部知识检索
  -> 外部文献补充
  -> 实验方案生成
  -> 相似性灾难检测/证据多样性检查
  -> 安全审查
  -> ERP库存/MES工单转换
  -> 人工确认
  -> 输出报告/工单
```

每个节点都有：

```text
entry_condition
exit_action
retry_policy
idempotency_key
event_emit
audit_log
```

### 4.3 RAG 方案

科研文档很容易同质化，所以我不会只做向量 Top-K：

```text
Query Rewrite / HyDE
  -> Metadata Filter: 宿主细胞、抗体类型、批次、表达系统
  -> Hybrid Search: BM25 + Embedding
  -> Rerank
  -> MMR / Semantic Dedup
  -> Graph-RAG: 蛋白-宿主-条件-结果关系
  -> Evidence Budget 注入 LLM
```

项目里可对应：

```text
agent.chains.research
agent.graph_runtime
agent.cloud_native.collapse
```

### 4.4 Dify -> LangGraph 改造思路

我会分三步做：

1. **资产迁移**：导出 Dify Prompt、知识库配置、工作流节点配置，转为 YAML/JSON。
2. **状态机重构**：把同步 workflow 拆成 LangGraph 节点，每个节点有 checkpoint 和事件。
3. **异步执行**：长任务进入 task queue，前端通过 SSE/WebSocket 订阅事件。

稳定性补充：

```text
idempotency_key = thread_id + node_name + input_hash
visibility timeout 防止 Worker 挂死
DLQ 保存 poison task
human interrupt 保护高风险实验方案
```

### 4.5 K8s 部署

```text
Agent API        -> Deployment + HPA
Worker Pool      -> KEDA based on queue depth
RAG/Vector DB    -> StatefulSet + PVC
Graph DB         -> StatefulSet
Sandbox Job      -> K8s Job + SecurityContext + NetworkPolicy
Model Gateway    -> vLLM/Ollama/Cloud Provider route
```

项目里已经具备：

```text
healthz/readyz/startupz/metrics
K8s sandbox plan
Context PV slicing
CNI/CSI/PodOverhead scorecard
Agent task queue lease/DLQ prototype
```

## 5. 被追问时的防守点

### Q1：你是不是只是包装了大模型？

不是。项目核心不是 prompt，而是 **运行时契约**：状态机、证据链、任务队列、权限监督、幂等、DLQ、Graph-RAG、Prometheus 指标。LLM 只是其中一个推理节点。

### Q2：相似性灾难怎么量化？

我会看三类指标：

```text
pairwise_rationale_cosine：Agent 观点是否越来越像
effective_rank：多 Agent 表征是否塌缩
evidence_jaccard：证据来源是否高度重复
```

如果触发阈值，工作流会进入：

```text
collapse_alarm -> rewind_blind_fanout -> diversity-aware retention
```

### Q3：科研场景怎么保证安全？

关键节点必须有人机协同：

```text
实验安全规则检查
禁用条件/危险试剂过滤
高风险方案 interrupt
审计日志与版本回滚
MES 工单幂等提交
```

### Q4：Dify 改造成 LangChain/LangGraph 难点是什么？

难点不是“重写流程”，而是：

```text
保留 Dify 资产
补状态持久化
补异步事件
补权限和审计
补复杂分支与人工介入
```

### Q5：你项目还有哪些不足？

我会诚实说：目前是项目级控制面和原型实现，真实生产还需要接：

```text
真实 Redis/Postgres 队列后端
真实企业 MES/ERP API
真实私有知识库/向量库
真实 K8s 集群和模型网关
真实用户评估数据
```

但优势是架构边界已经清楚，关键风险都被设计成可观测、可测试、可替换的模块。

## 6. 初试时优先讲的 6 个亮点

1. **LangGraph 二改**：不是链式调用，而是状态图 + checkpoint + replay + graph memory。
2. **相似性灾难治理**：用指标检测塌缩，用条件边触发 rewind。
3. **Graph-RAG 证据链**：每个决策能追溯证据、动作、产物、奖励、人工介入。
4. **异步任务可靠性**：lease、visibility timeout、idempotency、DLQ。
5. **云原生落地**：K8s sandbox、PV、CSI/CNI/PodOverhead、Prometheus。
6. **百英业务迁移能力**：科研 SOP/RAG、MES/ERP、实验安全、人机审批。

## 7. 项目讲解最后一句

> 我希望展示的不是“我会调一个 Agent 框架”，而是我理解企业级 Agent 平台真正难的地方：状态、证据、异步、稳定性、安全和业务系统集成。百英的科研场景正好需要这种能力，因为实验流程既需要推理，也需要可追溯和可控。

## 8. 强化版：前沿技术、二改与企业级交付

> 这一节用于补强初试表达：面试官如果追问“前沿在哪里、LangGraph 二改在哪里、从 0 到企业级怎么交付”，就从这里展开。更完整版本见 `docs/BIOYING_FRONTIER_ENTERPRISE_DELIVERY_PLAYBOOK.md`。

### 8.1 前沿技术不是堆名词，而是组合成 AgentOS

我会把项目定位成 **Graph-native AgentOS**，不是单点 Agent Demo：

```text
LangGraph-like 状态图
  + Graph-RAG 证据/经验图
  + 相似性灾难治理
  + Human-in-the-loop 审批
  + K8s/队列/监控/沙盒运行时
  + MES/ERP/LIMS 企业系统适配
```

百英场景下，这套能力对应的是：SOP/历史实验/文献检索、实验方案生成、安全审查、库存/MES 工单、PI 审批和实验结果回写。

### 8.2 LangGraph 二改：我真正改的是运行时契约

普通 LangGraph 关注图执行；企业级 Agent 还要关注节点副作用、权限、审计和恢复。我会把二改讲成 6 层：

| 二改层 | 我会补什么 | 为什么百英需要 |
|---|---|---|
| State Schema | risk_level、evidence_budget、tenant_id、tool_permissions、human_review_status | 实验流程有风险等级、权限和审批 |
| Node Runtime | timeout、retry、idempotency_key、cost_budget、side_effect_guard | MES/ERP 调用不能重复提交 |
| Edge Policy | 基于风险、成本、证据质量、collapse_alarm 动态路由 | 高风险方案要进人工审核或重检索 |
| Checkpoint | replay、canary、state migration、人工 patch 后恢复 | 长流程失败后不能从头再来 |
| Event Ledger | decision/action/evidence/reward/human_review 入图 | 可追溯、可审计、可复盘 |
| Ops Runtime | queue lease、DLQ、Prometheus、K8s Job/SecurityContext | 企业上线需要稳定性兜底 |

一句话：**我不是只会用 LangGraph，而是知道 LangGraph 进入企业流程后缺哪些控制面，并在项目里按这些缺口补模块。**

### 8.3 图数据库二改：从文本 RAG 升级到经验 RAG

普通 RAG 找相似文本；科研 Agent 更需要找多跳关系和历史经验：

```text
ExperimentGoal
  -> Antibody / Host / Vector / Medium / Temperature
  -> SOP / Paper / Patent / HistoricalBatch
  -> ProtocolStep
  -> SafetyRisk
  -> HumanApproval
  -> MESWorkOrder
  -> ExperimentResult
```

我的项目里对应的是 `AgentRun -> Decision -> Action -> Evidence -> Reward -> HumanReview -> PolicyVersion`。这意味着系统下次遇到类似问题，不只查文档，还能查：以前哪个方案失败、为什么失败、谁修正过、哪个 policy 版本更稳。

### 8.4 从 0 到企业级交付路线

| 阶段 | 目标 | 交付物 | 通过门槛 |
|---|---|---|---|
| 业务发现 | 找真实高价值流程 | SOP/数据源/MES/ERP/权限/风险地图 | 画出端到端流程和不可自动化边界 |
| PoC | 快速证明价值 | Dify 原型、10-20 条真实问题、专家评分 | 专家认可答案有参考价值 |
| MVP | 从 Demo 变可控系统 | 状态机、RAG 评估、人工审批、审计日志 | 关键节点可追溯、失败可恢复 |
| Pilot | 接真实系统但 shadow mode | MES/ERP 沙盒、队列、权限、监控、K8s | 不影响生产，能观测全链路 |
| Production | 进入部门流程 | SSO/RBAC、DLQ、灰度、回滚、SLO、成本账 | 有质量指标和事故预案 |
| Platform | 多部门复用 | workflow marketplace、规则编译、领域图谱、多租户 | 新流程可配置，不推倒重来 |

### 8.5 如果问“为什么不用现成框架？”

> 我会用现成框架验证方向，但百英这种科研企业场景不能停留在框架默认能力。因为流程里有真实副作用：MES 工单、库存、实验记录、安全审批。现成框架解决的是图执行，我要补的是企业运行时：权限、幂等、审计、人工审批、失败恢复、监控告警、状态迁移和数据隔离。

### 8.6 30 秒升级版收束

```text
我的项目亮点不是“会调大模型”，而是把 Agent 放进企业运行时：
1. LangGraph-like 状态图支持 checkpoint、interrupt、replay；
2. 决策/证据/动作/人工修正入 property graph，形成 Graph-RAG 经验系统；
3. 用 collapse_alarm 治理 RAG 和多 Agent 的相似性灾难；
4. 用队列、DLQ、Prometheus、K8s sandbox 保证长任务可靠；
5. 迁移到百英后，可以承载 SOP/文献检索、实验方案、安全审查、MES/ERP 工单闭环。
```
## 9. 新增代码证据：Enterprise Workflow Compiler

这一轮我把“LangGraph 二改”进一步落成了代码入口：`agent/workflow/enterprise.py`，并暴露 action：`enterprise_workflow_compile`。

它解决的问题是：Dify/YAML/业务流程只能说明“节点怎么连”，但企业级 Agent 还必须说明“节点能不能上线”。因此编译器会把业务 workflow 转成企业运行契约：

```text
Dify/YAML workflow
  -> Enterprise Workflow Compiler
  -> state_schema
  -> node runtime contract
  -> edge/route policy
  -> checkpoint/human interrupt/idempotency
  -> graph memory projection
  -> release gates
  -> 0-to-production delivery plan
```

### 9.1 现在可以向面试官明确说的实现点

| 能力 | 代码证据 | 面试讲法 |
|---|---|---|
| LangGraph 二改落地 | `compile_enterprise_workflow()` | 我能把普通流程编译成带状态、证据、权限、审计的运行契约 |
| 人工审批节点 | `human_interrupt.required` | 高风险实验和 MES 工单前强制 interrupt |
| 副作用治理 | `side_effect_guard` + `idempotency_key` | MES/ERP 调用不允许重复提交，必须 outbox/dedup |
| 证据要求 | `evidence_contract` | protocol 节点必须引用 SOP/文献/历史实验 |
| 受控循环 | `collapse_alarm_rewind` | 相似性灾难触发后回到 evidence planner，而不是盲目输出 |
| 交付成熟度 | `enterprise_delivery_plan` | 能讲清 PoC -> MVP -> Pilot -> Production -> Platform |

### 9.2 面试强话术

> 我最近给项目补了一个 Enterprise Workflow Compiler。它可以把 Dify 或 YAML 风格的流程，编译成 LangGraph-like 企业运行契约。每个节点会自动标注风险等级、证据要求、人工审批、幂等键、重试策略、checkpoint 策略和审计事件。这样我讲 LangGraph 二改不是抽象概念，而是能落到每个节点能不能自动执行、能不能重试、出了问题怎么恢复、怎么进入图数据库审计。

### 9.3 百英场景的默认工作流

```text
intent_parser
  -> evidence_planner
  -> sop_rag / graph_rag
  -> collapse_guard
  -> protocol_builder
  -> rule_compiler
  -> safety_critic
  -> human_review
  -> mes_erp_adapter
  -> audit_feedback
```

其中：

- `protocol_builder`：必须有证据引用；
- `safety_critic`：critical 风险；
- `human_review`：人工 interrupt 和状态 patch 点；
- `mes_erp_adapter`：真实副作用节点，必须幂等和 outbox/dedup；
- `collapse_guard`：相似性灾难检测，触发 `collapse_alarm_rewind`。

文档见：`docs/ENTERPRISE_WORKFLOW_COMPILER.md`。
### 9.4 新增打通：Dify 导入与图数据库投影

`enterprise_workflow_compile` 现在继续补齐了两端：

```text
Dify graph
  -> import_dify_workflow()
  -> compile_enterprise_workflow()
  -> enterprise contract
  -> graph_projection / cypher_seed
```

这让项目能讲出完整迁移路线：Dify 不被抛弃，而是作为 PoC/业务配置入口；进入生产前，系统会把 Dify 节点提升成企业级运行契约，并投影到图数据库。

面试可以这样说：

> 如果百英已有 Dify 工作流，我不会推倒重来。我会先导入 Dify graph，把 knowledge-retrieval 映射为 RAG 证据节点，把 human-review 映射为 interrupt，把 http/tool/MES/ERP 节点映射为副作用节点，然后自动生成幂等、审批、checkpoint、审计和 release gate。最后把这份 workflow contract 投影到 Neo4j/Memgraph，形成可查询的治理图谱。

这样 “Dify -> LangGraph 二改 -> Graph-RAG 审计资产” 这条链路就完整了。

