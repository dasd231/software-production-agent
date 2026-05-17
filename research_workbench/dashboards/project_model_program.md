# 项目大模型路线

生成时间：`2026-05-17T10:18:32+00:00`

- 北极星：Maximize repository understanding per token, not repository tokens per prompt.
- 数据源：`6`
- 训练任务：`10`
- Benchmark：`6`
- 阶段：`4`

## 推荐首建

- ID：`repo_memory_v1`
- 目标：Build retrieval-grounded project memory before attempting internet-scale continued pretraining.
- 成功指标：recall_at_5, citation_precision, architecture_summary_faithfulness, tokens_per_correct_answer

## 数据源

| Source | Tier | Modalities | Weight | Governance |
| --- | --- | --- | ---: | --- |
| `open_repo_snapshots` | foundation | source_code, tree, manifests | 0.34 | allowlist_or_permissive_only |
| `repository_docs` | semantic | readme, docs, adr, design_notes | 0.16 | inherit_repo_license |
| `dependency_manifests` | structural | package_manifest, lockfile, build_config | 0.1 | inherit_repo_license |
| `development_traces` | evolution | issues, pull_requests, commit_messages, release_notes | 0.14 | source_platform_policy_plus_repo_gate |
| `official_reference_docs` | external_semantic | api_docs, guides, specs | 0.08 | source_specific_allowlist |
| `execution_signals` | behavioral | tests, ci_configs, examples, fixtures | 0.18 | inherit_repo_license |

## 训练阶段

| Stage | Kind | Objective | Task Mix |
| --- | --- | --- | --- |
| `corpus_foundation` | data | Build a provenance-preserving, de-duplicated repository corpus before any serious training. |  |
| `repo_representation_pretraining` | training | Teach the model to encode project structure before asking it to answer project questions. | repo_structure_mapping:0.22, symbol_grounding:0.2, cross_file_dependency:0.18, architecture_summary:0.16, cross_file_completion:0.24 |
| `retrieval_grounded_understanding` | training | Train a retriever-reader system that finds evidence first and answers second. | evidence_retrieval:0.36, repo_grounded_qa:0.28, issue_to_code_localization:0.18, architecture_summary:0.18 |
| `engineering_reasoning_alignment` | training | Use project evolution traces to reason about intent, impact and repair. | change_impact_reasoning:0.24, test_guided_fixing:0.22, issue_to_code_localization:0.18, repo_grounded_qa:0.18, cross_file_completion:0.18 |

## Benchmark

| Benchmark | Capability | Metrics | Gate |
| --- | --- | --- | --- |
| `coderepoqa` | repository QA | answer_accuracy, evidence_grounding | retrieval_grounded_understanding |
| `coreqa` | cross-file QA | answer_f1, retrieval_quality | retrieval_grounded_understanding |
| `longcodeu` | long-context repository understanding | task_accuracy, long_context_robustness | repo_representation_pretraining |
| `repobench` | repository-level completion | exact_match, edit_similarity | repo_representation_pretraining |
| `crosscodeeval` | cross-file code completion | exact_match, retrieval_gain | repo_representation_pretraining |
| `internal_repo_holdout` | evidence retrieval and architecture QA | recall_at_5, citation_precision, latency_ms | all |

## 读法

- 这不是一次 GPU 任务，而是项目级模型的控制面蓝图。
- 当前最值得先做的是 `repo_memory_v1`：先把项目表示、证据检索和 holdout 评测跑通，再决定何时扩大到互联网级继续预训练。
