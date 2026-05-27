from __future__ import annotations

from typing import Any

from agent.cloud_native.k8s_operator import build_cloud_native_operator_assets
from agent.cloud_native.metrics import build_cloud_native_prometheus_scorecard


RESEARCH_SOURCES: list[dict[str, str]] = [
    {
        "topic": "multi_agent_similarity_collapse",
        "title": "Diversity Collapse in Multi-Agent LLM Systems: Structural Coupling and Collective Failure in Open-Ended Idea Generation",
        "url": "https://arxiv.org/abs/2604.18005",
        "signal": "dense communication and structural coupling can accelerate premature convergence; preserve independence and disagreement",
    },
    {
        "topic": "multi_agent_similarity_collapse",
        "title": "Hear Both Sides: Efficient Multi-Agent Debate via Diversity-Aware Message Retention",
        "url": "https://arxiv.org/abs/2603.20640",
        "signal": "selectively propagate messages that maximize disagreement instead of broadcasting all messages",
    },
    {
        "topic": "multi_agent_similarity_collapse",
        "title": "Demystifying Multi-Agent Debate: The Role of Confidence and Diversity",
        "url": "https://arxiv.org/abs/2601.19921",
        "signal": "diverse initialization and calibrated confidence communication improve debate over vanilla MAD",
    },
    {
        "topic": "multi_agent_similarity_collapse",
        "title": "Representational Collapse in Multi-Agent LLM Committees: Measurement and Diversity-Aware Consensus",
        "url": "https://arxiv.org/abs/2604.03809",
        "signal": "measure pairwise rationale similarity and effective rank; apply diversity-aware consensus",
    },
    {
        "topic": "etcd_memory",
        "title": "Announcing etcd v3.6.0",
        "url": "https://etcd.io/blog/2025/announcing-etcd-3.6/",
        "signal": "v3.6 reduced default snapshot-count to 10000 and reports major memory reduction from more frequent raft compaction",
    },
    {
        "topic": "etcd_memory",
        "title": "etcd v3.6 Configuration options",
        "url": "https://etcd.io/docs/v3.6/op-guide/configuration/",
        "signal": "snapshot-count, auto-compaction-mode, auto-compaction-retention and backend quota are operational levers",
    },
    {
        "topic": "etcd_memory",
        "title": "etcd v3.6 Metrics",
        "url": "https://etcd.io/docs/v3.6/metrics/",
        "signal": "watch process/go/backend metrics; snapshot latency and file descriptors can indicate instability",
    },
    {
        "topic": "k8s_scheduling",
        "title": "Kubernetes Dynamic Resource Allocation",
        "url": "https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/",
        "signal": "DRA is stable in v1.35 and updates ResourceClaim allocation through the scheduler path",
    },
    {
        "topic": "k8s_scheduling",
        "title": "Kubernetes Scheduling Framework",
        "url": "https://v1-34.docs.kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/",
        "signal": "QueueSort, PreFilter, Filter, Score, Reserve, Permit, PreBind and Bind form extension points for scheduling algorithms",
    },
    {
        "topic": "k8s_storage",
        "title": "Kubernetes StorageClasses",
        "url": "https://kubernetes.io/docs/concepts/storage/storage-classes/",
        "signal": "WaitForFirstConsumer delays binding/provisioning until pod scheduling constraints are known",
    },
    {
        "topic": "k8s_storage",
        "title": "Kubernetes Persistent Volumes",
        "url": "https://kubernetes.io/docs/concepts/storage/persistent-volumes/",
        "signal": "PV/PVC matching uses access modes, volume mode, class and node affinity; FlexVolume is deprecated; CSI is the standard path",
    },
    {
        "topic": "k8s_storage",
        "title": "k8s.io/kubernetes persistentvolume package",
        "url": "https://pkg.go.dev/k8s.io/kubernetes@v1.36.0/pkg/controller/volume/persistentvolume",
        "signal": "PersistentVolumeController synchronizes PVs and PVCs with informers and work queues",
    },
    {
        "topic": "k8s_runtime",
        "title": "Kubernetes Pod Overhead",
        "url": "https://kubernetes.io/docs/concepts/scheduling-eviction/pod-overhead/",
        "signal": "Pod overhead is added to container requests during scheduling and cgroup sizing",
    },
    {
        "topic": "k8s_runtime",
        "title": "Kubernetes Container Runtime Interface",
        "url": "https://kubernetes.io/docs/concepts/architecture/cri/",
        "signal": "CRI is the gRPC interface between kubelet and container runtimes; v1 CRI API is required in modern Kubernetes",
    },
    {
        "topic": "k8s_network",
        "title": "Kubernetes Network Plugins",
        "url": "https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/network-plugins/",
        "signal": "Kubernetes relies on CNI-compatible network plugins to implement the network model",
    },
    {
        "topic": "k8s_network",
        "title": "CNI Specification",
        "url": "https://www.cni.dev/docs/spec/",
        "signal": "CNI defines ADD, DEL, CHECK, STATUS, VERSION and GC operations",
    },
    {
        "topic": "k8s_workloads",
        "title": "Kubernetes StatefulSets",
        "url": "https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/",
        "signal": "StatefulSet provides stable identity, ordered rollout and per-replica volumeClaimTemplates",
    },
    {
        "topic": "k8s_extension",
        "title": "Kubernetes Operator Pattern",
        "url": "https://kubernetes.io/docs/concepts/extend-kubernetes/operator/",
        "signal": "Operators combine custom resources and controllers to encode operational knowledge in reconcile loops",
    },
]


