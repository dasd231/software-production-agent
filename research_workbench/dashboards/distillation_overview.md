# 蒸馏控制面

生成时间：`2026-05-17T10:46:36+00:00`

- 教师模型：`3`
- 教师任务：`5`

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

## 说明

- 当前页面只展示蒸馏控制面目录，不代表已经触发真实教师调用。
- 真实调用层应在 teacher registry 和 task suite 稳定后接入。
