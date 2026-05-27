# 百英初试强化：前沿技术、LangGraph 二改与从 0 到企业级交付

> 用途：这是 `BIOYING_PROJECT_INITIAL_INTERVIEW_PITCH.md` 的“增强弹药库”。面试时不用全背，核心是把项目讲成 **可二次开发、可上线、可治理、可审计的科研 AgentOS**，而不是一个会调用 LLM 的 Demo。

## 1. 一句话升级定位

`software-production-agent` 不是一个 ChatBot，也不是简单 Agent 脚本，而是一个面向企业复杂流程的 **Graph-native AgentOS 原型**：

```text
自然语言需求
  -> LangGraph-like 状态图运行时
  -> RAG / Graph-RAG 证据系统
  -> 多 Agent 协同与反同质化治理
  -> Human-in-the-loop 审批
  -> K8s / 队列 / 监控 / 沙盒执行
  -> 企业系统 MES/ERP/LIMS 集成
```

放到百英，它可以演进成“科研实验 Agent 平台”：研究员输入实验目标，系统把 SOP、历史实验、外部文献、库存、MES 工单、安全规则串成一个可审计的执行图。

我的讲法重点不是“我用了 LangGraph”，而是：**我知道 LangGraph 类框架在企业落地时必须二改哪些层。**

---

## 2. 前沿技术雷达：我项目要体现的 7 个方向

| 前沿方向 | 面试关键词 | 项目里的落点 | 百英迁移价值 |
|---|---|---|---|
| Graph-native Agent Runtime | StateGraph、checkpoint、interrupt、time-travel | `agent.workflow` | 实验流程天然是状态机，不能只靠链式 prompt |
| Graph-RAG / Evidence Graph | 实体-关系-证据-结论 | `agent.graph_runtime` | 抗体、宿主、培养条件、表达量、失败原因可做知识图谱 |
| 相似性灾难治理 | collapse alarm、effective rank、diversity retention | `agent.cloud_native.collapse` | SOP/实验记录同质化，必须保证检索证据多样性 |
| Human-in-the-loop Agent | 审批、状态补丁、恢复执行 | workflow interrupt / review | 高风险实验方案必须人工确认，不允许模型直接执行 |
| Agent Observability | run_id、trace_id、decision ledger、SLO | `agent.operations` | 每个实验建议为什么生成、引用了什么、谁批准，都能审计 |
| K8s-aware AI Scheduling | GPU/PV/PodOverhead/CSI/CNI | `agent.cloud_native`、`context_pv` | 长上下文、模型服务、异步 worker 要受资源约束 |
| 业务语义编译 | 自然语言规则 -> 状态机/API/权限 | `agent.rule_compiler` | 把“实验审批规则/库存规则/MES 工单规则”变成可执行契约 |

**面试压缩话术：**

> 我关注的是 Agent 工程的下一层：不是让模型回答问题，而是把模型放进一个带状态、证据、权限、审计和资源调度的企业运行时里。这也是我为什么强调 LangGraph 二改、Graph-RAG、相似性灾难和 K8s 调度。

---

## 3. LangGraph 二改到底改什么

### 3.1 不是“调 LangGraph API”，而是改 6 层

```text
Workflow Spec DSL
  -> State Schema
  -> Node Runtime
  -> Edge / Route Policy
  -> Checkpoint / Replay
  -> Event Ledger / Graph Memory
  -> Ops / Queue / K8s Runtime
```

| 二改层 | 普通用法 | 企业级二改 | 项目表达 |
|---|---|---|---|
| State Schema | messages 放进 state | 增加 risk_level、evidence_budget、tenant_id、tool_permissions、human_review_status | 让状态成为企业契约，不只是聊天上下文 |
| Node Runtime | node 调 LLM/工具 | node 有 timeout、retry、idempotency_key、cost_budget、side_effect_guard | 防止长任务和外部副作用失控 |
| Edge Policy | 固定条件边 | 基于风险、成本、证据质量、collapse alarm 动态路由 | `collapse_alarm -> rewind_blind_fanout` |
| Checkpoint | 保存对话状态 | 支持 replay、canary、state migration、人工 patch 后恢复 | 失败可复盘，流程可回滚 |
| Event Ledger | 普通日志 | decision/action/evidence/reward/human_review 事件化入图 | 支持审计和 Graph-RAG |
| Ops Runtime | 本地进程跑 | 队列 lease、DLQ、Prometheus、K8s Job/SecurityContext | 真正能跑长任务和多人协作 |

### 3.2 我会这样解释“为什么要二改”

> LangGraph 给了状态图、checkpoint、interrupt 这些核心抽象，但企业内部 Agent 要接 MES/ERP/LIMS，节点会有真实副作用。比如提交 MES 工单、扣库存、生成实验批次，这些动作不能因为 Worker 重启就重复执行。所以我会在 LangGraph 之上二改运行时契约：每个节点必须声明幂等键、超时、重试、权限、审计事件和人工审批点。这样 Agent 不是“能跑”，而是“出错也可控”。

### 3.3 面试可画的二改架构图