def build_multi_agent_similarity_collapse_route() -> dict[str, Any]:
    return {
        "schema": "multi_agent_similarity_collapse_route.v1",
        "problem": {
            "name": "similarity_disaster_or_diversity_collapse",
            "definition": "多个 Agent 名义上协作，但因共享模型、共享提示、共享上下文和密集互看，输出语义越来越像，分歧提前消失，最终得到一个昂贵但单调的多数意见。",
            "failure_modes": [
                "semantic_convergence: 不同角色复述同一框架",
                "representational_collapse: rationale embedding 的有效秩下降",
                "authority_lock_in: 强模型/主 Agent 的早期观点压制少数假设",
                "dense_broadcast_noise: 每轮全量广播制造冗余并放大错误前提",
                "consensus_premature_stop: 看到表面一致就停止探索",
            ],
        },
        "route": [
            {
                "layer": "agent_pool_initialization",
                "technique": "diversity_aware_initialization",
                "implementation": [
                    "候选答案先 blind fanout，禁止互看",
                    "按 embedding 距离 / citation Jaccard / tool path 差异挑选初始 Agent 子集",
                    "同一任务至少保留一个 adversarial verifier 和一个 minority hypothesis keeper",
                ],
                "why": "先让正确或罕见假设有机会进入池子，再讨论；否则后续 debate 只是同质答案互相确认。",
            },
            {
                "layer": "communication_topology",
                "technique": "sparse_and_delayed_message_passing",
                "implementation": [
                    "默认不做全图广播；使用 ring / hub-spoke / random-k sparse topology",
                    "每轮只传播 disagreement 最大且与多数派距离最大的消息",
                    "关键分歧以 message_id 传递，保留原文，禁止 summary 改写少数观点",
                ],
                "why": "降低结构耦合，避免所有 Agent 过早吸收同一个上下文。",
            },
            {
                "layer": "memory_and_graph",
                "technique": "epistemic_graph_memory",
                "implementation": [
                    "将 Claim / Evidence / Assumption / Counterexample / AgentRole 写入 property graph",
                    "共识不是合并文本，而是合并有证据边的 claim 子图",
                    "如果两个 Agent 引用同源证据，降低独立性权重",
                ],
                "why": "用图结构保存分歧和证据血缘，而不是把所有上下文压成一个 prompt。",
            },
            {
                "layer": "consensus",
                "technique": "diversity_aware_consensus",
                "implementation": [
                    "score = quality + calibrated_confidence + evidence_support + diversity_bonus - redundancy_penalty",
                    "多数派只能提升置信，不能删除少数派；少数派需要明确反证才能被淘汰",
                    "最终答案必须附带 survived_alternatives 和 rejected_assumptions",
                ],
                "why": "把分歧视为资产，而不是噪音。",
            },
            {
                "layer": "runtime_gate",
                "technique": "collapse_alarm_and_rewind",
                "implementation": [
                    "pairwise_similarity > threshold 且 evidence_diversity 低时触发 collapse_alarm",
                    "回滚到 blind fanout 阶段，强制注入异构模型/工具/检索路径",
                    "对高风险任务要求 disagreement_budget >= 2 才能进入执行",
                ],
                "why": "把相似性灾难变成可观测、可中断、可恢复的运行时事件。",
            },
        ],
        "metrics": {
            "pairwise_rationale_cosine": "Agent rationale embedding 的平均两两相似度；越高越危险",
            "effective_rank": "rationale embedding 矩阵有效秩；低于 Agent 数说明表示塌缩",
            "evidence_jaccard": "不同 Agent 证据集合的 Jaccard 相似度；过高说明证据源同质",
            "minority_survival_rate": "少数假设经过 debate 后仍被保留/反驳的比例",
            "disagreement_value": "少数观点最终被证明有用的比例",
            "consensus_delay_rounds": "到达共识前经过的轮数；过短可能是早熟共识",
        },
        "project_fit": [
            "接入 agent.graph_runtime：把 Agent 输出写成 Claim/Evidence/Assumption 图",
            "接入 agent.operations：heartbeat/failover 时保留 role diversity，不只补数量",
            "接入 workflow optimizer：把 collapse_alarm 作为条件边，触发 rewind/fanout",
            "接入 scorecard：把相似性指标作为质量反作弊指标",
        ],
    }


