# Model Promotion Decision

Status: `blocked`
Candidate: `tuned_protocol_benchv2`
Baseline: `base_benchv2`
Benchmark: `backup_model_eval.v2.json`
Candidate overall: `7.16`
Baseline overall: `6.16`
Recommended next step: `adjust_data_or_training_then_re_evaluate`
Recommended actions: `increase_action_protocol_supervision`

## Checks

| Check | Passed | Actual | Expected |
| --- | --- | --- | --- |
| `benchmark_match` | True | backup_model_eval.v2.json | backup_model_eval.v2.json |
| `overall_floor` | True | 7.16 | 7.0 |
| `overall_delta_vs_baseline` | True | 1.0 | 0.0 |
| `candidate_subject_matches_model_version` | True | backup-f4a25b2403a8832a2c01 | backup-f4a25b2403a8832a2c01 |
| `stage_floor:model_eval.action_protocol` | False | 0.0 | 6.0 |
| `stage_regression:model_eval.action_protocol` | True | 0.0 | >= -0.0 |
| `stage_floor:model_eval.grounded_answer` | True | 7.27 | 6.0 |
| `stage_regression:model_eval.grounded_answer` | True | 2.02 | >= -0.0 |
| `stage_floor:model_eval.solution_reuse` | True | 6.82 | 6.0 |
| `stage_regression:model_eval.solution_reuse` | True | 1.9 | >= -0.0 |
