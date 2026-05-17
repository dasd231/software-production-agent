# 晋级门禁总览

生成时间：`2026-05-17T10:46:36+00:00`

## 汇总

- 决策总数：`5`
- 通过：`0`
- 阻塞：`5`

## 决策明细

| Eval | Model Version | Benchmark | Status | Failed Checks | Recommended Actions |
| --- | --- | --- | --- | --- | --- |
| `qwen25coder_tuned_hardmix_20260516_benchv2_schema` | `backup-6cc03ce09f7d72204aba` | `backup_model_eval.v2.json` | blocked | overall_delta_vs_baseline, stage_floor:model_eval.action_protocol, stage_regression:model_eval.grounded_answer | increase_action_protocol_supervision, rebalance_grounded_answer_supervision, run_regression_focused_ablation, compare_against_baseline_before_more_training |
| `qwen25coder_tuned_hardmix_20260516_benchv3` | `backup-6cc03ce09f7d72204aba` | `backup_model_eval.v3.json` | blocked | overall_delta_vs_baseline, stage_regression:model_eval.action_protocol, stage_floor:model_eval.grounded_answer, stage_regression:model_eval.grounded_answer | rebalance_grounded_answer_supervision, run_regression_focused_ablation, compare_against_baseline_before_more_training |
| `qwen25coder_tuned_protocol_20260516_benchv2` | `backup-08e1a18c01536ed4f030` | `backup_model_eval.v2.json` | blocked | overall_floor, stage_floor:model_eval.action_protocol, stage_regression:model_eval.grounded_answer, stage_floor:model_eval.solution_reuse | increase_action_protocol_supervision, rebalance_grounded_answer_supervision, increase_solution_reuse_supervision, run_regression_focused_ablation, raise_candidate_overall_quality |
| `qwen25coder_tuned_protocol_20260516_benchv2_schema` | `backup-08e1a18c01536ed4f030` | `backup_model_eval.v2.json` | blocked | stage_floor:model_eval.action_protocol, stage_regression:model_eval.grounded_answer, stage_floor:model_eval.solution_reuse | increase_action_protocol_supervision, rebalance_grounded_answer_supervision, increase_solution_reuse_supervision, run_regression_focused_ablation |
| `tuned_protocol_20260516_benchv2` | `backup-f4a25b2403a8832a2c01` | `backup_model_eval.v2.json` | blocked | stage_floor:model_eval.action_protocol | increase_action_protocol_supervision |

## 失败模式

| Check | Count |
| --- | ---: |
| `stage_floor:model_eval.action_protocol` | 4 |
| `stage_regression:model_eval.grounded_answer` | 4 |
| `overall_delta_vs_baseline` | 2 |
| `stage_floor:model_eval.solution_reuse` | 2 |
| `overall_floor` | 1 |
| `stage_floor:model_eval.grounded_answer` | 1 |
| `stage_regression:model_eval.action_protocol` | 1 |

## 读法

- 先看重复出现最多的失败项，再决定下一批数据该补哪类能力。
- 如果 `overall_delta_vs_baseline` 与某个 `stage_regression:*` 同时高频，说明当前训练在换能力，而不是稳定增益。
