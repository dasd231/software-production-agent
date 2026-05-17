# 指标说明

生成时间：`2026-05-17T04:57:59+00:00`

## 项目理解指标

| 指标 | 含义 |
| --- | --- |
| `architecture_qa_accuracy` | 项目结构与设计问答的正确率 |
| `module_localization_accuracy` | 关键模块、入口或实现位置定位正确率 |
| `dependency_relation_accuracy` | 模块关系与依赖判断正确率 |

## 证据质量指标

| 指标 | 含义 |
| --- | --- |
| `evidence_recall` | 关键证据是否被召回 |
| `citation_precision` | 引用证据中真正支持结论的比例 |
| `evidence_chain_completeness` | 证据链是否覆盖结论形成所需的关键环节 |
| `grounded_answer_rate` | 最终回答中带有效证据支撑的比例 |

## Agent 运维指标

| 指标 | 含义 |
| --- | --- |
| `tool_selection_accuracy` | 面对状态与目标时选对工具或动作的比例 |
| `state_diagnosis_accuracy` | 对失败、阻塞和运行状态判断的正确率 |
| `recovery_policy_accuracy` | 失败后给出正确恢复策略的比例 |
| `protocol_validity_rate` | 结构化动作输出满足协议的比例 |

## 泛化指标

| 指标 | 含义 |
| --- | --- |
| `heldout_project_score` | 在未见项目上的综合表现 |
| `cross_domain_transfer_score` | 跨技术栈或跨项目类型迁移能力 |

## 训练效率指标

| 指标 | 含义 |
| --- | --- |
| `trainable_parameter_count` | 新增或可训练参数量 |
| `gpu_hours` | 训练耗时与算力消耗 |
| `score_gain_per_gpu_hour` | 单位算力带来的性能收益 |
| `min_task_share` | 训练集中最稀少任务族的占比，用于暴露极端任务失衡 |

## 备注

- 当前先保留主流、可解释指标；后续创新指标可在此基础上扩展。
- 论文实验中建议区分协议有效性、工具选择能力和证据理解能力，避免混测。
