# 历史训练证据链回填

早期实验产物先于当前训练控制面产生，因此常见三类缺口：

1. 旧 `model_version_manifest.json` 缺少 `dataset_snapshot_id` / `training_job_spec_id`；
2. 旧模型 run 还没有 `training_job_spec.json` / `training_job_manifest.json`；
3. 旧 `model_evaluation_report.json` 缺少 `benchmark_id` 与 `subject.model_version`。

这些缺口会让研究工作台只能“按名字猜”，而无法把训练数据、模型版本、评测结果和晋级决策精确串起来。

## 设计原则

`agent.training.lineage_backfill` 只自动回填**可确定事实**：

| 信息 | 回填方式 |
| --- | --- |
| `dataset_snapshot_id` | 由 `training_dir/dataset_snapshot_manifest.json` 精确读取 |
| `training_job_spec.json` | 由旧 `backup_training_spec.json` + dataset snapshot 重建 |
| `training_job_manifest.json` | 由重建后的 job spec 与历史训练状态重建 |
| `benchmark_id` | 由评测 case-id 与 `benchmarks/*.json` 的完整签名精确匹配 |

评测到模型版本的挂接 **不做模糊猜测**。  
这部分必须写入 `research_workbench/lineage_overrides.json`，因为一旦把旧评测错挂到错误模型，后续实验结论会一起被污染。

## 使用方式

先做 dry-run：

```powershell
$env:PYTHONPATH='.'
python -m agent.training.lineage_backfill
```

确认摘要后再真正写入：

```powershell
$env:PYTHONPATH='.'
python -m agent.training.lineage_backfill --apply
python scripts/update_research_workbench.py
```

写入后会刷新：

- 旧模型 run 中缺失的 job spec / job manifest；
- 模型版本 manifest 中缺失的 lineage 字段；
- 旧评测报告中的 `benchmark_id`；
- 显式 override 指定的 `subject.model_version`；
- 可生成的 `model_promotion_decision.json`；
- `research_workbench/dashboards/lineage_backfill_report.json`。

## override 文件

示例：

```json
{
  "schema": "lineage_backfill_overrides.v1",
  "evaluation_links": [
    {
      "evaluation_run": "qwen25coder_tuned_hardmix_20260516_benchv3",
      "model_run": "backup_qwen_protocol_hardmix_20260516",
      "baseline_evaluation_run": "qwen25coder_base_20260516_benchv3"
    }
  ]
}
```

如果某个旧评测无法被可靠确认，应让它继续留在 `unresolved_evaluations`，而不是为了“看起来完整”强行挂接。
