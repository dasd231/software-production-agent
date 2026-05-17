# 平台演进路线

生成时间：`2026-05-17T04:57:59+00:00`

- 北极星：control-plane owned evidence, Ray-first execution, data-plane by workload

## 分层

| Plane | Primary | Owns | Entry Condition |
| --- | --- | --- | --- |
| `control_plane` | project-owned | job spec, manifest, lineage, promotion gate, audit |  |
| `execution_plane` | Ray | distributed tasks, actors, resource labels, retryable jobs |  |
| `batch_data_plane` | Spark | lakehouse transforms, large-scale cleaning, dedupe, partitioned datasets | JSONL snapshots become too large or too numerous for local Python preparation |
| `streaming_data_plane` | Flink | event streams, stateful monitoring, online feature updates, audit aggregation | continuous event throughput and stateful real-time decisions become material |

## 推荐引入顺序

- 1. Ray execution contracts and manifests
- 2. Parquet/object-storage dataset snapshots
- 3. Spark batch pipelines for large training corpora
- 4. Flink for genuinely stateful real-time flows

## 明确避免

- Do not replace the control plane with a scheduler.
- Do not introduce Flink before there is a real streaming problem.
- Do not let Spark own model-promotion or workflow semantics.
- Do not start clusters from ordinary metadata inspection paths.
