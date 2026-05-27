from __future__ import annotations

import hashlib

from agent.context_pv.schema import ContextSlice, SlicePlacement, TransactionPlan, WALRecord


def compute_merkle_root(checksums: list[str]) -> str:
    if not checksums:
        return hashlib.sha256(b"").hexdigest()
    level = [bytes.fromhex(item) for item in checksums]
    while len(level) > 1:
        next_level: list[bytes] = []
        for idx in range(0, len(level), 2):
            left = level[idx]
            right = level[idx + 1] if idx + 1 < len(level) else left
            next_level.append(hashlib.sha256(left + right).digest())
        level = next_level
    return level[0].hex()


def build_transaction_plan(
    manifest_id: str,
    slices: list[ContextSlice],
    placements: list[SlicePlacement],
    *,
    strict_version_reads: bool = True,
) -> TransactionPlan:
    placement_by_slice = {item.slice_id: item for item in placements}
    records: list[WALRecord] = []
    for slice_obj in slices:
        placement = placement_by_slice[slice_obj.slice_id]
        for phase in ("prepare", "write"):
            records.append(
                WALRecord(
                    record_id=hashlib.sha1(
                        f"{manifest_id}:{slice_obj.slice_id}:{phase}:{placement.pvc_name}".encode("utf-8")
                    ).hexdigest()[:16],
                    phase=phase,
                    slice_id=slice_obj.slice_id,
                    pvc_name=placement.pvc_name,
                    checksum=slice_obj.checksum,
                )
            )
    for slice_obj in slices:
        placement = placement_by_slice[slice_obj.slice_id]
        records.append(
            WALRecord(
                record_id=hashlib.sha1(f"{manifest_id}:{slice_obj.slice_id}:commit".encode("utf-8")).hexdigest()[:16],
                phase="commit",
                slice_id=slice_obj.slice_id,
                pvc_name=placement.pvc_name,
                checksum=slice_obj.checksum,
            )
        )
    return TransactionPlan(
        transaction_id=hashlib.sha1(f"{manifest_id}:transaction".encode("utf-8")).hexdigest()[:20],
        consistency_mode="strong_manifest_version" if strict_version_reads else "eventual_slice_refresh",
        isolation="read_committed_manifest_snapshot",
        checksum_policy="sha256_per_slice + merkle_root_manifest",
        wal_records=records,
        rollback_strategy={
            "mode": "wal_compensating_delete",
            "safe_point": "previous_committed_manifest_version",
            "rule": "if any prepare/write fails, delete uncommitted slice payloads and keep last manifest pointer",
        },
    )


def verify_slice_checksums(slices: list[ContextSlice]) -> dict[str, bool]:
    return {
        item.slice_id: hashlib.sha256(f"{item.version}:{item.ordinal}\n{item.text}".encode("utf-8")).hexdigest()
        == item.checksum
        for item in slices
    }

