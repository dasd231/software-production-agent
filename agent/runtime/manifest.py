"""Run manifest helpers for reproducible chain outputs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _stable_digest(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.blake2b(text.encode("utf-8"), digest_size=12).hexdigest()


def build_run_manifest(
    *,
    kind: str,
    input_summary: dict[str, Any],
    files: dict[str, str],
    evaluation: dict[str, Any] | None = None,
    artifacts: list[str] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    risks: list[str] | None = None,
) -> dict[str, Any]:
    body = {
        "schema": "run_manifest.v1",
        "kind": kind,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": dict(input_summary),
        "files": dict(files),
        "artifacts": list(artifacts or []),
        "source_refs": list(source_refs or []),
        "risks": list(risks or []),
        "evaluation": dict(evaluation or {}),
    }
    body["manifest_id"] = _stable_digest({k: v for k, v in body.items() if k != "created_at"})
    return body


def write_run_manifest(output_dir: Path, manifest: dict[str, Any], *, name: str = "run_manifest.json") -> Path:
    path = output_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
