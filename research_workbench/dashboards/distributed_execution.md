# 分布式执行目录

生成时间：`2026-05-17T04:57:59+00:00`

## 汇总

- 标准 workload：`6`
- 需要 GPU 的 workload：`2`
- 逻辑队列：`6`

## 队列分布

| Queue | Count |
| --- | ---: |
| `evaluation` | 1 |
| `governance` | 1 |
| `ingestion` | 1 |
| `learning` | 1 |
| `training` | 1 |
| `workflow` | 1 |

## Workloads

| Workload | Queue | Priority | CPU | GPU | Memory GB | Expected Outputs |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `learning_run` | learning | normal | 2 | 0 | 4 | knowledge_cards.json, vector_index.jsonl, training_examples.jsonl |
| `benchmark_evaluation` | evaluation | high | 2 | 1 | 12 | model_evaluation_report.json |
| `promotion_gate` | governance | high | 1 | 0 | 2 | model_promotion_decision.json, promotion_report.md |
| `github_crawl_profile` | ingestion | normal | 2 | 0 | 4 | crawl_report.json, solutions/ |
| `training_dispatch` | training | high | 4 | 1 | 16 | adapter/, training_result.json, training_job_manifest.json |
| `agent_workflow` | workflow | normal | 1 | 0 | 2 | run_manifest.json, .agent_events.jsonl |

## 读法

- 这里定义的是未来进入 Ray 执行面的标准任务类型，不代表当前已经真的派发到集群。
- 先把 queue / priority / resource profile 固定下来，可以避免后续接入分布式时把治理逻辑做散。