def build_etcd_memory_optimization_plan() -> dict[str, Any]:
    return {
        "schema": "etcd_memory_optimization_plan.v1",
        "target": "etcd v3.6+ memory allocation / reclamation policy for Kubernetes control-plane stability",
        "mental_model": {
            "raft_history": "--snapshot-count 控制多少已提交 Raft entry 在内存中保留；值越高 follower 追赶友好但内存越大。",
            "mvcc_history": "MVCC revision 历史需要 compaction 回收逻辑历史，否则读写和存储都会退化。",
            "bbolt_backend": "压缩释放逻辑 key 历史，但 bbolt 文件空洞需要 defrag 重写数据库文件才能归还空间。",
            "go_runtime": "Go heap 受 GOGC/GOMEMLIMIT 和 live heap 影响；频繁 watcher、range 和大事务会放大短期分配。",
            "os_page_cache": "mmap/page cache 可能表现为 RSS 增长，不能简单等同泄漏，需要结合 backend size/free in use 判断。",
        },
        "algorithms": [
            {
                "name": "adaptive_snapshot_count",
                "goal": "在 follower 追赶能力和 leader 内存之间找平衡",
                "pseudocode": [
                    "if raft_memory_pressure_high and follower_lag_low: lower snapshot_count toward 10000",
                    "if slow_followers_need_history and memory_ok: raise snapshot_count cautiously",
                    "never tune without watching proposal latency, snapshot duration and follower lag",
                ],
                "risk": "过低会增加 snapshot 传输；过高会推高内存。",
            },
            {
                "name": "epoch_based_mvcc_compaction",
                "goal": "按 revision/time 窗口周期性删除旧版本",
                "pseudocode": [
                    "retention = max(min_revision_window, watch_sla_window)",
                    "compact_revision = current_revision - retention",
                    "run compaction only if no critical watcher requires older revision",
                ],
                "risk": "过激 compaction 会让慢 watcher 收到 compacted 错误。",
            },
            {
                "name": "fragmentation_aware_defrag",
                "goal": "只在碎片真正影响空间/性能时 defrag，避免盲目定时 defrag",
                "pseudocode": [
                    "fragmentation_ratio = (db_total_size - db_in_use_size) / db_total_size",
                    "if fragmentation_ratio > 0.35 and leader_stable and qps_low: defrag followers one by one",
                    "move leader last or trigger safe leadership transfer before leader defrag",
                ],
                "risk": "defrag 是重 IO 操作，错误时机会扩大控制面抖动。",
            },
            {
                "name": "allocation_pressure_guard",
                "goal": "从 Go runtime 和请求模式降低瞬时分配",
                "pseudocode": [
                    "cap large range limit and batch write size",
                    "shed or page expensive list/watch clients",
                    "set GOMEMLIMIT below container limit and alert on go_memstats_heap_inuse_bytes growth",
                ],
                "risk": "GOGC/GOMEMLIMIT 调太紧会增加 CPU GC 开销。",
            },
        ],
        "metrics_to_watch": [
            "process_resident_memory_bytes",
            "go_memstats_heap_alloc_bytes",
            "go_memstats_heap_inuse_bytes",
            "etcd_mvcc_db_total_size_in_bytes",
            "etcd_mvcc_db_total_size_in_use_in_bytes",
            "etcd_debugging_mvcc_db_total_size_in_bytes or version-specific replacement",
            "snapshot_save_total_duration_seconds",
            "etcd_server_leader_changes_seen_total",
            "etcd_disk_wal_fsync_duration_seconds_bucket",
            "etcd_disk_backend_commit_duration_seconds_bucket",
        ],
        "operator_policy": {
            "control_loop": "Observe memory/db metrics -> decide compaction/defrag/snapshot-count recommendation -> gate on leader stability -> execute one member at a time -> verify quorum/latency.",
            "safety_gates": [
                "cluster has healthy quorum",
                "no recent leader-change storm",
                "backend commit p99 below threshold",
                "defrag one member at a time",
                "snapshot backup exists before aggressive maintenance",
            ],
        },
    }


