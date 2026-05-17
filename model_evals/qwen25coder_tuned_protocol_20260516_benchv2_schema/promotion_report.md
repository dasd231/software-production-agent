# Model Promotion Decision

Status: `blocked`
Candidate: `qwen25coder_tuned_protocol_benchv2_schema`
Baseline: `qwen25coder_base_benchv2_schema`
Benchmark: `backup_model_eval.v2.json`
Candidate overall: `8.02`
Baseline overall: `8.02`
Recommended next step: `adjust_data_or_training_then_re_evaluate`
Recommended actions: `increase_action_protocol_supervision, rebalance_grounded_answer_supervision, increase_solution_reuse_supervision, run_regression_focused_ablation`

## Checks

| Check | Passed | Actual | Expected |
| --- | --- | --- | --- |
| `benchmark_match` | True | backup_model_eval.v2.json | backup_model_eval.v2.json |
| `overall_floor` | True | 8.02 | 7.0 |
| `overall_delta_vs_baseline` | True | 0.0 | 0.0 |
| `candidate_subject_matches_model_version` | True | backup-08e1a18c01536ed4f030 | backup-08e1a18c01536ed4f030 |
| `stage_floor:model_eval.action_protocol` | False | 5.88 | 6.0 |
| `stage_regression:model_eval.action_protocol` | True | 0.07 | >= -0.0 |
| `stage_floor:model_eval.grounded_answer` | True | 7.1 | 6.0 |
| `stage_regression:model_eval.grounded_answer` | False | -0.89 | >= -0.0 |
| `stage_floor:model_eval.solution_reuse` | False | 5.81 | 6.0 |
| `stage_regression:model_eval.solution_reuse` | True | 0.89 | >= -0.0 |
