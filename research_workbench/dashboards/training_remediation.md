# 下一轮训练修复建议

生成时间：`2026-05-17T10:18:32+00:00`

## 汇总

- 需要修复建议的模型数：`3`

## 高频动作

| Action | Count |
| --- | ---: |
| `increase_action_protocol_supervision` | 3 |
| `rebalance_grounded_answer_supervision` | 2 |
| `run_regression_focused_ablation` | 2 |
| `compare_against_baseline_before_more_training` | 1 |
| `increase_solution_reuse_supervision` | 1 |
| `raise_candidate_overall_quality` | 1 |

## 按模型查看

| Model Run | Dataset | Balance | Rarest Tasks | Recommended Actions | Current Task Support | Underrepresented Tasks |
| --- | --- | --- | --- | --- | --- | --- |
| `backup_qwen_protocol_20260516` | `dataset-ccd957c9b2d5f2887280ff92` | 0.011 watch | rag_grounded_answer | increase_action_protocol_supervision, increase_solution_reuse_supervision, raise_candidate_overall_quality, rebalance_grounded_answer_supervision, run_regression_focused_ablation | action_protocol_sft:22, rag_grounded_answer:1, solution_reuse_sft:7 | rag_grounded_answer:1, solution_reuse_sft:7 |
| `backup_qwen_protocol_hardmix_20260516` | `dataset-1e4c574e483686c6385a924e` | 0.0097 watch | rag_grounded_answer | compare_against_baseline_before_more_training, increase_action_protocol_supervision, rebalance_grounded_answer_supervision, run_regression_focused_ablation | action_protocol_sft:34, rag_grounded_answer:1 | rag_grounded_answer:1 |
| `backup_protocol_mix_20260516` | `dataset-ccd957c9b2d5f2887280ff92` | 0.011 watch | rag_grounded_answer | increase_action_protocol_supervision | action_protocol_sft:22 |  |

## 读法

- 这里不是自动下训练命令，而是把门禁失败翻译成下一轮数据设计线索。
- 如果某个失败对应任务在当前数据里极少，优先补样本配比；如果样本已经很多仍失败，再考虑 prompt、格式或模型结构问题。