```text
[Dify / YAML / UI Workflow]
          |
          v
[Workflow Compiler]
  - node contract
  - state schema
  - edge policy
  - permission scope
          |
          v
[LangGraph-like Runtime]
  - checkpoint / replay
  - human interrupt
  - route policy
  - collapse alarm
          |
          v
[Enterprise Control Plane]
  - task queue lease / DLQ
  - event ledger
  - graph memory
  - Prometheus metrics
  - K8s sandbox job
```

---

## 4. 图数据库/Graph-RAG 二改：让 Agent 有“可查询的经验”

普通 RAG 是“查文本片段”，企业 Agent 更需要“查经验结构”。

### 4.1 我项目里的图模型

```text
AgentRun
  -> Decision
  -> Action
  -> Evidence
  -> Reward
  -> HumanReview
  -> PolicyVersion
  -> SimilarityCollapse
  -> DiversityRetention
```

迁移到百英：

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

### 4.2 为什么这比普通向量库更强

- 向量库适合找“语义相似片段”；图适合找“多跳因果链”。
- 科研问题常常不是问一句文献，而是问：**这个抗体在 CHO 细胞失败过几次？失败原因是否和温度/培养基/载体有关？类似项目谁审批过？**
- Graph-RAG 可以把“证据来源、实验条件、结果、人工判断”连起来，减少模型胡编。

### 4.3 面试话术

> 我不是把所有日志塞进向量库，而是把 Agent 的决策过程事件化，再构造成 property graph。这样系统下次遇到类似任务，不只检索文本，还能检索成功路径、失败路径、人工修正路径和风险节点。这就是我理解的 Graph-RAG 二改：从“知识检索”升级为“经验检索”。

---

## 5. 从 0 到企业级交付：5 个阶段怎么讲

这个部分非常重要，因为百英岗位看重“从 0 到 1”和“企业内部落地”。

| 阶段 | 目标 | 我会交付什么 | 通过门槛 |
|---|---|---|---|
| 0. 业务发现 | 搞清真实流程，不急着写 Agent | SOP/数据源/MES/ERP/权限/风险地图 | 画出端到端流程和不可自动化边界 |
| 1. PoC | 证明 LLM + RAG 有价值 | Dify 快速原型、10-20 条真实问题、人工评审表 | 专家认为答案有参考价值 |
| 2. MVP | 从 Demo 变成可控系统 | LangGraph-like 状态机、RAG 评估、人工审批、审计日志 | 关键节点可追溯、失败可恢复 |
| 3. Pilot | 接真实系统但不全自动 | MES/ERP 沙盒、异步队列、权限、监控、K8s 部署 | Shadow mode 跑通，不影响生产 |
| 4. Production | 进入部门流程 | SSO/RBAC、Prometheus/Grafana、DLQ、灰度、回滚、SLO | 有事故预案，有质量指标，有成本账 |
| 5. Platform | 多部门复用 | workflow marketplace、规则编译、领域知识图谱、多租户 | 新流程能快速配置，不推倒重来 |

### 5.1 一句话体现成熟度

> 我会先用 Dify 做 PoC 降低沟通成本，但不会停在 Dify。只要进入真实业务系统，就必须迁到代码级状态机、异步队列、审计日志、权限和监控；否则 Demo 越好看，生产风险越高。

---

## 6. 百英场景的“二改版科研 AgentOS”

### 6.1 运行链路

```text
研究员输入目标
  -> Intent Parser：识别抗体、宿主、表达系统、约束
  -> Evidence Planner：决定查 SOP / 历史实验 / 文献 / 专利 / 库存
  -> RAG + Graph-RAG：返回多样化证据
  -> Collapse Detector：检查证据是否同质化
  -> Protocol Builder：生成实验方案草案
  -> Rule Compiler：把方案转状态机/API契约/权限矩阵
  -> Safety Critic：生物安全、危险试剂、合规检查
  -> Human Review：研究员/PI 审批或修正
  -> MES/ERP Adapter：生成工单、查库存、写回结果
  -> Audit Graph：全链路记录与复盘
```

### 6.2 企业级控制点

| 风险 | 控制机制 |
|---|---|
| LLM 编造 SOP | evidence required + citation verification + graph provenance |
| 检索结果太像 | MMR + effective rank + collapse_alarm |
| 高风险实验误执行 | human interrupt + approval policy |
| MES 工单重复提交 | idempotency_key + outbox + webhook inbox |
| Worker 挂掉 | lease + visibility timeout + DLQ |
| 多 Agent 互相复读 | blind fanout + sparse communication + diversity retention |
| 数据泄露 | tenant_id、RBAC、secret redaction、NetworkPolicy |
| 算力抢占 | K8s resource quota、PodOverhead、priority class、scheduler score |

---

## 7. K8s/云原生怎么体现“高阶”

如果面试官问 K8s，我不要只说会写 Deployment，而是这样讲：

