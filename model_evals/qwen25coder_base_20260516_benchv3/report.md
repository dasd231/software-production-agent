# Backup Model Evaluation

Label: `qwen25coder_base_benchv3`
Overall: `8.41` (excellent)

## Scores

| Stage | Score | Grade |
| --- | ---: | --- |
| model_eval.action_protocol | 7.5 | good |
| model_eval.grounded_answer | 7.32 | good |
| model_eval.solution_reuse | 5.08 | watch |

## Cases

- `protocol_workspace_index_v3` action_protocol: 10.0
- `protocol_resource_registry_v3` action_protocol: 0.0
- `protocol_research_synthesize_v3` action_protocol: 10.0
- `protocol_training_prepare_v3` action_protocol: 10.0
- `protocol_backup_model_train_v3` action_protocol: 10.0
- `protocol_evidence_ledger_v3` action_protocol: 10.0
- `protocol_model_route_plan_v3` action_protocol: 0.0
- `protocol_finish_v3` action_protocol: 10.0
- `grounding_stack_v3` grounded_answer: 10.0
- `grounding_endpoints_v3` grounded_answer: 1.5
- `grounding_permissions_v3` grounded_answer: 10.0
- `reuse_surface_v3` solution_reuse: 4.0
- `reuse_incremental_v3` solution_reuse: 4.0
- `reuse_auth_upgrade_v3` solution_reuse: 4.0
