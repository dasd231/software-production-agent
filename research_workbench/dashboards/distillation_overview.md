# 蒸馏控制面

生成时间：`2026-05-17T15:41:05+00:00`

- 教师模型：`3`
- 教师任务：`5`
- 中段阶段：`5`

## Teachers

| Teacher | Provider | Model | Role | Strengths | Cost |
| --- | --- | --- | --- | --- | --- |
| `openai_reasoning_teacher` | openai | `gpt-4.1` | reasoning_teacher | architecture_summary, change_impact_reasoning, repo_grounded_qa | high |
| `deepseek_reasoning_teacher` | deepseek | `deepseek-reasoner` | reasoning_teacher | repo_grounded_qa, issue_to_code_localization, architecture_summary | medium |
| `local_main_teacher` | main_deepseek | `deepseek-v4-pro` | local_teacher | repo_grounded_qa, symbol_grounding, action_protocol_sft | low |

## Teacher Tasks

| Task | Capability | Requires Evidence | Quality Checks |
| --- | --- | --- | --- |
| `teacher_repo_grounded_qa` | answer project questions from supplied evidence | True | citation_present, answer_supported_by_evidence, no_unsupported_claims |
| `teacher_architecture_summary` | compress repository structure into faithful explanation | True | coverage, faithfulness, citation_present |
| `teacher_symbol_localization` | resolve symbol to definition and rationale | True | path_match, line_match, citation_present |
| `teacher_issue_to_code` | map natural-language issue to likely files and symbols | True | ranked_files_present, evidence_present, unsupported_claims_absent |
| `teacher_change_impact` | predict impacted modules and tests | True | impact_set_present, test_coverage_present, evidence_present |

## Distillation Pipeline

| Stage | Purpose | Default Mode |
| --- | --- | --- |
| `teacher_prompt_batch` | turn governed source examples into evidence-bound teacher prompts | `safe_build_only` |
| `teacher_execution_plan` | preview provider/model calls before any expensive execution | `dry_run` |
| `teacher_execution_run` | execute teachers only after explicit live authorization | `requires_live_authorization` |
| `teacher_output_review` | reject missing, mismatched or unsupported teacher outputs | `evidence_gate` |
| `distillation_export` | emit training_prepare-compatible examples | `write_learning_dir` |

## 说明

- 当前默认路径仍然不会触发真实教师调用；execution plan 的默认 mode 是 dry_run。
- 真实 teacher runtime 已经接上，但只有 mode=live 且 allow_remote=true 时才会远端调用。
- 下一步再做多教师 consensus 与论文级对照。