```text
Agent API：无状态 Deployment + HPA
Worker：队列驱动扩缩容 + lease 防重复执行
Vector/Graph DB：StatefulSet + PVC + backup
Sandbox：K8s Job + SecurityContext + NetworkPolicy
Model Gateway：vLLM/Ollama/云模型路由 + 限流
Scheduler 二改：考虑 GPU、PV locality、PodOverhead、队列压力
Context PV：长上下文切片、热/温/冷存储、checksum、prefetch
```

**高阶点：**

- 普通 K8s 只看 CPU/Memory；AI Agent 还要看 GPU 显存、模型冷启动、PV 数据局部性、队列积压、PodOverhead。
- 普通 RAG 只关心召回；长上下文 Agent 要考虑 context slice 的加载延迟和缓存命中。
- 普通任务队列只保证消费；Agent 任务要保证人工审批、幂等、副作用回滚和审计链不断。

---

## 8. 面试强回答：如果问“前沿在哪里？”

> 我觉得前沿不只是用了某个新框架，而是把几个方向组合成可落地系统：第一，Graph-native Agent runtime，让流程具备状态、checkpoint 和 human interrupt；第二，Graph-RAG，把文本检索升级成证据图和经验图；第三，相似性灾难治理，解决多 Agent 和 RAG 容易同质化的问题；第四，云原生 Agent 调度，把 GPU、PV、PodOverhead、队列压力纳入资源决策；第五，业务语义编译，把自然语言规则编译成状态机、API 契约和权限矩阵。  
> 这些能力叠起来，才是企业级 Agent，而不是 Demo 级 Agent。

---

## 9. 面试强回答：如果问“为什么不用现成 LangGraph？”

> 我会用 LangGraph 的核心思想，但企业场景一定要二改。因为百英的科研流程里有真实副作用：提交工单、调用 MES、查询库存、生成实验记录。现成框架解决的是图执行，而我需要补的是企业运行时：节点权限、幂等、审计、人工审批、任务队列、监控告警、状态迁移、失败恢复和数据隔离。我的项目就是围绕这些生产缺口去补控制面的。

---

## 10. 面试强回答：如果问“你怎么从 0 到 1 推动？”

> 我会先找一个高价值但低风险的场景，比如 SOP 问答 + 实验方案草案，不直接自动下发 MES 工单。第一周用 Dify 做 PoC，快速收集研究员反馈；第二阶段把稳定流程迁到 LangGraph-like 状态机，补审计、审批和 RAG 评估；第三阶段接 MES/ERP 沙盒，shadow mode 跑一段时间；最后才进入生产，把高风险动作保留 human-in-the-loop。这样既能快，又不会把 Demo 风险带进生产。

---

## 11. 项目文件证据怎么对应

| 能力 | 项目位置 | 讲法 |
|---|---|---|
| LangGraph-like runtime | `agent/workflow/` | 状态图、条件边、checkpoint/replay 思想 |
| 图数据库二改 | `agent/graph_runtime/` | run/decision/action/evidence/reward 入图 |
| 相似性灾难 | `agent/cloud_native/collapse.py` | 多 Agent / RAG 同质化检测与回滚 |
| 运维可靠性 | `agent/operations/` | health、metrics、queue、DLQ、failover |
| K8s 算法路线 | `agent/cloud_native/k8s_operator.py` | scheduler plugin、etcd policy、CSI/CNI 指标 |
| 规则编译 | `agent/rule_compiler/` | 自然语言规则转系统契约 |
| 长上下文 PV | `agent/context_pv/` | 存储-计算协同的超长上下文方案 |

---

## 12. 速背版：30 秒技术亮点

```text
我这个项目的核心亮点是把 Agent 做成企业运行时：
1. 用 LangGraph-like 状态图替代简单链式调用，支持 checkpoint、interrupt、replay；
2. 把决策、证据、动作、人工修正写入 property graph，形成 Graph-RAG 经验系统；
3. 针对 RAG/多 Agent 相似性灾难做 collapse alarm 和 diversity retention；
4. 用队列 lease、idempotency、DLQ、Prometheus、K8s sandbox 解决生产稳定性；
5. 迁移到百英后，可承载 SOP/文献检索、实验方案生成、安全审查、MES/ERP 工单。
```

---

## 13. 技术依据/可提及参考

- LangGraph Persistence：官方文档说明通过 checkpointer 保存图状态，用于 human-in-the-loop、memory、time travel 和 fault-tolerant execution。  
  https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph Interrupts / Human-in-the-loop：官方文档说明 `interrupt()` 可暂停图执行、保存状态并等待外部输入后恢复。  
  https://docs.langchain.com/oss/python/langgraph/human-in-the-loop
- Microsoft GraphRAG Overview：GraphRAG indexing pipeline 从非结构化文本抽取 entities、relationships、claims，形成可查询图结构。  
  https://microsoft.github.io/graphrag/index/overview/
- Kubernetes Scheduling Framework：官方文档说明调度器可通过插件扩展 PreFilter、Filter、Score、Reserve、Permit、PreBind 等阶段。  
  https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/
- Kubernetes Persistent Volumes：官方文档覆盖 PV/PVC、动态供给、访问模式、回收策略等生产存储语义。  
  https://kubernetes.io/docs/concepts/storage/persistent-volumes/
