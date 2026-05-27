from __future__ import annotations

import hashlib
import time
from typing import Any

from agent.context_pv.index import build_global_index, route_query_to_slices
from agent.context_pv.placement import place_slices
from agent.context_pv.schema import ContextPVManifest, ContextPVPlan, ContextPVPolicy
from agent.context_pv.slicer import slice_context_text
from agent.context_pv.transaction import build_transaction_plan, compute_merkle_root


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _manifest_id(text: str, version: str, tenant: str) -> str:
    return "ctxm-" + hashlib.sha256(f"{tenant}:{version}\n{text}".encode("utf-8")).hexdigest()[:20]


def _build_cache_plan(policy: ContextPVPolicy) -> dict[str, Any]:
    return {
        "schema": "context_pv.cache_plan.v1",
        "tiers": [
            {"name": "pv", "role": "source_of_truth", "eviction": "none"},
            {"name": "local_ssd", "size": policy.local_cache_size, "eviction": "LRU by manifest_version+slice_id"},
            {"name": "memory", "budget_tokens": policy.memory_cache_tokens, "eviction": "LFU with recency decay"},
            {"name": "gpu", "budget_tokens": policy.gpu_cache_tokens, "eviction": "attention-prefetch window"},
        ],
        "prefetch": {
            "strategy": "route_top_k_neighbors",
            "async": True,
            "rule": "after loading a routed slice, prefetch ordinal-1 and ordinal+1 when same manifest version",
        },
        "zero_copy_direction": {
            "current": "planned interface; use mmap/local SSD staging before tensorization",
            "future": "GPUDirect Storage / io_uring path when CSI and GPU runtime support it",
        },
    }


def _build_lifecycle_plan(policy: ContextPVPolicy) -> dict[str, Any]:
    return {
        "schema": "context_pv.lifecycle.v1",
        "dynamic_provisioning": {
            "enabled": True,
            "mechanism": "StorageClass + PVC templates rendered by control plane",
            "storage_classes": dict(policy.storage_classes),
        },
        "tiering": {
            "hot": "summary, code and active query-window slices on NVMe/SSD",
            "warm": "recent but not immediately routed slices on SSD",
            "cold": "archival long-tail slices on object/HDD-backed PV",
            "migration_trigger": "access_frequency + age + capacity pressure",
        },
        "expansion": {
            "online_csi_resize_first": True,
            "fallback": "create next PVC bucket and rewrite placement map atomically through WAL",
        },
        "versions": {
            "mode": "immutable slice payloads + mutable manifest pointer",
            "ab_test": "route by manifest version without rewriting payload",
            "rollback": "switch manifest pointer to previous committed version",
        },
    }


def _build_load_plan(
    routes: list[dict[str, Any]],
    slices_by_id: dict[str, Any],
) -> dict[str, Any]:
    required = [str(item["slice_id"]) for item in routes]
    prefetch: list[str] = []
    for route in routes:
        ordinal = int(route.get("ordinal", 0))
        for candidate in slices_by_id.values():
            if candidate.ordinal in (ordinal - 1, ordinal + 1) and candidate.slice_id not in required:
                if candidate.slice_id not in prefetch:
                    prefetch.append(candidate.slice_id)
    return {
        "schema": "context_pv.load_plan.v1",
        "required_slice_ids": required,
        "prefetch_slice_ids": prefetch[: max(4, len(required))],
        "read_consistency": {
            "require_same_manifest_version": True,
            "verify_checksum_before_use": True,
            "verify_merkle_root_on_manifest_load": True,
        },
        "routing_trace": routes,
    }


def _build_observability_plan(policy: ContextPVPolicy) -> dict[str, Any]:
    return {
        "schema": "context_pv.observability.v1",
        "metrics": [
            "context_pv_slice_load_latency_ms{tier,pvc}",
            "context_pv_slice_bytes{tier,pvc,label}",
            "context_pv_cache_hit_ratio{tier}",
            "context_pv_checksum_failures_total{tier,pvc}",
            "context_pv_degraded_reads_total{reason}",
            "context_pv_capacity_used_ratio{pvc}",
        ],
        "tracing_spans": [
            "route_query",
            "load_manifest",
            "load_slice_from_pv",
            "promote_to_local_cache",
            "promote_to_memory_cache",
            "tensorize_to_gpu",
        ],
        "alerts": [
            {"name": "PVCNearFull", "expr": "context_pv_capacity_used_ratio > 0.80", "severity": "warning"},
            {"name": "SliceLoadTimeout", "expr": "p95(context_pv_slice_load_latency_ms) > 1500", "severity": "critical"},
            {"name": "ChecksumFailure", "expr": "increase(context_pv_checksum_failures_total[5m]) > 0", "severity": "critical"},
        ],
        "namespace": policy.namespace,
    }


