# Model Promotion Decision

Status: `blocked`
Candidate: `qwen25coder_tuned_hardmix_benchv3`
Baseline: `qwen25coder_base_benchv3`
Benchmark: `backup_model_eval.v3.json`
Candidate overall: `7.94`
Baseline overall: `8.41`
Recommended next step: `adjust_data_or_training_then_re_evaluate`
Recommended actions: `rebalance_grounded_answer_supervision, run_regression_focused_ablation, compare_against_baseline_before_more_training`

## Checks

| Check | Passed | Actual | Expected |
| --- | --- | --- | --- |
| `benchmark_match` | True | backup_model_eval.v3.json | backup_model_eval.v3.json |
| `overall_floor` | True | 7.94 | 7.0 |
| `overall_delta_vs_baseline` | False | -0.47 | 0.0 |
| `candidate_subject_matches_model_version` | True | backup-6cc03ce09f7d72204aba | backup-6cc03ce09f7d72204aba |
| `stage_floor:model_eval.action_protocol` | True | 6.25 | 6.0 |
| `stage_regression:model_eval.action_protocol` | False | -1.25 | >= -0.0 |
| `stage_floor:model_eval.grounded_answer` | False | 4.95 | 6.0 |
| `stage_regression:model_eval.grounded_answer` | False | -2.37 | >= -0.0 |
| `stage_floor:model_eval.solution_reuse` | True | 6.95 | 6.0 |
| `stage_regression:model_eval.solution_reuse` | True | 1.87 | >= -0.0 |
