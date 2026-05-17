# 分布式派发候选

生成时间：`2026-05-17T04:57:59+00:00`

## 汇总

- 当前可包装为分布式 job 的待办：`2`

## 按 workload

| Workload | Count |
| --- | ---: |
| `benchmark_evaluation` | 1 |
| `training_dispatch` | 1 |

## 候选

| Model Run | Next Action | Workload | Queue | Priority | CPU | GPU | Reason |
| --- | --- | --- | --- | --- | ---: | ---: | --- |
| `backup_qwen_grounding_rebalanced_20260516` | `execute_training_job` | `training_dispatch` | training | high | 4 | 1 | training_job_not_completed |
| `backup_quality_20260515` | `run_benchmark_evaluation` | `benchmark_evaluation` | evaluation | high | 2 | 1 | trained_without_precisely_linked_evaluation |

## 读法

- 这里把现有实验队列翻译成未来 Ray job 的候选清单。
- `apply_remediation_then_retrain` 之类仍需人类设计的数据修复动作，不会被伪装成可直接派发的 job。
