# Backup Model Evaluation

Label: `qwen25coder_base_benchv2`
Overall: `6.76` (good)

## Scores

| Stage | Score | Grade |
| --- | ---: | --- |
| model_eval.action_protocol | 0.0 | risk |
| model_eval.grounded_answer | 7.99 | good |
| model_eval.solution_reuse | 4.92 | watch |

## Cases

- `action_workspace_index_v2` action_protocol: 0.0
- `action_resource_registry_v2` action_protocol: 0.0
- `action_research_synthesize_v2` action_protocol: 0.0
- `action_training_prepare_v2` action_protocol: 0.0
- `action_backup_model_train_v2` action_protocol: 0.0
- `action_evidence_ledger_v2` action_protocol: 0.0
- `action_model_route_plan_v2` action_protocol: 0.0
- `action_finish_v2` action_protocol: 0.0
- `grounding_stack_v2` grounded_answer: 10.0
- `grounding_role_v2` grounded_answer: 10.0
- `grounding_endpoints_v2` grounded_answer: 1.5
- `grounding_permissions_v2` grounded_answer: 10.0
- `reuse_surface_v2` solution_reuse: 4.0
- `reuse_incremental_v2` solution_reuse: 4.0
- `reuse_auth_upgrade_v2` solution_reuse: 4.0
- `reuse_evidence_v2` solution_reuse: 4.0