def build_k8s_resource_scheduling_plan(*, kubernetes_version: str = "v1.36") -> dict[str, Any]:
    return {
        "schema": "k8s_resource_scheduling_algorithm_plan.v1",
        "kubernetes_version": kubernetes_version,
        "scheduler_framework": {
            "cycle": [
                "QueueSort",
                "PreFilter",
                "Filter",
                "PostFilter",
                "PreScore",
                "Score",
                "NormalizeScore",
                "Reserve",
                "Permit",
                "PreBind",
                "Bind",
                "PostBind",
            ],
            "resource_formula": "effective_request = sum(container.requests) + pod.spec.overhead + pod_level_resources_delta + extended_resource_or_DRA_claims",
            "score_formula": "node_score = w_cpu*fit + w_mem*fit + w_storage*volume_topology + w_network*cni_ip_capacity + w_data*stateful_locality - penalties",
        },
        "storage_control_plane": {
            "pv_controller": {
                "workers": [
                    {
                        "name": "ClaimWorker",
                        "role": "消费 PVC workqueue，执行 syncClaim：查找/绑定已有 PV，触发动态 provision，处理 Lost/Pending/Bound 状态。",
                    },
                    {
                        "name": "VolumeWorker",
                        "role": "消费 PV workqueue，执行 syncVolume：维护 Available/Bound/Released/Failed，处理 reclaim policy 与 claimRef。",
                    },
                ],
                "matching_keys": ["storageClassName", "accessModes", "volumeMode", "capacity", "selector", "nodeAffinity", "claimRef"],
                "binding_modes": {
                    "Immediate": "PVC 创建后立即绑定/供应，简单但多 zone/本地盘容易选错拓扑。",
                    "WaitForFirstConsumer": "等 Pod 进入调度后结合 nodeSelector/affinity/taints/resources/storage topology 决策。",
                },
            },
            "flexvolume": {
                "status": "deprecated",
                "algorithmic_position": "历史 exec 插件模型，缺少 CSI 标准化控制器侧能力；新系统只保留兼容理解，不作为设计目标。",
            },
            "csi": {
                "components": ["external-provisioner", "external-attacher", "external-resizer", "external-snapshotter", "node-driver-registrar", "CSI node plugin"],
                "scheduler_hooks": [
                    "CSIStorageCapacity + WaitForFirstConsumer 让 scheduler 在候选节点上考虑容量",
                    "VolumeBinding plugin 在 Filter/Reserve/PreBind 阶段假设并提交绑定",
                    "topology keys 约束 volume zone/node locality",
                ],
            },
        },
        "workload_runtime_interfaces": {
            "statefulset": {
                "algorithmic_value": "稳定 ordinal + stable network id + per-replica volumeClaimTemplates，使调度器/存储控制器能把身份和数据绑定。",
                "risks": ["OrderedReady 卡死", "PVC retention policy 误删", "跨 zone 重调度受 PV nodeAffinity 限制"],
            },
            "operator": {
                "algorithmic_value": "CRD + reconcile loop，把人类 runbook 编码成控制器：observe -> diff -> act -> requeue/backoff/finalizer。",
                "project_fit": "为 AgentTask / EtcdMaintenance / ContextPV / ModelPool 编写 Operator，比脚本更能体现企业化。",
            },
            "cni": {
                "operations": ["ADD", "DEL", "CHECK", "STATUS", "VERSION", "GC"],
                "scheduling_signal": "IPAM 剩余量、网络拓扑、带宽/延迟、NetworkPolicy 成本可以作为自定义 scheduler plugin 的 Score 输入。",
            },
            "cri": {
                "role": "kubelet 通过 CRI gRPC 调用 runtime/image service；RuntimeClass 可将 Kata/gVisor 等 sandbox overhead 反馈给 PodOverhead。",
                "scheduling_signal": "不同 RuntimeClass 的 pod overhead、启动延迟和隔离成本应进入调度评分。",
            },
            "pod_overhead": {
                "role": "把 sandbox/runtime 本身消耗加入调度请求，防止只算容器 requests 导致节点过量承诺。",
                "formula": "pod_effective_request = container_requests + pod_overhead",
            },
            "dra": {
                "role": "ResourceClaim/ResourceSlice/DeviceClass 把 GPU、加速器等设备分配纳入 scheduler，而不是只靠静态 extended resources。",
                "project_fit": "多 Agent 模型服务可以把 GPU slice / vLLM KV cache / special device 作为 ResourceClaim 管。",
            },
        },
        "agent_platform_scheduler_design": {
            "name": "AgentWorkloadSchedulingPlugin",
            "pre_filter": [
                "compute effective CPU/memory/request incl. PodOverhead",
                "resolve PVC/CSI/DRA claims",
                "classify workload: agent-api / verifier / sandbox-runner / vLLM / crawler / training",
            ],
            "filter": [
                "node has enough allocatable resources after overhead",
                "volume topology matches or can be provisioned with WaitForFirstConsumer",
                "CNI/IPAM capacity remains above safety watermark",
                "RuntimeClass and CRI handler available",
                "DRA devices or GPU slices satisfy ResourceClaim",
            ],
            "score": [
                "prefer data locality for StatefulSet/PV-bound pods",
                "prefer balanced GPU/CPU packing for model-serving pools",
                "penalize nodes with high CNI setup failure or CSI attach latency",
                "spread orchestrators across failure domains; pack short-lived sandbox jobs",
            ],
            "reserve_prebind": [
                "assume PV binding and ResourceClaim allocation",
                "write binding decisions atomically in PreBind",
                "rollback assumed state on failure",
            ],
        },
    }


