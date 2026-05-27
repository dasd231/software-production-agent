# Enterprise Long-Context PV Slicing

这个模块解决的不是“把长文本切几块存盘”，而是把超长上下文变成一套可审计、可路由、可恢复、可接 K8s 的存储-计算协同方案。

入口：

```text
agent/context_pv/
tests/test_context_pv.py
```

可通过 executor action 调用：

```json
{
  "type": "action",
  "action": "context_pv_plan",
  "args": {
    "text": "# Overview\n\nvery long context...",
    "query": "load code slice",
    "tenant": "demo",
    "namespace": "context-pv",
    "output_path": "plans/context-pv.json"
  }
}
```

权限要求：

```text
context:plan + workspace:write
```

## 1. 切片策略与粒度控制

`slicer.py` 做三层切片：

1. 短上下文直接单 PV，不强行分片。
2. 超阈值后按 Markdown 标题、空行、代码块、表格、列表、段落等语义边界切块。
3. 超大语义块再按句子/代码行拆分，避免单块超过 `max_slice_tokens`。

相邻切片保留 overlap window，默认 256 估算 tokens。真实生产可替换成目标模型 tokenizer，但接口不变。

## 2. 元数据与索引层

`ContextPVManifest` 保存：

- manifest version
- slice token range
- semantic label
- checksum
- PV/PVC placement
- global index
- Merkle root

`index.py` 目前实现 `semantic_label + consistent_hash` 路由：先用 query 判断 code/table/summary/prose，再结合关键词命中、critical slice、hash bucket 给出 top-k slice。这个设计避免每次推理都全量扫 PV。

## 3. PV 生命周期与存储后端

`planner.py` 输出 lifecycle plan：

- StorageClass + PVC 动态供给
- hot/warm/cold 分层
- CSI 在线扩容优先
- 扩容失败时新增 PVC bucket 并通过 WAL 原子切换 placement map
- immutable slice payload + mutable manifest pointer，支持 A/B 和回滚

`k8s.py` 会渲染 Namespace、ResourceQuota、StorageClass、PVC、ConfigMap、loader Job、NetworkPolicy。Job 内含 `verify-manifest` Init Container 和 `slice-metrics-sidecar`，分别对应启动前一致性校验与运行期指标采集。

## 4. 一致性与事务

`transaction.py` 输出 WAL：

```text
prepare -> write -> commit
```

每个 slice 有 SHA256 checksum，manifest 有 Merkle root。读侧要求：

- 同 manifest version
- 使用前校验 slice checksum
- manifest 加载时校验 Merkle root

当前实现是控制面计划，不直接写真实 PV；接入真实 writer 时按 WAL 执行即可。

## 5. 缓存与加载性能

cache plan 固化四层：

```text
PV -> local SSD -> memory -> GPU
```

策略：

- local SSD: LRU by manifest_version + slice_id
- memory: LFU with recency decay
- GPU: attention-prefetch window
- prefetch: 对 routed slice 的 ordinal-1 / ordinal+1 异步预加载

zero-copy 当前是接口预留：本地阶段用 mmap/local SSD staging；集群能力成熟后可接 GPUDirect Storage / io_uring。

## 6. 容错与高可用

critical slices 默认复制：

- 首片/尾片
- summary/heading/code
- hot tier 内或跨 hot tier 副本

降级策略：

- PV 部分不可用时，用 hot/critical slice 继续回答
- 输出必须标注 missing slice ids 和 confidence downgrade
- 崩溃后从 latest committed manifest pointer + WAL checkpoint 恢复

## 7. 可观测性与运维

observability plan 包含指标：

- `context_pv_slice_load_latency_ms{tier,pvc}`
- `context_pv_cache_hit_ratio{tier}`
- `context_pv_checksum_failures_total{tier,pvc}`
- `context_pv_degraded_reads_total{reason}`
- `context_pv_capacity_used_ratio{pvc}`

追踪 span：

```text
route_query -> load_manifest -> load_slice_from_pv -> local_cache -> memory_cache -> tensorize_to_gpu
```

告警覆盖 PVC 80% 容量、slice load 超时、checksum failure。

## 8. 安全与隔离

security plan 包含：

- tenant scoped namespace/PVC
- ResourceQuota 防止 PVC 资源耗尽
- NetworkPolicy default deny
- ServiceAccount 禁用自动 token
- loader Job 非 root、只读根文件系统、drop ALL capabilities
- 静态加密与传输加密要求

## 当前边界

已经完成：

- 控制面规划器
- 语义切片
- PV placement
- index/routing
- WAL/Merkle/checksum
- cache/lifecycle/observability/security/degradation plan
- K8s manifest 渲染
- executor action
- pytest 覆盖

尚未做成真实生产组件：

- 真 CSI driver 对接
- 真对象存储冷热迁移
- 真 GPU zero-copy
- Prometheus exporter
- Kubernetes client apply/回滚执行器

也就是说：现在足够支撑论文/面试/架构演示和第一版工程入口；下一步要把 writer/loader 从“计划”升级成“真实执行器”。
