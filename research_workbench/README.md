# 研究训练工作台

这个目录与主系统解耦，专门用于组织 **Agent 运维 / 项目理解 / 证据链理解** 方向的训练研究。

它不承担真实训练执行；真实训练仍由 `agent/training/` 与未来 Linux 执行面负责。  
它承担的是研究者视角下更需要长期维护的内容：

1. 训练层级与任务边界；
2. 评价指标与实验口径；
3. baseline / variant / ablation 实验登记；
4. 论文阅读与同行方法对照；
5. 将已有训练证据汇总成便于快速查看的工作台。

## 目录说明

```text
research_workbench/
├── README.md
├── training_layers/
│   ├── layer_map.md
│   ├── task_taxonomy.json
│   └── metric_taxonomy.json
├── experiments/
│   ├── experiment_registry.csv
│   └── experiment_template.md
├── dashboards/
│   ├── training_overview.md
│   ├── training_overview.json
│   ├── experiment_comparison.md
│   ├── experiment_comparison.json
│   ├── metric_explainer.md
│   ├── metric_explainer.json
│   ├── promotion_overview.md
│   ├── promotion_overview.json
│   ├── experiment_queue.md
│   ├── experiment_queue.json
│   ├── dataset_evolution.md
│   ├── dataset_evolution.json
│   ├── platform_evolution.md
│   ├── platform_evolution.json
│   ├── distributed_execution.md
│   ├── distributed_execution.json
│   ├── distributed_dispatch_candidates.md
│   ├── distributed_dispatch_candidates.json
│   ├── project_model_program.md
│   ├── project_model_program.json
│   ├── training_platform_blueprint.md
│   ├── training_platform_blueprint.json
│   ├── distillation_overview.md
│   ├── distillation_overview.json
│   ├── training_remediation.md
│   ├── training_remediation.json
│   ├── training_lineage.md
│   └── training_lineage.json
├── literature/
│   ├── paper_reading_log.csv
│   ├── paper_reading_template.md
│   └── taxonomy.md
└── thesis_assets/
    ├── diagrams/
    └── tables/
```

## 使用原则

- **训练层清楚**：先回答“训练什么能力”，再回答“怎么实现创新”。
- **证据链清楚**：任何实验都应能追溯到数据快照、训练任务、评测结果和结论。
- **主流方法留白**：这里先建立规范容器，不提前锁定你后续的 cross-attention、编码器或融合结构。
- **本地设计优先**：研究设计在本地完成，服务器只承担标准化 job 的算力执行。

## 你最常用的入口

| 需求 | 文件 |
| --- | --- |
| 看整体训练分层 | `training_layers/layer_map.md` |
| 看任务分类 | `training_layers/task_taxonomy.json` |
| 看评价指标 | `training_layers/metric_taxonomy.json` |
| 登记一次实验 | `experiments/experiment_registry.csv` |
| 新建实验说明 | `experiments/experiment_template.md` |
| 看当前训练总览 | `dashboards/training_overview.md` |
| 看横向实验对比 | `dashboards/experiment_comparison.md` |
| 看评价指标解释 | `dashboards/metric_explainer.md` |
| 看晋级门禁失败模式 | `dashboards/promotion_overview.md` |
| 看当前最该推进的实验动作 | `dashboards/experiment_queue.md` |
| 看训练数据如何演进 | `dashboards/dataset_evolution.md` |
| 看平台从单机到企业级如何演进 | `dashboards/platform_evolution.md` |
| 看未来 Ray 执行面的标准任务目录 | `dashboards/distributed_execution.md` |
| 看当前哪些真实待办可包装成分布式 job | `dashboards/distributed_dispatch_candidates.md` |
| 看项目大模型的语料、任务和阶段路线 | `dashboards/project_model_program.md` |
| 看四大训练 Plane、路线记忆和可调旋钮 | `dashboards/training_platform_blueprint.md` |
| 看蒸馏教师、教师任务和中段执行链 | `dashboards/distillation_overview.md` |
| 看下一轮训练修复建议 | `dashboards/training_remediation.md` |
| 看训练证据谱系 | `dashboards/training_lineage.md` |
| 记论文 | `literature/paper_reading_log.csv` |

## 刷新工作台

在项目根目录运行：

```bash
python scripts/update_research_workbench.py
```

它会读取：

- `training_runs/`
- `model_runs/`
- `model_evals/`

并刷新：

- `dashboards/training_overview.json`
- `dashboards/training_overview.md`
- `dashboards/experiment_comparison.json`
- `dashboards/experiment_comparison.md`
- `dashboards/metric_explainer.json`
- `dashboards/metric_explainer.md`
- `dashboards/promotion_overview.json`
- `dashboards/promotion_overview.md`
- `dashboards/experiment_queue.json`
- `dashboards/experiment_queue.md`
- `dashboards/dataset_evolution.json`
- `dashboards/dataset_evolution.md`
- `dashboards/platform_evolution.json`
- `dashboards/platform_evolution.md`
- `dashboards/distributed_execution.json`
- `dashboards/distributed_execution.md`
- `dashboards/distributed_dispatch_candidates.json`
- `dashboards/distributed_dispatch_candidates.md`
- `dashboards/project_model_program.json`
- `dashboards/project_model_program.md`
- `dashboards/training_platform_blueprint.json`
- `dashboards/training_platform_blueprint.md`
- `dashboards/distillation_overview.json`
- `dashboards/distillation_overview.md`
- `dashboards/training_remediation.json`
- `dashboards/training_remediation.md`
- `dashboards/training_lineage.json`
- `dashboards/training_lineage.md`

`training_overview` 会同时展示已接收样本数、`min_task_share` 和任务配比状态。  
对于早于该指标引入的历史 run，工作台会从冻结的 dataset snapshot 任务配比中派生同口径信号，避免旧实验因为缺少新字段而在对比中“隐身”。

如果你是在接管早期实验历史，先执行一次：

```bash
python -m agent.training.lineage_backfill --apply
```

它会把可确定的旧训练/评测 lineage 回填出来，并把报告写到 `dashboards/lineage_backfill_report.json`。  
需要人工确认的旧评测挂接关系写在 `lineage_overrides.json`，不要让模糊命名替代证据。

## 当前研究主线

当前工作台面向的主线是：

> 训练一个能够理解项目、理解证据链、并服务于 Agent 运维与项目理解任务的模型体系。

后续真正的方法创新可继续放入这一主线之下，但这里先保持基础设施克制、清晰、可扩展。
