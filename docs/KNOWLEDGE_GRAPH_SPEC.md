# Agent Knowledge Graph / LPG 规格

> 位置：`agent/graph_runtime/schema_spec.py`  
> 目标：让 GraphRAG 与图数据库不是“有图就行”，而是有可治理的 LPG 规格、索引、质量门禁和 schema drift 校验。

## 1. 定位

项目里的图数据库不是普通知识库。它承担四类记忆：

1. **运行记忆**：`AgentRun -> Decision -> Action -> Artifact`；
2. **证据记忆**：`Action -> Evidence`、`NeedSlot -> CandidateEvidence`；
3. **反馈记忆**：`Reward`、`HumanReview`、`PolicyVersion`；
4. **模型质量记忆**：`ModelArtifact -> TrainingDataset -> QualityMetric`。

这使 GraphRAG 能从“查资料”升级为“查经验链路”：哪个决策引用了什么证据、执行后效果如何、是否被人审修正、后续策略有没有回滚。

## 2. 当前 LPG Schema

代码入口：

```python
from agent.graph_runtime import build_agent_knowledge_graph_spec
spec = build_agent_knowledge_graph_spec()
```

核心节点：

- `AgentRun`：一次 Agent 运行；
- `WorkflowNode`：状态图节点；
- `Decision`：路由/策略选择；
- `Action`：工具/命令/外部系统调用；
- `Evidence` / `CandidateEvidence`：检索、引用、经验；
- `TaskSemanticFrame` / `NeedSlot` / `SemanticContextPackage`：任务必要性检索产物；
- `HumanReview`：人工介入与状态 patch；
- `PolicyVersion`：策略版本、replay、canary、rollback；
- `SimilarityCollapse`：多 Agent 同质化/相似性灾难告警；
- `ModelArtifact` / `TrainingDataset` / `QualityMetric`：小模型训练与质量追踪。

核心边：

- `HAS_SLOT`：任务语义框架拥有知识槽位；
- `MATCHED_EVIDENCE`：证据命中槽位；
- `SELECTED_FOR`：证据/上下文被选入某次任务；
- `EXECUTED` / `PRODUCED` / `CITED`：动作执行、产物、引用；
- `USED_POLICY` / `REWARDED_BY` / `PATCHED_STATE`：策略与反馈闭环；
- `TRAINED_ON` / `EVALUATED_BY`：模型训练质量闭环。

## 3. Schema Drift 校验

代码入口：

```python
from agent.graph_runtime import validate_property_graph_against_spec
report = validate_property_graph_against_spec(graph)
```

它会检查：

- 未注册 node label；
- 未注册 edge type；
- 关键节点缺少 required properties；
- 输出 `agent_knowledge_graph_validation.v1` 报告。

测试文件：`tests/test_quality_and_kg_specs.py`。

## 4. 质量门禁

当前图谱质量规则：

- `CandidateEvidence` 必须声明 `source_type` 和 `verification_level`；
- `unknown` 证据不能单独支撑 must_have NeedSlot；
- GraphRAG 回答必须能追溯 node id 和 edge path；
- 模型晋级必须连接 `TrainingDataset` 和 `QualityMetric`；
- `HumanReview` / `Reward` 只追加不覆盖，保留审计链。

## 5. 百英面试讲法

> 我把图数据库定位成 Agent 经验库，而不是普通知识库。知识库回答“文档里说了什么”，经验库回答“上次为什么这么决策、用了什么证据、结果好不好、有没有人审修正”。迁移到百英，就是把 SOP、文献证据、实验步骤、风险审批、MES 工单、实验结果串成图。后续 GraphRAG 不只是召回 SOP，而是能查出哪类条件失败率高、哪个审批节点经常卡住、哪些方案被专家修正过。
