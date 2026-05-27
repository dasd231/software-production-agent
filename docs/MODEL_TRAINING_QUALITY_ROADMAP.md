# Model Training Quality Roadmap：两类小模型与质量门禁

> 位置：`agent/local_training/quality.py`、`agent/local_training/trainer.py`  
> 目标：把“模型训练”从能训练，升级为可验货、可晋级、可回滚。

## 1. 两类小模型

### 1.1 中间层小模型：规则/算法耗时优化

用途：预测什么时候可以安全跳过昂贵规则、搜索、图查询，什么时候必须执行完整算法。

- 输入：`confidence`、`margin`、`risk_signal`、`candidate_count`、`latency_saved_ms`、`quality_delta`；
- 标签：`1 = 必须跑昂贵规则`，`0 = 可以 shortcut`；
- 约束：高风险动作、安全动作、must_have 槽位弱覆盖时，模型无权跳过规则；
- 当前实现：CPU 透明 logistic baseline，输出 `middle_model_local.json`。

### 1.2 GitHub 语料质量评估模型

用途：给 GitHub 仓库打分，决定进入 `train_now / distill_pool / observe / quarantine`。

- 输入：`lexical_relevance`、`repo_quality`、`freshness`、`governance`、`novelty`、`downstream_utility`；
- 标签：`1 = 可进入训练/蒸馏池`，`0 = 观察或隔离`；
- 硬门禁：license/governance/secret/malware 不通过不能靠模型分数覆盖；
- 当前实现：CPU 透明 logistic baseline，输出 `github_evaluator_local.json`。

## 2. 质量门禁

代码入口：

```python
from agent.local_training import build_training_quality_plan, evaluate_training_quality

plan = build_training_quality_plan()
report = evaluate_training_quality(manifest)
```

当前门槛：

| 模型 | 最少样本 | 最低 accuracy | 额外注意 |
|---|---:|---:|---|
| middle_model | 50 | 0.72 | 重点看 false_skip_rate，错跳过比错执行更危险 |
| github_evaluator | 80 | 0.70 | license/governance 是硬门禁 |

训练成功不等于可上线。必须经过：

```text
local_cpu_baseline -> shadow_inference -> limited_shortcut / offline_ranking_eval
-> server_distillation_or_lora -> canary -> rollback_ready
```

## 3. 数据质量要求

训练数据必须保留：

- 原始 trace 或 repo id；
- feature vector；
- label source；
- timestamp；
- 对 GitHub 样本：license/governance 状态；
- 对语义检索样本：NeedSlot 覆盖报告、证据等级、下游交付质量。

反作弊要求：

- 同组织仓库不能同时进入训练集和 holdout，避免数据泄漏；
- Agent 自己写的测试不能作为唯一质量标签；
- 用户满意是正反馈，但高风险任务还要看事实正确性与运行结果。

## 4. 下一步工程化

1. 将 `SemanticContextPackage.coverage_report` 写入训练样本；
2. 将 GraphRAG 子图的 path quality 作为特征；
3. 将用户“满意/不满意”、人工介入层级、CI、线上错误归因写成统一质量日志；
4. 本地 CPU baseline 稳定后，再上服务器做 LoRA/蒸馏；
5. 每个模型产物挂到 KG：`ModelArtifact -> TRAINED_ON -> TrainingDataset -> EVALUATED_BY -> QualityMetric`。

## 5. 面试讲法

> 我没有把小模型训练理解成“能跑个脚本”。我先做本地透明 baseline，因为当前最重要的是把标签、门禁和质量闭环做对。中间层小模型负责判断昂贵算法什么时候能跳过，但高风险场景永远保留规则兜底；GitHub 语料模型负责筛训练数据，但 license 和安全扫描是硬门禁。模型只有经过 shadow、canary、rollback-ready 才能晋级。这样训练是服务工程质量，而不是为了训练而训练。
