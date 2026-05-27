from __future__ import annotations

import hashlib
import re

from agent.context_pv.schema import ContextPVPolicy, ContextSlice, SlicePlacement


def _slug(value: str, *, fallback: str = "default") -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return slug or fallback


def consistent_hash_bucket(key: str, bucket_count: int) -> int:
    count = max(1, int(bucket_count))
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % count


def pvc_name(policy: ContextPVPolicy, tier: str, bucket: int) -> str:
    tenant = _slug(policy.tenant)
    return f"ctx-{tenant}-{tier}-{bucket:02d}"[:63].rstrip("-")


def tier_for_slice(slice_obj: ContextSlice, policy: ContextPVPolicy) -> str:
    if slice_obj.critical and slice_obj.token_start <= policy.hot_tier_token_budget:
        return "hot"
    if slice_obj.token_start < policy.hot_tier_token_budget:
        return "hot"
    if slice_obj.token_start < policy.warm_tier_token_budget:
        return "warm"
    return "cold"


def place_slices(slices: list[ContextSlice], *, policy: ContextPVPolicy | None = None) -> list[SlicePlacement]:
    active_policy = (policy or ContextPVPolicy()).normalized()
    offsets: dict[str, int] = {}
    placements: list[SlicePlacement] = []
    for slice_obj in slices:
        tier = tier_for_slice(slice_obj, active_policy)
        bucket_count = active_policy.pvc_count_per_tier[tier]
        bucket = consistent_hash_bucket(slice_obj.slice_id, bucket_count)
        primary = pvc_name(active_policy, tier, bucket)
        offset = offsets.get(primary, 0)
        offsets[primary] = offset + slice_obj.token_count

        replicas: list[str] = [primary]
        if slice_obj.critical and active_policy.replica_factor_critical > 1:
            replica_tier = tier if tier == "hot" else "hot"
            replica_count = active_policy.pvc_count_per_tier[replica_tier]
            for step in range(1, active_policy.replica_factor_critical + 1):
                candidate = pvc_name(
                    active_policy,
                    replica_tier,
                    (consistent_hash_bucket(slice_obj.slice_id + f":r{step}", replica_count)) % replica_count,
                )
                if candidate not in replicas:
                    replicas.append(candidate)
                if len(replicas) >= active_policy.replica_factor_critical:
                    break

        placements.append(
            SlicePlacement(
                slice_id=slice_obj.slice_id,
                pv_tier=tier,
                namespace=active_policy.namespace,
                pvc_name=primary,
                storage_class=active_policy.storage_classes[tier],
                offset_tokens=offset,
                length_tokens=slice_obj.token_count,
                replica_pvc_names=tuple(replicas),
            )
        )
    return placements

