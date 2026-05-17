# Backup Model Evaluation

Label: `tuned`
Overall: `6.69` (good)

## Scores

| Stage | Score | Grade |
| --- | ---: | --- |
| model_eval.action_protocol | 0.0 | risk |
| model_eval.grounded_answer | 7.97 | good |
| model_eval.solution_reuse | 4.41 | watch |

## Cases

- `action_workspace_index` action_protocol: 0.0
- `action_training_prepare` action_protocol: 0.0
- `action_backup_train` action_protocol: 0.0
- `grounding_stack` grounded_answer: 10.0
- `grounding_endpoints` grounded_answer: 7.5
- `grounding_auth` grounded_answer: 5.5
- `reuse_surface` solution_reuse: 4.0
- `reuse_incremental` solution_reuse: 4.0
- `reuse_auth_upgrade` solution_reuse: 4.0
