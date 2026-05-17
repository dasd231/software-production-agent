# 实验执行队列

生成时间：`2026-05-17T10:06:52+00:00`

## 汇总

- 模型数：`5`

## 待办分布

| Next Action | Count |
| --- | ---: |
| `apply_remediation_then_retrain` | 3 |
| `execute_training_job` | 1 |
| `run_benchmark_evaluation` | 1 |

## 队列

| Model Run | Job | Eval Count | Promotion | Dataset Balance | Next Action | Reason |
| --- | --- | ---: | --- | --- | --- | --- |
| `backup_qwen_grounding_rebalanced_20260516` | queued | 0 |  | 0.0625 ok | `execute_training_job` | training_job_not_completed |
| `backup_quality_20260515` | completed | 0 |  | 0.0145 watch | `run_benchmark_evaluation` | trained_without_precisely_linked_evaluation |
| `backup_protocol_mix_20260516` | completed | 1 | blocked | 0.011 watch | `apply_remediation_then_retrain` | promotion_blocked |
| `backup_qwen_protocol_20260516` | completed | 2 | blocked | 0.011 watch | `apply_remediation_then_retrain` | promotion_blocked |
| `backup_qwen_protocol_hardmix_20260516` | completed | 2 | blocked | 0.0097 watch | `apply_remediation_then_retrain` | promotion_blocked |

## 读法

- 这个页面回答的是“下一步最该做什么”，不是“哪个模型最好”。
- 如果某个已训练模型仍显示 `run_benchmark_evaluation`，说明当前没有可精确挂接到该模型版本的评测证据。
- 如果某个候选模型仍显示 `execute_training_job`，说明数据与 job 已准备好，但训练本身尚未真正完成。
