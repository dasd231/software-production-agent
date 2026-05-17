# Model Promotion Decision

Status: `blocked`
Candidate: `qwen25coder_tuned_hardmix_benchv2_schema`
Baseline: `qwen25coder_base_benchv2_schema`
Benchmark: `backup_model_eval.v2.json`
Candidate overall: `7.73`
Baseline overall: `8.02`
Recommended next step: `adjust_data_or_training_then_re_evaluate`
Recommended actions: `increase_action_protocol_supervision, rebalance_grounded_answer_supervision, run_regression_focused_ablation, compare_against_baseline_before_more_training`

## Checks

| Check | Passed | Actual | Expected |
| --- | --- | --- | --- |
| `benchmark_match` | True | backup_model_eval.v2.json | backup_model_eval.v2.json |
| `overall_floor` | True | 7.73 | 7.0 |
| `overall_delta_vs_baseline` | False | -0.29 | 0.0 |
| `candidate_subject_matches_model_version` | True | backup-6cc03ce09f7d72204aba | backup-6cc03ce09f7d72204aba |
| `stage_floor:model_eval.action_protocol` | False | 5.88 | 6.0 |
| `stage_regression:model_eval.action_protocol` | True | 0.07 | >= -0.0 |
| `stage_floor:model_eval.grounded_answer` | True | 6.21 | 6.0 |
| `stage_regression:model_eval.grounded_answer` | False | -1.78 | >= -0.0 |
| `stage_floor:model_eval.solution_reuse` | True | 6.31 | 6.0 |
| `stage_regression:model_eval.solution_reuse` | True | 1.39 | >= -0.0 |
