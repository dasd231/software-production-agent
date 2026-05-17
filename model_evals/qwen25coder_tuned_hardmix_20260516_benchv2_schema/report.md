# Backup Model Evaluation

Label: `qwen25coder_tuned_hardmix_benchv2_schema`
Overall: `7.73` (good)

## Scores

| Stage | Score | Grade |
| --- | ---: | --- |
| model_eval.action_protocol | 5.88 | watch |
| model_eval.grounded_answer | 6.21 | watch |
| model_eval.solution_reuse | 6.31 | watch |

## Cases

- `action_workspace_index_v2` action_protocol: 6.67
- `action_resource_registry_v2` action_protocol: 0.0
- `action_research_synthesize_v2` action_protocol: 6.67
- `action_training_prepare_v2` action_protocol: 10.0
- `action_backup_model_train_v2` action_protocol: 3.33
- `action_evidence_ledger_v2` action_protocol: 10.0
- `action_model_route_plan_v2` action_protocol: 0.0
- `action_finish_v2` action_protocol: 10.0
- `grounding_stack_v2` grounded_answer: 1.5
- `grounding_role_v2` grounded_answer: 10.0
- `grounding_endpoints_v2` grounded_answer: 4.0
- `grounding_permissions_v2` grounded_answer: 4.0
- `reuse_surface_v2` solution_reuse: 10.0
- `reuse_incremental_v2` solution_reuse: 4.0
- `reuse_auth_upgrade_v2` solution_reuse: 4.0
- `reuse_evidence_v2` solution_reuse: 4.0
