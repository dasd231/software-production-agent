# GitHub 语料智能层

生成时间：`2026-05-17T17:06:02+00:00`

- 北极星：Continuously turn GitHub into governed project intelligence for a self-owned repo-reading model.
- 学生模型家族：`deepseek_open_family`
- 首轮基座：`deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B`

## 模块

| Module | Owns | Algorithm |
| --- | --- | --- |
| `discovery` | seed queries, web-assisted query expansion, rate-budgeted crawl schedule | seed queries + WebSearch facet expansion + MMR-style diversity selection |
| `recommendation_router` | candidate scoring, hard governance gates, train/distill/benchmark routing | transparent weighted multi-objective ranker with novelty and downstream utility |
| `projectization` | repo memory, symbol index, evidence index, task synthesis | linked project-object construction from code, docs, manifests and tests |
| `distillation` | teacher prompts, teacher outputs, review gates, distillation export | evidence-grounded SFT, then optional multi-teacher consensus |
| `student_training` | recipes, LoRA/QLoRA jobs, ablation, promotion | adapter-first fine-tuning on open DeepSeek-family bases |
| `evaluation_feedback` | intake metrics, dataset metrics, model metrics, resampling signals | offline benchmark gates + corpus feedback resampling |
| `ops_guard` | shared-server admission, job manifests, safe launch, audit | CPU-first ingestion plus conservative GPU preflight |

## 关键算法

- Search：web_assisted_faceted_discovery
- Recommendation：transparent_multi_objective_ranker
- Repo Quality：weighted_structural_quality
- Distillation：evidence_grounded_distillation

## 指标层

| Layer | Metrics |
| --- | --- |
| `discovery` | query_yield, accepted_candidate_rate, novelty_rate, license_allowlist_pass_rate, dedupe_rate |
| `repo_quality` | repo_quality_score, architecture_coverage, docs_present_rate, tests_present_rate, ci_present_rate |
| `dataset` | grounded_required_rate, citation_rate, duplicate_rate, task_diversity, min_task_share |
| `model` | recall_at_5, mrr, citation_precision, answer_f1, faithfulness_score, impact_f1, tokens_per_correct_answer |
| `ops` | crawl_backlog, queue_latency, gpu_admission_pass_rate, foreign_gpu_process_block_rate, job_failure_rate |

## 下一步

- wire query_plan + ranker into the live crawler loop
- persist route decisions and feedback reports as first-class artifacts
- add online query-arm rewards after enough crawl history exists
- upgrade benchmark lane from skeleton to paper-grade comparison
