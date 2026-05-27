# Enterprise Workflow Compiler：LangGraph 二改的企业控制面

> 目标：把 Dify/YAML/业务流程从“可视化编排”升级成 **可审计、可恢复、可上线** 的 LangGraph-like 企业运行契约。  
> 代码位置：`agent/workflow/enterprise.py`  
> Action：`enterprise_workflow_compile`

## 1. 为什么需要这一层

普通 Agent workflow 解决的是“节点如何串起来”。企业级 Agent workflow 还要解决：

- 哪些节点有真实副作用；
- 哪些节点必须人工审批；
- 哪些节点必须带证据引用；
- 哪些节点可以自动重试，哪些只能 outbox/manual replay；
- 状态如何 checkpoint、resume、replay；
- 决策、证据、动作、人工修正如何进入图数据库；
- 从 PoC 到 Production 的上线门槛是什么。

这就是本项目所谓 **LangGraph 二改** 的落点：不是重写 LangGraph，而是在图运行时外面补企业控制面。

## 2. 输入形态

可以接近 Dify/YAML 的简单结构：

```json
{
  "schema": "enterprise_workflow_input.v1",
  "name": "bioying-research-agentos",
  "goal": "抗体表达实验助手",
  "nodes": [
    {"id": "sop_rag", "kind": "rag", "evidence": true},
    {"id": "human_review", "kind": "human_review", "human_gate": true},
    {"id": "mes_erp_adapter", "kind": "mes_erp_adapter", "side_effect": true, "risk": "high"}
  ],
  "edges": [
    {"from": "sop_rag", "to": "human_review"},
    {"from": "human_review", "to": "mes_erp_adapter", "route": "approved"}
  ]
}
```

如果不传 spec，系统会生成默认的百英科研 Agent 工作流：

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

其中 `collapse_guard -> evidence_planner` 的 `collapse_alarm_rewind` 是受控循环，体现 LangGraph-style loop，而不是无约束死循环。

## 3. 编译输出

`compile_enterprise_workflow()` 会输出：

| 输出块 | 用途 |
|---|---|
| `state_schema` | 企业级状态字段：tenant、risk、evidence_budget、tool_permissions、human_review_status |
| `nodes` | 每个节点的 timeout、retry、idempotency、side_effect_guard、evidence_contract、human_interrupt |
| `edges` | 图边和 route 条件 |
| `langgraph_second_modifications` | 明确说明二改 6 层：State、Node、Edge、Checkpoint、Ledger、Ops |
| `graph_memory_projection` | run/decision/evidence/human review/side effect 如何入图 |
| `runtime_controls` | checkpoint、routing、human interrupt、idempotency、observability 策略 |
| `release_gates` | 上线门槛：无 blocker、高风险节点有人审、副作用幂等、RAG 引用、监控/DLQ |
| `assessment` | readiness、score、risk_counts、findings |
| `enterprise_delivery_plan` | 0 到企业级交付 6 阶段 |

## 4. Action 用法

```json
{
  "type": "action",
  "action": "enterprise_workflow_compile",
  "args": {
    "goal": "百英科研 AgentOS",
    "domain": "bio_research",
    "output_path": "plans/enterprise-workflow.json"
  }
}
```

权限：

```text
workflow:compile + workspace:write
```

返回 summary 示例：

```json
{
  "workflow_name": "bioying-research-agentos",
  "node_count": 11,
  "edge_count": 12,
  "score": 100,
  "readiness": "ready_for_pilot",
  "high_risk_count": 2,
  "delivery_stage_count": 6
}
```

## 5. 面试讲法

> 我在项目里补了一个 Enterprise Workflow Compiler。它可以把 Dify/YAML 风格的业务流程编译成 LangGraph-like 企业运行契约：每个节点都有风险等级、证据要求、人工审批、幂等键、重试策略、checkpoint 策略和审计事件。这样我讲 LangGraph 二改不是泛泛而谈，而是明确知道企业流程里哪些节点会有副作用，哪些节点要人审，哪些证据必须入图，最后还能给出从 PoC 到 Production 的上线门槛。

## 6. 百英迁移价值

百英的科研 Agent 不是普通问答，它会接触 SOP、历史实验、库存、MES 工单和安全审批。这个编译层可以把：

```text
实验目标 -> SOP/文献检索 -> 实验方案 -> 安全审查 -> 人工确认 -> MES工单
```

转成可审计状态图，并自动标记：

- `protocol_builder` 必须有证据引用；
- `safety_critic` 是 critical 风险；
- `human_review` 是 interrupt/patch 点；
- `mes_erp_adapter` 是 side-effect 节点，必须有 idempotency 和 outbox/dedup；
- `collapse_guard` 是相似性灾难治理节点，触发后 rewind 到 evidence planner。

这就是从 Demo 到企业级交付之间最容易被忽视、但最能体现工程能力的一层。
## 7. Dify-like Import

新增 `import_dify_workflow()`，用于把 Dify 风格导出的 graph 转成中立 workflow spec。

支持这些形态：

```text
{"graph": {"nodes": [...], "edges": [...]}}
{"workflow": {"graph": {"nodes": [...], "edges": [...]}}}
{"nodes": [...], "edges": [...]}
```

Dify 节点中的 `data.type` 会被映射成企业运行时 kind：

| Dify / UI 节点 | 企业 kind | 控制含义 |
|---|---|---|
| knowledge-retrieval / dataset | `rag` | 自动加 `evidence_contract` |
| llm / agent / protocol | `llm_protocol` | 默认要求证据预算 |
| human-review / approval | `human_review` | 自动加 `human_interrupt` |
| safety / critic / compliance | `safety` | 标记 critical 风险 |
| http-request / tool / webhook | `external_adapter` | 标记 side-effect，高风险，要求幂等 |
| mes / erp / lims / inventory | `mes_erp_adapter` | 企业系统副作用节点 |

这让项目可以讲清楚：**Dify 不是被否定，而是作为 PoC/业务配置入口；进入生产前由编译器提升为可审计运行契约。**

## 8. Graph Projection / Cypher Export

编译结果现在会自动生成：

```text
graph_projection
cypher_seed
```

图投影包含：

```text
EnterpriseWorkflow
StateSchema
WorkflowNode
HighRiskNode
SideEffectNode
HumanInterruptNode
EvidenceRequiredNode
AuditContract
ReleaseGate
DeliveryStage
WorkflowFinding
```

主要边：

```text
HAS_STATE_SCHEMA
HAS_NODE
ROUTES_TO
EMITS_AUDIT
REQUIRES_GATE
HAS_DELIVERY_STAGE
HAS_FINDING
```

这条链路把 LangGraph 二改与图数据库思想接上：workflow 不只是“能执行”，还可以被 Neo4j/Memgraph 查询、审计和复盘。

典型查询问题：

```text
哪些流程有 side-effect 但缺少人工审批？
哪些 protocol 节点要求证据但没有足够引用？
哪些 release gate 阻塞了从 pilot 到 production？
哪些高风险节点经常触发人工 patch？
```

面试表达：

> 我把 workflow contract 投影成 property graph，同时导出 Cypher seed。这样每个节点的风险、审批、证据、审计事件和上线门槛都能被图数据库查询。Graph-RAG 不只是知识库检索，也可以检索 Agent 自己的运行经验和治理记录。

