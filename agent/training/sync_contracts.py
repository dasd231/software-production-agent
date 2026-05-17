"""Portable input/output contracts for local-to-remote training dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_artifact_sync_contract(
    *,
    dataset_snapshot: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    """Describe what must move to and from a compute worker."""

    dataset_files = dataset_snapshot.get("files") if isinstance(dataset_snapshot.get("files"), dict) else {}
    shard_rows = ((dataset_snapshot.get("sharding") or {}).get("shards") or []) if isinstance(dataset_snapshot, dict) else []
    inputs = [
        {
            "kind": "dataset_manifest",
            "path": str(Path(str(dataset_snapshot.get("training_dir", ""))) / "dataset_snapshot_manifest.json"),
            "required": True,
        },
        {
            "kind": "train_file",
            "path": str((dataset_files.get("train") or {}).get("path", "")),
            "required": True,
        },
        {
            "kind": "eval_file",
            "path": str((dataset_files.get("eval") or {}).get("path", "")),
            "required": False,
        },
    ]
    inputs.extend(
        {
            "kind": f"{str(row.get('split', 'data'))}_shard",
            "path": str(row.get("path", "")),
            "content_hash": str(row.get("content_hash", "")),
            "required": True,
        }
        for row in shard_rows
        if isinstance(row, dict)
    )
    return {
        "schema": "training_sync_contract.v1",
        "inputs": inputs,
        "outputs": [
            {"kind": "adapter_dir", "path": str(output_dir / "adapter"), "required": True},
            {
                "kind": "training_result",
                "path": str(output_dir / "adapter" / "training_result.json"),
                "required": True,
            },
            {"kind": "logs_dir", "path": str(output_dir / "logs"), "required": False},
            {"kind": "checkpoints_dir", "path": str(output_dir / "adapter"), "required": False},
        ],
        "verification": {
            "verify_input_hashes": True,
            "verify_required_outputs_before_completion": True,
            "checkpoint_discovery": "latest_by_mtime",
        },
    }
