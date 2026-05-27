# Cloud-Native Agent Deep Dive: Similarity Collapse, etcd Memory, Kubernetes Scheduling

> 更新时间：2026-05-24  
> 目标：把“多智能体 Agent + 云原生底层”做成可面试、可论文、可工程化的技术路线。  
> 新增控制面：`agent/cloud_native/` + `cloud_native_deep_dive_plan`。

## 0. 这次联网得到的关键判断

这条线最重要的转向是：**多智能体不是越多越好，通信也不是越密越好。** 2026 年几篇新论文都在指向同一个问题：同构 LLM Agent 通过 dense communication / majority vote 很容易把差异磨平，形成语义或表征塌缩。

- `Diversity Collapse in Multi-Agent LLM Systems` 指出，在开放式创意任务里，群体规模继续扩大收益递减，密集通信会加速过早收敛，核心失败来自结构耦合，而不是单个模型不够聪明。来源：[arXiv 2604.18005](https://arxiv.org/abs/2604.18005)
- `Hear Both Sides` 提出 Diversity-Aware Retention：每轮保留和多数派分歧最大的消息，而不是全量广播。来源：[arXiv 2603.20640](https://arxiv.org/abs/2603.20640)
- `Demystifying Multi-Agent Debate` 认为 vanilla MAD 容易输给简单多数投票；更有效的是多样化初始化和校准置信度通信。来源：[arXiv 2601.19921](https://arxiv.org/abs/2601.19921)
- `Representational Collapse` 用 rationale embedding 直接测量塌缩，例如 pairwise cosine 和 effective rank。来源：[arXiv 2604.03809](https://arxiv.org/abs/2604.03809)

所以项目路线不能是“Planner / Coder / Reviewer 三个 prompt 并行投票”这么浅。要做的是：

```text
Blind independent generation
  -> diversity-aware message retention
  -> epistemic graph memory
  -> diversity-aware consensus
  -> collapse alarm / rewind
```

## 1. 解决“相似性灾难”的多智能体技术路线

### 1.1 问题定义

相似性灾难 / diversity collapse：

```text
多个 Agent 名义上协作，但因共享模型、共享提示、共享上下文、共享历史和密集互看，
输出语义越来越像，分歧过早消失，最后得到一个昂贵但单调的“多数意见”。
```

典型失败：

| 失败模式 | 现象 | 项目里的检测方式 |
|---|---|---|
| semantic convergence | 不同角色都在说同一套话 | rationale pairwise cosine 上升 |
| representational collapse | embedding 有效秩下降 | effective rank 低于 Agent 数量 |
| authority lock-in | 强模型/主 Agent 早期观点压制少数假设 | minority hypothesis survival 过低 |
| dense broadcast noise | 全量广播造成冗余和错误前提放大 | evidence Jaccard 过高 |
| premature consensus | 第一轮就“大家一致” | consensus_delay_rounds 过短 |

### 1.2 架构路线

```text
AgentPool 初始化
  - 不同模型 / 不同温度 / 不同检索路径 / 不同工具预算
  - Blind fanout，第一轮禁止互看

Diversity-Aware Retention
  - 不广播全部消息
  - 只传播与多数派距离大、证据不同、假设不同的消息
  - retained message 保留原文，不让 summary 改写少数观点

Epistemic Graph Memory
  - Claim / Evidence / Assumption / Counterexample / AgentRole 入图
  - 共识合并的是证据子图，不是文本拼接
  - 同源证据降低独立性权重

Diversity-Aware Consensus
  - quality + confidence + evidence + diversity_bonus - redundancy_penalty
  - 多数派只增加置信，不能删除少数派
  - 少数观点必须被证伪，而不是被投票淹没

Collapse Alarm / Rewind
  - 相似度过高 + 证据多样性过低时触发
  - 回滚到 blind fanout
  - 强制注入异构模型/工具/检索路径
```

### 1.3 指标

```text
pairwise_rationale_cosine
  Agent rationale embedding 两两相似度；过高说明塌缩。

effective_rank
  rationale embedding 矩阵有效秩；低于 Agent 数说明表征塌缩。

evidence_jaccard
  不同 Agent 证据集合相似度；过高说明只是同源引用。

minority_survival_rate
  少数假设经过 debate 后仍被保留或被明确证伪的比例。

disagreement_value
  少数观点最终被证明有用的比例。

consensus_delay_rounds
  到达共识前经过的轮数；过短可能是早熟共识。
```

### 1.4 和当前项目怎么缝合

```text
agent.graph_runtime
  -> 把 Claim/Evidence/Assumption/Counterexample 写入 property graph

agent.workflow
  -> collapse_alarm 变成条件边，触发 rewind/blind_fanout

agent.operations
  -> 多 Agent failover 时不只补数量，还要保持 role/model/tool diversity

agent.evaluation.automation_scorecard
  -> 把相似性指标纳入“测试自嗨/多数派自嗨”反作弊
```

一句面试话术：

> 我们不是简单堆多个 Agent，而是把多 Agent 的结构耦合当成一类系统性风险来治理。通过 blind fanout、稀疏通信、分歧保留、图证据记忆和 collapse alarm，保证多 Agent 真正扩大搜索空间，而不是昂贵地复读同一个模型的偏见。

## 2. etcd 性能优化：以内存分配与回收为主

### 2.1 最新依据

etcd v3.6.0 在 2025-05-15 发布，官方博客明确提到 v3.6 有主要内存优化：默认 `--snapshot-count` 从 100000 降到 10000，Raft history 更频繁 compact，平均内存消耗至少降低 50%。来源：[etcd v3.6.0 release blog](https://etcd.io/blog/2025/announcing-etcd-3.6/)

官方配置里：

```text
--snapshot-count '10000'
--auto-compaction-retention '0'
--auto-compaction-mode 'periodic'
--quota-backend-bytes '0'
--backend-bbolt-freelist-type 'map'
--max-txn-ops '128'
--max-request-bytes '1572864'
```

来源：[etcd v3.6 configuration](https://etcd.io/docs/v3.6/op-guide/configuration/)

### 2.2 内存模型

etcd 的内存问题不能只看 RSS。要拆成几层：

| 层 | 内存/空间来源 | 回收机制 | 误区 |
|---|---|---|---|
| Raft history | leader 保留已提交 entry | snapshot-count / raft compaction | snapshot-count 越大不一定越稳 |
| MVCC history | revision 历史 | auto compaction | compaction 不等于文件变小 |
| bbolt backend | page / freelist / mmap | defrag | defrag 是重 IO，不该乱跑 |
| Go runtime | heap / short-lived allocations | GOGC / GOMEMLIMIT / request shaping | GOMEMLIMIT 过紧会换 CPU 压力 |
| OS page cache | mmap/page cache | OS reclaim | RSS 高不一定泄漏 |

### 2.3 四个算法策略

#### A. Adaptive Snapshot Count

目标：在 follower 追赶能力和 leader 内存之间平衡。

```text
if raft_memory_pressure_high and follower_lag_low:
    recommend snapshot_count -> 10000
elif slow_followers_need_history and memory_ok:
    cautiously raise snapshot_count
else:
    keep default
```

观测：

```text
process_resident_memory_bytes
go_memstats_heap_inuse_bytes
snapshot_save_total_duration_seconds
etcd_server_leader_changes_seen_total
follower lag
```

#### B. Epoch-based MVCC Compaction

目标：用 revision/time 窗口删除旧版本。

```text
retention = max(min_revision_window, watch_sla_window)
compact_revision = current_revision - retention
run compaction only if no critical watcher requires older revision
```

注意：慢 watcher 需要历史窗口。compaction 太激进会让 watcher 收到 compacted 错误。

#### C. Fragmentation-aware Defrag

目标：只在碎片率确实过高时 defrag。

```text
fragmentation_ratio = (db_total_size - db_in_use_size) / db_total_size

if fragmentation_ratio > 0.35
   and leader_stable
   and qps_low
   and quorum_healthy:
       defrag followers one by one
       defrag or transfer leader last
```

关键区分：

```text
compaction 释放 MVCC 历史

defrag 重写 bbolt 文件，把空洞还给文件系统
```

#### D. Allocation Pressure Guard

目标：从请求模式上降低 Go heap 瞬时分配。

```text
限制大 range / list 请求
控制单事务大小和 batch
分页 expensive list/watch client
设置 GOMEMLIMIT < container memory limit
监控 heap_inuse 与 GC pause
```

### 2.4 项目化方向：EtcdMaintenance Operator

可以做一个 Operator，CRD 叫：

```yaml
apiVersion: ops.agent.dev/v1alpha1
kind: EtcdMaintenancePolicy
spec:
  snapshotCountTarget: 10000
  compaction:
    mode: periodic
    retention: 10h
  defrag:
    fragmentationThreshold: 0.35
    oneMemberAtATime: true
    avoidLeaderFirst: true
  safetyGates:
    requireHealthyQuorum: true
    maxLeaderChangesPerHour: 1
```

控制循环：

```text
observe metrics
  -> compute memory pressure / fragmentation
  -> gate on quorum and latency
  -> recommend or execute compaction/defrag
  -> verify db size, latency and leader stability
  -> emit evidence to scorecard
```

这比“调几个 etcd 参数”更高级：它把维护策略变成可观测、可审计、可回滚的控制器。

## 3. K8s 资源分配调度：算法视角

### 3.1 Scheduler Framework

Kubernetes 调度框架是插件化的。官方文档说明：一次 Pod 调度分成 scheduling cycle 和 binding cycle，扩展点包括 QueueSort、PreFilter、Filter、Score、Reserve、Permit、PreBind、Bind、PostBind 等。来源：[Kubernetes Scheduling Framework](https://v1-34.docs.kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/)

面试里你可以按这个算法链讲：

```text
QueueSort
  -> 按优先级/业务等级/等待时间排序

PreFilter
  -> 预计算 Pod 有效资源请求：containers + init max + pod overhead + DRA + PVC

Filter
  -> 过滤不满足 CPU/Mem/GPU/PV topology/CNI/CRI/taint 的节点

Score
  -> 计算资源利用率、数据亲和、网络容量、存储拓扑、故障域分布

Reserve
  -> 为假定节点预留状态，防止并发调度抢同一资源

Permit
  -> 等待外部资源、gang scheduling 或 device condition

PreBind
  -> 写入 PV binding / ResourceClaim allocation / 网络准备

Bind
  -> Pod 绑定到 Node
```

### 3.2 有效资源公式

```text
effective_request =
  sum(app_container.requests)
  + max(init_container.requests)
  + pod.spec.overhead
  + ResourceClaim / DRA device footprint
  + ephemeral-storage / hugepages / extended resources
```

PodOverhead 是正式的资源账：官方文档说明 Pod overhead 会在调度、Pod cgroup sizing、eviction ranking 中计入。来源：[Kubernetes Pod Overhead](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-overhead/)

### 3.3 PV-controller / ClaimWorker / VolumeWorker

Kubernetes 的 PV controller 不是玄学，它是典型 informer + workqueue + reconcile。

源码中可以看到：

```text
claimQueue
volumeQueue
```

并且注释强调每个队列应该只有一个 worker，尤其 `syncClaim()` 不可重入，否则可能出现两个 claim 绑定同一个 volume 或一个 claim 绑定两个 volume 的竞争。来源：[Kubernetes pv_controller.go v1.36.0](https://github.com/kubernetes/kubernetes/blob/v1.36.0/pkg/controller/volume/persistentvolume/pv_controller.go)

算法理解：

```text
ClaimWorker:
  PVC event -> syncClaim
  if unbound:
      find matching PV or provision dynamically
  if bound:
      verify claimRef / phase / annotations

VolumeWorker:
  PV event -> syncVolume
  if Available:
      wait for claim
  if Bound:
      verify claim still points back
  if Released:
      apply reclaim policy Retain/Delete/Recycle(deprecated)
```

匹配键：

```text
storageClassName
accessModes
volumeMode
capacity
selector
nodeAffinity
claimRef
```

PVC 的 class 规则见官方 PV 文档。来源：[Kubernetes Persistent Volumes](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

### 3.4 WaitForFirstConsumer / CSI / FlexVolume

`WaitForFirstConsumer` 是 PV 调度的关键。官方文档说明：它会延迟 PV binding/provisioning，直到使用该 PVC 的 Pod 出现，然后结合 Pod 的资源需求、node selector、affinity、taints/tolerations 等调度约束选择或供应 PV。来源：[Kubernetes StorageClasses](https://kubernetes.io/docs/concepts/storage/storage-classes/)

```text
Immediate:
  PVC 创建即绑定/供应
  简单，但多 zone / local PV 容易选错拓扑

WaitForFirstConsumer:
  Pod 进入调度后再决定 PV
  正确处理 zone / node affinity / local disk / CSI topology
```

FlexVolume：官方文档标明从 Kubernetes v1.23 起 deprecated，且没有迁移计划和移除计划；现代路线应该走 CSI。来源：[Kubernetes Persistent Volumes - FlexVolume](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

CSI 组件算法位置：

```text
external-provisioner -> 动态创建 PV
external-attacher    -> attach/detach
external-resizer     -> 扩容
external-snapshotter -> 快照
node-driver-registrar -> kubelet 发现 CSI node plugin
CSI node plugin      -> NodePublishVolume / mount
```

### 3.5 StatefulSet

官方定义：StatefulSet 用于管理有状态应用，提供 sticky identity、稳定唯一网络身份、顺序性和唯一性保证。来源：[Kubernetes StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)

对项目的意义：

```text
vLLM shard / etcd / graph-db / vector-db / PV切片服务
都应该优先考虑 StatefulSet + volumeClaimTemplates
```

算法价值：

```text
ordinal -> stable identity
PVC name -> data identity
headless service -> stable network identity
ordered rollout -> safer migration
```

### 3.6 Operator

官方 Operator Pattern：Operator 使用 Custom Resource 管理应用及其组件，并遵循 Kubernetes control loop。来源：[Kubernetes Operator Pattern](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/)

项目里最值得做的 Operator：

```text
AgentTask Operator
  调度多 Agent 子任务、heartbeat、lease、DLQ

EtcdMaintenance Operator
  compaction / defrag / snapshot-count recommendation

ContextPV Operator
  超长上下文 PV 切片、冷热迁移、checksum 校验

ModelPool Operator
  vLLM / Ollama / DeepSeek worker 的扩缩容和健康门控
```

### 3.7 CNI / CRI

Kubernetes 官方说明：Kubernetes 1.3 到 1.36 及以后支持 CNI 插件；CNI 插件需要实现 Kubernetes 网络模型。来源：[Kubernetes Network Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/network-plugins/)

CNI specification 定义了 ADD / DEL / CHECK / STATUS / VERSION / GC 等操作，且要求同一 container 不并发 ADD/DEL，插件要能处理不同 container 的并发。来源：[CNI specification](https://www.cni.dev/docs/spec/)

调度上要把 CNI 变成信号：

```text
CNI/IPAM available IPs
network setup latency
network failure rate
NetworkPolicy cost
node-local DNS / overlay pressure
```

CRI 是 kubelet 和 container runtime 的主协议，官方文档说明 Kubernetes v1.26+ 要求 runtime 支持 CRI v1 API；v1.36 还引入 CRI list streaming alpha，用于大量容器场景绕过单响应大小限制。来源：[Kubernetes CRI](https://kubernetes.io/docs/concepts/architecture/cri/)

### 3.8 AgentWorkloadSchedulingPlugin 设计

项目可以设计一个自定义 scheduler plugin 或二调度器：

```text
PreFilter:
  effective_request = container + init + podOverhead + DRA + PVC
  classify workload = api / verifier / sandbox-runner / vLLM / crawler / training

Filter:
  node allocatable enough
  PV topology matches or provisionable
  CSI capacity available
  RuntimeClass handler exists
  CNI/IPAM above watermark
  DRA ResourceClaim satisfiable

Score:
  data locality for StatefulSet/PV-bound workloads
  GPU/CPU balanced packing for vLLM
  spread orchestrators across zones
  pack short-lived sandbox jobs
  penalize high CSI attach latency / CNI failure nodes

Reserve:
  assume PV binding / ResourceClaim allocation
  reserve internal scheduling state

PreBind:
  commit PV binding / ResourceClaim / annotations
  rollback on failure
```

核心公式：

```text
node_score =
  w_cpu * cpu_fit
  + w_mem * mem_fit
  + w_storage * volume_topology_score
  + w_network * cni_ip_capacity_score
  + w_data * stateful_locality_score
  + w_device * dra_device_score
  - penalties(csi_latency, cni_failure, pod_overhead_pressure, failure_domain_risk)
```

## 4. 新增项目落点

新增：

```text
agent/cloud_native/
  __init__.py
  deep_dive.py

tests/test_cloud_native_deep_dive.py
```

新增 executor action：

```text
cloud_native_deep_dive_plan
```

权限：

```text
cloud:plan + workspace:write
```

示例：

```json
{"type":"action","action":"cloud_native_deep_dive_plan","args":{"focus":"multi-agent-k8s-control-plane","kubernetes_version":"v1.36","output_path":"plans/cloud_native.json"}}
```

输出：

```text
multi_agent_similarity_collapse
etcd_memory_optimization
kubernetes_resource_scheduling
implementation_roadmap
interview_positioning
sources
```

## 5. 下一步工程化

### P0

- 把 collapse metrics 接入 `agent.graph_runtime`：Claim / Evidence / Assumption / Counterexample 入图。
- 在 `agent.workflow` 中加 `collapse_alarm` 条件边。
- 做 `EtcdMaintenancePolicy` CRD 草图。
- 做 `AgentWorkloadSchedulingPlugin` Go skeleton 草图。

### P1

- Prometheus 指标接入：pairwise cosine、effective rank、etcd fragmentation、CSI attach latency、CNI IP pressure。
- ContextPV 和 ModelPool 改成 Operator 风格。
- StatefulSet + volumeClaimTemplates 管理 vLLM shard / graph-db / vector-db。

一句总结：

> 多 Agent 的前沿是“反同质化控制面”；etcd 的前沿是“Raft/MVCC/bbolt/Go GC 联动维护”；K8s 调度的前沿是“CPU/内存之外，把 PodOverhead、PV topology、CSI capacity、DRA device、CNI/IPAM 和 Stateful identity 都纳入评分”。

## 6. 本轮继续开发：从方案到运行时

新增运行时代码：

```text
agent/cloud_native/collapse.py
agent/cloud_native/k8s_operator.py
agent/workflow/project_graph.py  # 接入 collapse_route 条件边
```

### 6.1 collapse_alarm 已接入 workflow

现在 project workflow 多了一段：

```text
choose_action
  -> assess_similarity_collapse
  -- collapse_route --> rewind_blind_fanout | execution_dispatcher
  -> execution_strategy
  -> fast_execute / safe_execute
```

如果 `multi_agent_rationales` 出现高相似、低 effective rank，系统会：

```text
collapse_alarm = true
route_choice = rewind_blind_fanout
build_diversity_retention_decision()
collapse_alarm_handled = true
回到 choose_action 重新规划
```

这一步的意义是：相似性灾难不再只是评价指标，而是能改变工作流路径的运行时条件边。

### 6.2 EtcdMaintenancePolicy CRD 草图

`build_etcd_maintenance_crd()` 生成：

```text
kind: EtcdMaintenancePolicy
spec.snapshotCountTarget
spec.compaction.mode / retention
spec.defrag.fragmentationThreshold
spec.safetyGates.requireHealthyQuorum
status.observedFragmentationRatio
status.recommendation
```

Operator reconcile loop：

```text
watch policy + metrics
  -> observe raft/mvcc/bbolt/go metrics
  -> compute fragmentation and memory pressure
  -> gate on quorum and leader stability
  -> compaction first, defrag second
  -> one member at a time
  -> status + Kubernetes Event + scorecard evidence
```

### 6.3 AgentWorkloadSchedulingPlugin 骨架

`build_agent_scheduler_plugin_skeleton()` 输出 Go 插件骨架，覆盖：

```text
PreFilter
Filter
Score
Reserve
Unreserve
PreBind
```

调度输入包括：

```text
pod_overhead_pressure
volume_topology_score
csi_attach_latency
cni_ip_pressure
runtimeclass_overhead
dra_device_fit
stateful_data_locality
```

这给后续做真实 scheduler plugin / 二调度器留下了清晰入口。

## 7. 本轮收尾：入图 + Prometheus scorecard

### 7.1 collapse_alarm 已进入 property graph

`agent.graph_runtime.ingest` 现在可以识别 workflow trace 中的：

```text
route_key = collapse_route
route_choice = rewind_blind_fanout
similarity_collapse_assessment
diversity_retention_decision
```

并写成图节点：

```text
SimilarityCollapse
QualityRisk
DiversityRetention
```

关系：

```text
(run)-[:HAS_QUALITY_RISK]->(risk:SimilarityCollapse)
(event)-[:DETECTED]->(risk)
(risk)-[:MITIGATED_BY]->(retention:DiversityRetention)
(decision)-[:CONTROLS_DIVERSITY]->(run)
```

Graph-RAG 也能按 `similarity collapse rewind diversity` 这类查询找回相似性塌缩事件。这样它就能服务三件事：

1. 面试：证明多 Agent 反同质化不是口号，有图证据链。
2. 论文：collapse alarm / rewind 可以作为实验事件统计。
3. 生产：某次 Agent 决策为什么回滚到 blind fanout，可以被审计。

### 7.2 Prometheus scorecard 已建模

新增：

```text
agent/cloud_native/metrics.py
build_cloud_native_prometheus_scorecard()
```

指标契约：

```text
agent_cni_ip_pressure_ratio{node,cni,tenant}
agent_csi_attach_latency_seconds_p95{driver,storageclass,zone}
agent_pod_overhead_cpu_pressure_ratio{node,runtimeclass}
agent_pod_overhead_memory_pressure_ratio{node,runtimeclass}
agent_scheduler_storage_topology_reject_total{storageclass,zone,reason}
```

release gate：

```text
critical CNI IP pressure        -> block rollout
critical CSI attach latency     -> block StatefulSet/PV rollout
critical PodOverhead pressure   -> block sandbox-heavy workload packing
```

这些指标也被接进 `agent.operations.monitoring`，和原有 Agent 指标一起进入统一监控契约。