def build_cloud_native_deep_dive_plan(
    *,
    focus: str = "agent-platform",
    kubernetes_version: str = "v1.36",
    include_sources: bool = True,
) -> dict[str, Any]:
    plan = {
        "schema": "cloud_native_agent_deep_dive_plan.v1",
        "focus": focus,
        "generated_from": "official-docs-and-recent-papers",
        "multi_agent_similarity_collapse": build_multi_agent_similarity_collapse_route(),
        "etcd_memory_optimization": build_etcd_memory_optimization_plan(),
        "kubernetes_resource_scheduling": build_k8s_resource_scheduling_plan(kubernetes_version=kubernetes_version),
        "operator_assets": build_cloud_native_operator_assets(),
        "prometheus_scorecard": build_cloud_native_prometheus_scorecard(),
        "implementation_roadmap": [
            {
                "phase": "P0",
                "items": [
                    "把 multi-agent collapse metrics 接入 graph_runtime ingest",
                    "新增 diversity-aware retention reducer，替换全量广播式 debate",
                    "形成 EtcdMaintenance Operator 设计：compaction/defrag/snapshot-count recommendation",
                    "形成 AgentWorkloadSchedulingPlugin 设计：PodOverhead + CSI topology + DRA + CNI capacity",
                ],
            },
            {
                "phase": "P1",
                "items": [
                    "实现 collapse_alarm -> workflow conditional edge -> blind fanout rewind",
                    "实现 etcd metrics parser 和 maintenance gate",
                    "输出 scheduler plugin Go skeleton / CRD schema",
                    "为 StatefulSet/vLLM/PV 切片生成 K8s manifests 和 scorecard 指标",
                ],
            },
        ],
        "interview_positioning": [
            "多 Agent 不是堆角色，而是控制结构耦合，保留有价值分歧。",
            "etcd 优化不是盲目 defrag，而是 MVCC compaction、bbolt 空洞回收、Raft snapshot 和 Go GC 的联动策略。",
            "K8s 调度不是只看 CPU/内存，而是 PodOverhead、PV topology、CSI capacity、DRA device、CNI/IPAM 和 Stateful identity 的联合优化。",
        ],
    }
    if include_sources:
        plan["sources"] = RESEARCH_SOURCES
    return plan
