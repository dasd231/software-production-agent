"""Guarded training launcher for shared servers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from agent.training.backup_trainer import run_training
from agent.training.resource_guard import build_training_resource_policy, run_server_resource_preflight


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _job_policy(spec_path: Path) -> dict[str, Any]:
    sibling_job_spec = spec_path.resolve().parent / "training_job_spec.json"
    job_spec = _safe_json(sibling_job_spec)
    policy = job_spec.get("resource_policy") if isinstance(job_spec.get("resource_policy"), dict) else {}
    return dict(policy or build_training_resource_policy())


def launch_with_guard(spec_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    policy = _job_policy(spec_path)
    preflight = run_server_resource_preflight(policy=policy)
    run_dir = spec_path.resolve().parent
    (run_dir / "resource_preflight.json").write_text(
        json.dumps(preflight, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not bool(preflight.get("admission", {}).get("admitted")):
        return {
            "status": "blocked_shared_resource",
            "spec": str(spec_path),
            "preflight": preflight,
        }
    for key, value in (policy.get("environment") if isinstance(policy.get("environment"), dict) else {}).items():
        os.environ[str(key)] = str(value)
    return {
        "status": "resource_admitted",
        "spec": str(spec_path),
        "preflight": preflight,
        "training": run_training(spec_path, dry_run=dry_run),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run guarded backup training on a shared GPU server")
    parser.add_argument("--config", required=True, help="Path to backup_training_spec.json")
    parser.add_argument("--dry-run", action="store_true", help="Prepare datasets/model stack without training")
    args = parser.parse_args()
    result = launch_with_guard(Path(args.config), dry_run=bool(args.dry_run))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "blocked_shared_resource":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
