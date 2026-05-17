"""Dataset snapshotting and sharding for reproducible training jobs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            rows.append(raw)
    return rows


def _file_hash(path: Path) -> str:
    h = hashlib.blake2b(digest_size=16)
    if not path.exists():
        return ""
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _stable_digest(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()


def _task_mix(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        task = str(metadata.get("task_type") or row.get("task_type") or "unknown")
        counts[task] = counts.get(task, 0) + 1
    return counts


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_split_shards(
    rows: list[dict[str, Any]],
    *,
    split: str,
    root: Path,
    shard_size: int,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    size = max(int(shard_size), 1)
    out: list[dict[str, Any]] = []
    for index in range(0, len(rows), size):
        shard_rows = rows[index : index + size]
        shard_no = index // size
        shard_path = root / split / f"shard-{shard_no:05d}.jsonl"
        _write_jsonl(shard_path, shard_rows)
        out.append(
            {
                "split": split,
                "index": shard_no,
                "path": str(shard_path),
                "examples": len(shard_rows),
                "content_hash": _file_hash(shard_path),
                "task_mix": _task_mix(shard_rows),
            }
        )
    return out


def build_dataset_storage_profile(
    *,
    training_dir: Path,
    dataset_id: str,
    object_store_uri: str = "",
    preferred_format: str = "jsonl",
) -> dict[str, Any]:
    """Describe current and future storage posture without copying data."""

    normalized_format = preferred_format if preferred_format in {"jsonl", "parquet"} else "jsonl"
    return {
        "schema": "dataset_storage_profile.v1",
        "dataset_id": dataset_id,
        "current_format": "jsonl",
        "preferred_format": normalized_format,
        "local_root": str(training_dir.resolve()),
        "object_store_uri": object_store_uri,
        "spark_ready": bool(normalized_format == "parquet" and object_store_uri),
        "partition_hints": ["split", "task_type"],
        "migration_state": "local_jsonl" if normalized_format == "jsonl" else "parquet_planned",
        "notes": [
            "JSONL remains authoritative for the current workstation workflow.",
            "Parquet/object-storage migration is metadata-planned only until a real batch-data need appears.",
        ],
    }


def create_dataset_snapshot(
    training_dir: Path,
    *,
    shard_size: int = 1024,
    write_shards: bool = True,
) -> dict[str, Any]:
    """Freeze a training directory into a traceable dataset manifest."""

    root = training_dir.resolve()
    dataset_path = root / "dataset.jsonl"
    train_path = root / "train.jsonl"
    eval_path = root / "eval.jsonl"
    raw_path = root / "raw_examples.jsonl"
    protocol_path = root / "protocol_examples.jsonl"
    quality = _safe_json(root / "quality_report.json")
    sample_quality = _safe_json(root / "sample_quality_report.json")
    governance = _safe_json(root / "governance_report.json")
    evaluation = _safe_json(root / "evaluation_report.json")
    run_manifest = _safe_json(root / "run_manifest.json")
    train_rows = _read_jsonl(train_path)
    eval_rows = _read_jsonl(eval_path)
    dataset_rows = _read_jsonl(dataset_path)

    files = {
        "dataset": {"path": str(dataset_path), "content_hash": _file_hash(dataset_path), "examples": len(dataset_rows)},
        "train": {"path": str(train_path), "content_hash": _file_hash(train_path), "examples": len(train_rows)},
        "eval": {"path": str(eval_path), "content_hash": _file_hash(eval_path), "examples": len(eval_rows)},
        "raw_examples": {"path": str(raw_path), "content_hash": _file_hash(raw_path)},
        "protocol_examples": {"path": str(protocol_path), "content_hash": _file_hash(protocol_path)},
    }
    identity_payload = {
        "files": files,
        "quality": {
            "evaluation_score": quality.get("evaluation_score"),
            "sample_quality_score": sample_quality.get("overall_score"),
            "governance_grade": governance.get("grade"),
        },
        "source_manifest_id": run_manifest.get("manifest_id"),
    }
    dataset_id = f"dataset-{_stable_digest(identity_payload)}"
    shard_root = root / "shards"
    shards: list[dict[str, Any]] = []
    if write_shards:
        shards.extend(_build_split_shards(train_rows, split="train", root=shard_root, shard_size=shard_size))
        shards.extend(_build_split_shards(eval_rows, split="eval", root=shard_root, shard_size=shard_size))

    manifest = {
        "schema": "dataset_snapshot_manifest.v1",
        "dataset_id": dataset_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_dir": str(root),
        "source_manifest_id": run_manifest.get("manifest_id"),
        "source_refs": list(run_manifest.get("source_refs", [])) if isinstance(run_manifest.get("source_refs"), list) else [],
        "counts": {
            "dataset_examples": len(dataset_rows),
            "train_examples": len(train_rows),
            "eval_examples": len(eval_rows),
        },
        "task_mix": {
            "dataset": _task_mix(dataset_rows),
            "train": _task_mix(train_rows),
            "eval": _task_mix(eval_rows),
        },
        "quality": {
            "quality_report": quality,
            "sample_quality_report": sample_quality,
            "governance_report": governance,
            "evaluation_report": evaluation,
        },
        "files": files,
        "storage_profile": build_dataset_storage_profile(
            training_dir=root,
            dataset_id=dataset_id,
        ),
        "sharding": {
            "enabled": bool(write_shards),
            "shard_size": max(int(shard_size), 1),
            "shards": shards,
        },
    }
    (root / "dataset_snapshot_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