def _build_security_plan(policy: ContextPVPolicy) -> dict[str, Any]:
    return {
        "schema": "context_pv.security.v1",
        "tenant": policy.tenant,
        "namespace": policy.namespace,
        "isolation": [
            "namespace-per-tenant or namespace-per-environment",
            "PVC names are tenant-scoped",
            "NetworkPolicy default deny for loader/indexer pods",
            "ResourceQuota prevents unbounded PVC growth",
        ],
        "encryption": {
            "at_rest_required": policy.encryption_required,
            "transport": "TLS/IPSec by cluster/storage backend",
            "key_boundary": "tenant-scoped KMS key alias recommended",
        },
        "rbac": {
            "service_account": "context-pv-loader",
            "permissions": ["read ConfigMap index", "mount tenant PVCs"],
            "forbidden": ["list secrets", "hostPath mount", "privileged pods"],
        },
        "quota": {
            "storage": policy.quota_storage_limit,
            "cpu": policy.quota_cpu_limit,
            "memory": policy.quota_memory_limit,
        },
    }


def _build_degradation_plan(routes: list[dict[str, Any]]) -> dict[str, Any]:
    hot_required = [item["slice_id"] for item in routes if item.get("pv_tier") == "hot"]
    return {
        "schema": "context_pv.degradation.v1",
        "partial_pv_unavailable": {
            "mode": "best_effort_answer_with_evidence_gap",
            "minimum_viable_context": hot_required[:3] or [item["slice_id"] for item in routes[:1]],
            "output_requirement": "model response must expose missing slice_ids and confidence downgrade",
        },
        "snapshot_recovery": {
            "mode": "restore latest committed manifest pointer, then replay WAL records after checkpoint",
            "checkpoint": "manifest + merkle root + WAL commit index",
        },
        "redundancy": {
            "critical_slices": "replicated according to policy.replica_factor_critical",
            "non_critical_slices": "single primary plus object-store snapshot recommended",
        },
    }


def plan_context_pv(
    text: str,
    *,
    query: str = "",
    policy: ContextPVPolicy | None = None,
    version: str = "v1",
) -> ContextPVPlan:
    active_policy = (policy or ContextPVPolicy()).normalized()
    manifest_id = _manifest_id(text, version, active_policy.tenant)
    slices, total_tokens = slice_context_text(text, policy=active_policy, version=version, manifest_id=manifest_id)
    placements = place_slices(slices, policy=active_policy)
    merkle_root = compute_merkle_root([item.checksum for item in slices])
    global_index = build_global_index(slices, placements, policy=active_policy)
    manifest = ContextPVManifest(
        schema="context_pv.manifest.v1",
        manifest_id=manifest_id,
        version=version,
        created_at=_now_iso(),
        tenant=active_policy.tenant,
        namespace=active_policy.namespace,
        total_tokens=total_tokens,
        merkle_root=merkle_root,
        slices=slices,
        placements=placements,
        global_index=global_index,
    )
    transaction = build_transaction_plan(manifest_id, slices, placements)
    routes = route_query_to_slices(query, slices, placements, policy=active_policy)
    slices_by_id = {item.slice_id: item for item in slices}
    return ContextPVPlan(
        schema="context_pv.plan.v1",
        policy=active_policy,
        manifest=manifest,
        transaction=transaction,
        load_plan=_build_load_plan(routes, slices_by_id),
        cache_plan=_build_cache_plan(active_policy),
        lifecycle_plan=_build_lifecycle_plan(active_policy),
        observability_plan=_build_observability_plan(active_policy),
        security_plan=_build_security_plan(active_policy),
        degradation_plan=_build_degradation_plan(routes),
    )

