from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PV_TIERS: tuple[str, ...] = ("hot", "warm", "cold")


@dataclass(slots=True)
class ContextPVPolicy:
    """Tunable policy for long-context slicing and PV placement.

    The defaults are conservative enough for a shared development cluster:
    modest PVC counts, bounded slice sizes, explicit namespace isolation and
    no assumption that a real CSI driver exists yet.
    """

    tenant: str = "default"
    namespace: str = "context-pv"
    single_pv_token_threshold: int = 4096
    target_slice_tokens: int = 2048
    max_slice_tokens: int = 3072
    overlap_tokens: int = 256
    hot_tier_token_budget: int = 8192
    warm_tier_token_budget: int = 32768
    route_top_k: int = 6
    replica_factor_critical: int = 2
    critical_labels: tuple[str, ...] = ("summary", "heading", "code")
    storage_classes: dict[str, str] = field(
        default_factory=lambda: {
            "hot": "context-hot-nvme",
            "warm": "context-warm-ssd",
            "cold": "context-cold-object",
        }
    )
    pvc_capacity: dict[str, str] = field(
        default_factory=lambda: {"hot": "20Gi", "warm": "100Gi", "cold": "500Gi"}
    )
    pvc_count_per_tier: dict[str, int] = field(default_factory=lambda: {"hot": 2, "warm": 2, "cold": 2})
    local_cache_size: str = "10Gi"
    memory_cache_tokens: int = 8192
    gpu_cache_tokens: int = 2048
    encryption_required: bool = True
    quota_storage_limit: str = "1Ti"
    quota_cpu_limit: str = "8"
    quota_memory_limit: str = "32Gi"

    def normalized(self) -> "ContextPVPolicy":
        target = max(256, int(self.target_slice_tokens))
        max_tokens = max(target, int(self.max_slice_tokens))
        threshold = max(1, int(self.single_pv_token_threshold))
        overlap = max(0, min(int(self.overlap_tokens), max_tokens // 2))
        hot_budget = max(0, int(self.hot_tier_token_budget))
        warm_budget = max(hot_budget, int(self.warm_tier_token_budget))
        replica = max(1, int(self.replica_factor_critical))
        counts = {tier: max(1, int(self.pvc_count_per_tier.get(tier, 1))) for tier in PV_TIERS}
        classes = {tier: str(self.storage_classes.get(tier, f"context-{tier}")) for tier in PV_TIERS}
        capacity = {tier: str(self.pvc_capacity.get(tier, "20Gi")) for tier in PV_TIERS}
        return ContextPVPolicy(
            tenant=self.tenant,
            namespace=self.namespace,
            single_pv_token_threshold=threshold,
            target_slice_tokens=target,
            max_slice_tokens=max_tokens,
            overlap_tokens=overlap,
            hot_tier_token_budget=hot_budget,
            warm_tier_token_budget=warm_budget,
            route_top_k=max(1, int(self.route_top_k)),
            replica_factor_critical=replica,
            critical_labels=tuple(str(x) for x in self.critical_labels),
            storage_classes=classes,
            pvc_capacity=capacity,
            pvc_count_per_tier=counts,
            local_cache_size=str(self.local_cache_size),
            memory_cache_tokens=max(0, int(self.memory_cache_tokens)),
            gpu_cache_tokens=max(0, int(self.gpu_cache_tokens)),
            encryption_required=bool(self.encryption_required),
            quota_storage_limit=str(self.quota_storage_limit),
            quota_cpu_limit=str(self.quota_cpu_limit),
            quota_memory_limit=str(self.quota_memory_limit),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextSlice:
    slice_id: str
    ordinal: int
    text: str
    token_start: int
    token_end: int
    overlap_left: int
    overlap_right: int
    semantic_label: str
    checksum: str
    version: str
    critical: bool = False
    byte_length: int = 0

    @property
    def token_count(self) -> int:
        return max(0, self.token_end - self.token_start)

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        data = asdict(self)
        data["token_count"] = self.token_count
        if not include_text:
            data.pop("text", None)
        return data


@dataclass(slots=True)
class SlicePlacement:
    slice_id: str
    pv_tier: str
    namespace: str
    pvc_name: str
    storage_class: str
    offset_tokens: int
    length_tokens: int
    replica_pvc_names: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ContextPVManifest:
    schema: str
    manifest_id: str
    version: str
    created_at: str
    tenant: str
    namespace: str
    total_tokens: int
    merkle_root: str
    slices: list[ContextSlice]
    placements: list[SlicePlacement]
    global_index: dict[str, Any]

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "manifest_id": self.manifest_id,
            "version": self.version,
            "created_at": self.created_at,
            "tenant": self.tenant,
            "namespace": self.namespace,
            "total_tokens": self.total_tokens,
            "merkle_root": self.merkle_root,
            "slices": [item.to_dict(include_text=include_text) for item in self.slices],
            "placements": [item.to_dict() for item in self.placements],
            "global_index": self.global_index,
        }


@dataclass(slots=True)
class WALRecord:
    record_id: str
    phase: str
    slice_id: str
    pvc_name: str
    checksum: str
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TransactionPlan:
    transaction_id: str
    consistency_mode: str
    isolation: str
    checksum_policy: str
    wal_records: list[WALRecord]
    rollback_strategy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "consistency_mode": self.consistency_mode,
            "isolation": self.isolation,
            "checksum_policy": self.checksum_policy,
            "wal_records": [record.to_dict() for record in self.wal_records],
            "rollback_strategy": self.rollback_strategy,
        }


@dataclass(slots=True)
class ContextPVPlan:
    schema: str
    policy: ContextPVPolicy
    manifest: ContextPVManifest
    transaction: TransactionPlan
    load_plan: dict[str, Any]
    cache_plan: dict[str, Any]
    lifecycle_plan: dict[str, Any]
    observability_plan: dict[str, Any]
    security_plan: dict[str, Any]
    degradation_plan: dict[str, Any]

    def to_dict(self, *, include_text: bool = True) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "policy": self.policy.to_dict(),
            "manifest": self.manifest.to_dict(include_text=include_text),
            "transaction": self.transaction.to_dict(),
            "load_plan": self.load_plan,
            "cache_plan": self.cache_plan,
            "lifecycle_plan": self.lifecycle_plan,
            "observability_plan": self.observability_plan,
            "security_plan": self.security_plan,
            "degradation_plan": self.degradation_plan,
        }

