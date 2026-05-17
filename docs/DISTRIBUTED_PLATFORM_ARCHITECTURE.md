# 分布式平台演进架构

本项目的企业化扩展不把“用了多少中间件”当成目标，而把 **职责边界清晰、扩展路径稳定、证据链不被破坏** 当成目标。

当前最合理的方向是：

```text
Control Plane
  -> 仍由本项目负责 job spec / manifest / lineage / promotion / audit

Execution Plane
  -> Ray-first：承接 Python 原生的 Agent、学习、评测、训练派发任务

Batch Data Plane
  -> Spark-later：当训练数据规模超过本地 JSONL/Python 处理边界后接入

Streaming Data Plane
  -> Flink-when-needed：当实时、有状态事件流成为真实问题后接入
```

## 1. 为什么先 Ray

当前项目首先遇到的不是“缺少湖仓”，而是：

- 学习任务、评测任务、训练派发任务会越来越多；
- 后续多 Agent 工作流也需要资源隔离、重试与队列治理；
- 这些任务大多仍是 Python 原生工作负载；
- 现有训练控制面已经有 `training_job_spec`、manifest、retry/resume、lineage 等强契约。

因此第一阶段最贴切的企业化补强，是在不推翻控制面的前提下，为这些任务补一个分布式执行面。

## 2. 为什么不是一开始就全量 Spark / Flink

### Spark 的合适位置

Spark 很适合：

- 海量离线样本加工；
- 训练语料清洗、去重、分桶；
- Parquet / 对象存储上的批处理；
- 数据集统计、湖仓与版本化输出。

它不应该负责：

- 模型晋级判断；
- 工作流语义；
- 训练控制面的业务决策。

### Flink 的合适位置

Flink 很适合：

- 持续事件流；
- 状态ful 审计；
- 在线监控；
- 实时特征与告警；
- 事件时间窗口。

但只有当这些问题真正出现时才值得引入。否则会把架构复杂度提前很多。

## 3. 三层边界

| 层 | 负责什么 | 不负责什么 |
| --- | --- | --- |
| Control Plane | 任务定义、证据、晋级门禁、审计 | 不承担算力调度细节 |
| Execution Plane | 任务执行、资源标签、重试、队列 | 不拥有业务真相 |
| Data Plane | 大规模批处理与流处理 | 不决定模型能否晋级 |

这一点很重要：  
**Ray、Spark、Flink 都是底座，不是系统的大脑。**

## 4. 本轮已落地的最小骨架

代码中新增：

- `agent/distributed/backends.py`
- `agent/distributed/manifests.py`
- `agent/distributed/plans.py`
- `agent/training/runners/ray_cluster.py`

当前实现只做：

- 分布式后端能力描述；
- 标准 workload catalog；
- Ray submission contract；
- distributed job manifest；
- 企业化分层路线；
- Ray 训练执行 profile。

它们都遵循 `contract_only` 原则：

- 不启动 Ray；
- 不拉起集群；
- 不触发重算力任务；
- 只把未来执行面该如何接入说清楚。

当前 workload catalog 已经把第一批适合分布式化的任务固定下来：

| Workload | 典型职责 |
| --- | --- |
| `learning_run` | 学习资料构建 |
| `benchmark_evaluation` | 模型评测 |
| `promotion_gate` | 晋级门禁 |
| `github_crawl_profile` | 采集画像 |
| `training_dispatch` | 训练派发 |
| `agent_workflow` | 未来 workflow 执行包络 |

每类 workload 都显式带 queue、priority、默认资源画像、重试策略和预期产物。

如果需要在不真正派发的情况下先审查一次执行包，可以使用 `distributed_job_plan` 生成 preview：

```json
{"type":"action","action":"distributed_job_plan","args":{"job_id":"job-demo","workload":"promotion_gate"}}
```

返回结果会同时包含：

- workload 定义；
- `distributed_job_manifest.v1`；
- `ray_submission_plan.v1`。

研究工作台还会把当前 `experiment_queue` 翻译成 `distributed_dispatch_candidates`：  
只有已经足够明确、未来可直接包装成 job 的动作才会被列入；仍需人工决策的数据修复动作不会被假装成自动派发任务。

## 5. 建议演进顺序

### Phase 1：Distributed Execution v1

- 让 learning / eval / promotion / training-dispatch 都能被描述成分布式 job；
- 接入 resource labels、queue、retry、resume；
- 在工作台展示队列、失败、重试和资源占用。

### Phase 2：Dataset Platform v2

- 数据集产物从 JSONL 逐步增加 Parquet；
- dataset snapshot 引入 schema version、partition、object storage URI；
- 当本地 Python 准备链明显吃力时，再引入 Spark。

当前代码已经先加入 `dataset_storage_profile.v1`：

- 继续以 JSONL 作为当前事实源；
- 预留 `preferred_format`、`object_store_uri`、`partition_hints`；
- 只有在明确切到 Parquet 且具备对象存储位置时，才会把 `spark_ready` 标成真。

### Phase 3：Realtime Operations

- 当模型调用、Agent 事件、审计日志出现稳定实时需求后，再引入 Flink；
- 处理在线状态、告警、聚合、SLA。

## 6. 反模式

- 为了“企业味”同时引入 Ray + Spark + Flink；
- 让分布式框架反向接管 control plane；
- 在 metadata 检查路径上偷偷启动集群；
- 在还没有实时问题时先背上 Flink 的复杂度；
- 还没建立数据版本与治理，就先追求 PB 级规模。

## 7. 对当前项目最直接的价值

这条路线会把项目从：

> 单机可运行的 AI 软件工厂

推进到：

> 有控制面、有执行面、有数据面演进路径的企业级 AI 平台

并且这个升级是渐进式的，不需要推翻你现在已经做好的训练控制面、资源注册表、晋级门禁和研究工作台。
