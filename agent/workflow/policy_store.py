from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import time
from typing import Any

from agent.workflow.schema import WorkflowPolicy


@dataclass(slots=True)
class PolicyRecord:
    version: str
    policy: WorkflowPolicy
    created_at: float = field(default_factory=time)
    parent_version: str | None = None
    notes: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


class PolicyStore:
    """File-backed policy version store for canary/rollback-friendly optimization."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.current_path = self.root / "current.txt"

    def save(self, record: PolicyRecord, *, make_current: bool = False) -> Path:
        path = self.root / f"{record.version}.json"
        payload = {
            "version": record.version,
            "created_at": record.created_at,
            "parent_version": record.parent_version,
            "notes": record.notes,
            "metrics": record.metrics,
            "policy": asdict(record.policy),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if make_current:
            self.current_path.write_text(record.version, encoding="utf-8")
        return path

    def load(self, version: str) -> PolicyRecord:
        path = self.root / f"{version}.json"
        if not path.exists():
            raise KeyError(f"unknown policy version: {version}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PolicyRecord(
            version=payload["version"],
            created_at=float(payload.get("created_at", 0.0)),
            parent_version=payload.get("parent_version"),
            notes=str(payload.get("notes", "")),
            metrics=dict(payload.get("metrics", {})),
            policy=WorkflowPolicy(**payload.get("policy", {})),
        )

    def current(self) -> PolicyRecord | None:
        if not self.current_path.exists():
            return None
        version = self.current_path.read_text(encoding="utf-8").strip()
        return self.load(version) if version else None

    def promote(self, version: str) -> PolicyRecord:
        record = self.load(version)
        self.current_path.write_text(version, encoding="utf-8")
        return record

    def list_versions(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json"))
