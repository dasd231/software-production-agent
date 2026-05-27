# Semantic Retrieval：任务必要性检索模块

> 位置：`agent/semantic_retrieval/`  
> 目标：解决 RAG 的“相似性灾难”——最相似的文本不一定最有用，真正有用的工程知识也许与用户 query 字面并不相似。

## 1. 为什么要做

传统 RAG 常见链路是：

```text
user query -> embedding -> topK chunks -> prompt
```

这会把“文本相似”误当成“任务必要”。例如用户说“做 SaaS 工单系统”，系统可能召回“SaaS 是什么”“工单是什么”，但真正必要的是：

- 多租户隔离：`tenant_id`、查询拦截、缓存隔离；
- RBAC：用户、角色、权限、接口拦截；
- 工单状态机：合法流转、关闭后禁止处理；
- 审计与流转日志：`TicketStatusLog`、`OperatorLog`；
- 测试：跨租户、非法状态流转、并发更新。

本模块把 RAG 升级为：

```text
SemanticRetrievalRequest
  -> TaskParser
  -> TaskSemanticFrame
  -> NeedSlotPlanner
  -> QueryExpander
  -> Pattern/Keyword/Vector MultiRetriever
  -> NecessityReranker
  -> DiversityReranker
  -> CoverageEvaluator
  -> ContextPackageBuilder
  -> SemanticContextPackage
```

最终给上层 Agent 的不是 chunk list，而是结构化上下文包。

## 2. 当前实现

第一版 MVP 已落地，核心文件：

| 层 | 文件 | 作用 |
|---|---|---|
| Schema | `schemas.py` | `TaskSemanticFrame`、`NeedSlot`、`CandidateEvidence`、`SemanticContextPackage` |
| 任务解析 | `task_parser.py` | 识别 SaaS 工单、秒杀、登录鉴权等任务语义 |
| 槽位规划 | `need_slot_planner.py` | 先生成 must_have/important NeedSlot，再检索 |
| 查询扩展 | `query_expander.py` | 结合 slot、task_frame、tech_stack 扩展检索词 |
| 检索 | `retrievers/` | PatternCard、Keyword、Vector-like 三路召回 |
| 重排 | `rerankers/` | 按任务必要性 + 覆盖增益 + 结构/实现价值重排 |
| 覆盖评估 | `evaluators/coverage_evaluator.py` | must_have 槽位缺失/弱证据直接暴露 |
| 上下文打包 | `builders/context_package_builder.py` | 输出实现建议、风险提示、测试建议 |
| 服务入口 | `service.py` | `SemanticRetrievalService.resolve()` |

## 3. 评分逻辑

`NecessityReranker` 不信任 embedding 相似度，而是综合：

```text
final_score =
  necessity_score
+ slot_match_score
+ structure_score
+ implementation_value_score
+ confidence_score
+ coverage_gain_score
+ raw_similarity_score
- superficial_similarity_penalty
```

重点：

- `must_have` 槽位权重更高；
- 有表、实体、状态、接口、事务、测试点的证据得分更高；
- `human_verified/static_verified` 高于 `unknown`；
- “SaaS 是什么”这类泛介绍会被 `superficial_similarity_penalty` 降权；
- `DiversityReranker` 保证不同 NeedSlot 被覆盖，避免上下文被同类证据占满。

## 4. 当前验收

测试文件：`tests/test_semantic_retrieval.py`

已覆盖三类硬场景：

1. `帮我做一个无人门店 SaaS 售后工单系统`
   - 必须召回：多租户隔离、RBAC、工单实体、状态机、流转日志、操作审计、通知、跨租户测试、状态流转测试。
2. `帮我做一个秒杀下单模块`
   - 必须召回：Redis 库存预扣、MQ 异步下单、幂等、限流、超时取消、库存回滚、高并发测试。
3. `帮我做一个登录鉴权模块`
   - 必须召回：用户表、密码加密、登录接口、JWT/Session、权限拦截、白名单、RBAC、Redis 会话、安全测试。

运行：

```bash
cd software-production-agent
python -m pytest tests/test_semantic_retrieval.py -q
```

当前结果：`4 passed`。

## 5. 和 GraphRAG 的关系

`semantic_retrieval` 解决的是“检索前的任务语义规划”和“检索后的任务必要性重排”。  
GraphRAG 解决的是“证据、决策、动作、失败经验之间的结构化关系”。

下一步最自然的融合：

```text
TaskSemanticFrame -> NeedSlot
NeedSlot -> CandidateEvidence
CandidateEvidence -> SemanticContextPackage
SemanticContextPackage -> AgentRun / Decision / Action
```

把这些节点写入 LPG 后，GraphRAG 就能回答：

- 为什么这次上下文选择了多租户模式？
- 哪个 must_have 槽位证据弱？
- 哪类任务经常缺测试点？
- 哪些证据进入上下文后提升了最终交付质量？

## 6. 面试讲法

> 我没有把 RAG 停留在 topK chunk。我做了一个任务必要性检索模块：先把用户需求解析成任务语义框架，再规划完成任务必须具备的 NeedSlot，然后围绕槽位多路召回、按必要性重排、检查 must_have 覆盖，最后输出结构化上下文包。这样能避免“相似但没用”的资料污染上下文。对于百英这种科研/实验 Agent，类似地也可以把“抗体实验方案”解析成 SOP、风险、试剂、设备、审批、MES 工单等槽位，而不是只召回几段相似文献。


## 7. 图谱投影

新增入口：

```python
from agent.semantic_retrieval import semantic_context_to_property_graph, semantic_context_graph_bundle

graph = semantic_context_to_property_graph(package)
bundle = semantic_context_graph_bundle(package)
```

投影后的 LPG 结构：

```text
TaskSemanticFrame -[:HAS_SLOT]-> NeedSlot
CandidateEvidence -[:MATCHED_EVIDENCE]-> NeedSlot
CandidateEvidence -[:SELECTED_FOR]-> SemanticContextPackage
SemanticContextPackage -[:SELECTED_FOR]-> TaskSemanticFrame
SemanticContextPackage -[:EVALUATED_BY]-> QualityMetric
```

这使 GraphRAG 可以追问：

- 这个上下文包为什么选择某条证据？
- 哪些 must_have 槽位被覆盖？
- 哪些证据 verification_level 低？
- 覆盖率是否足够进入自动代码生成？

专项测试已覆盖：`test_semantic_context_projects_to_valid_lpg_and_graph_rag_can_query_need_slots`。
