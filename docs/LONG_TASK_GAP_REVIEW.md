# 超长任务遗漏复盘：从“做了很多”到“闭环更硬”

> 更新时间：2026-05-25  
> 目的：复盘前面超长开发中可能存在的遗漏，把设计型成果推进到可测、可讲、可迭代。

## 已补上的遗漏

### 1. 相似性灾难不应只停留在 GraphRAG 设计

补齐：`agent/semantic_retrieval/`

- 从 query topK 改为 `TaskSemanticFrame -> NeedSlot -> MultiRetriever -> NecessityReranker -> CoverageEvaluator`；
- 通过 Pattern/Keyword/Vector 三路召回；
- 输出 `SemanticContextPackage`；
- 已有专项测试：SaaS 工单、秒杀、登录鉴权。

### 2. 知识图谱需要规格治理，不只是能导出 Cypher

补齐：`agent/graph_runtime/schema_spec.py`

- 明确 node labels、edge types、required properties、indexes、quality gates；
- 增加 `validate_property_graph_against_spec()`，能发现 schema drift；
- 将语义检索和模型训练节点纳入统一 LPG。

### 3. 模型训练需要质量门禁，不只是本地训练脚本

补齐：`agent/local_training/quality.py`

- 增加两类小模型的训练质量计划；
- 增加 `evaluate_training_quality()`，训练样本不足/accuracy 不够时阻断晋级；
- 明确本地 CPU baseline -> shadow -> canary -> rollback-ready 的路线。

## 仍需继续推进的真实缺口

### P0：Semantic Retrieval 与 GraphRAG 融合

当前 `semantic_retrieval` 可独立运行，但还没有把 `TaskSemanticFrame/NeedSlot/CandidateEvidence` 自动写入 property graph。

下一步：

- 新增 `semantic_context_to_property_graph(package)`；
- GraphRAG 支持按 NeedSlot、evidence verification、missing must_have 查询；
- 将低覆盖任务进入训练质量日志。

### P0：Context PV 仍偏控制面

已有切片策略、WAL、checksum、冷热分层、K8s 资源设计，但本地 writer/loader/verifier 仍是下一阶段。

下一步：

- 本地 slice writer；
- manifest pointer 版本切换；
- checksum verify CLI；
- cache hit / slice load latency metrics。

### P1：Diff-native 多 Agent 协同还没工程化

已有口径：PatchProposal、PatchReview、PatchConflict、diff graph。尚未落地代码。

下一步：

- `agent/diff_intelligence/`；
- parse unified diff；
- hunk -> file/symbol/test impact；
- conflict scanner；
- patch graph projection。

### P1：真实数据闭环不足

Scorecard、operations、cloud_native 都有设计和原型，但真实 `.agent_events.jsonl`、CI、成本账、人工满意标签还需要采集。

下一步：

- action 执行自动写 `quality_events.jsonl`；
- CI/test/lint 结果接入 scorecard；
- 用户满意入库前置为方案库沉淀条件；
- 人工介入 L1/L2/L3 分级。

## 当前判断

项目已经不是“空概念堆砌”，但下一阶段必须围绕两件事加强：

1. **图谱化闭环**：所有上下文、证据、训练、质量、人工反馈都能进图；
2. **真实数据闭环**：不要只证明模块能生成计划，要证明模块能用真实反馈变好。
