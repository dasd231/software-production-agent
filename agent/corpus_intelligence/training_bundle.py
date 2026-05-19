"""Prepare a safe first-round training bundle from projectized corpus assets."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.chains.training import TrainingPrepareInput, prepare_fine_tuning_dataset


@dataclass(frozen=True)
class CorpusTrainingBundleInput:
    projectization_dir: Path
    output_dir: Path
    include_routes: tuple[str, ...] = ("train_now", "distill_pool")
    dataset_format: str = "messages"
    eval_ratio: float = 0.15
    min_chars: int = 20
    max_examples: int = 2000
    model_hint: str = "deepseek-coder"
    include_protocol_examples: bool = True
    protocol_example_limit: int = 0
    prepare_dataset: bool = False


@dataclass(frozen=True)
class CorpusTrainingBundleResult:
    output_dir: str
    files: dict[str, str] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    training_prepare: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "files": dict(self.files),
            "manifest": dict(self.manifest),
            "training_prepare": dict(self.training_prepare),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _route_assets(projectization: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in projectization.get("task_assets", []) if isinstance(row, dict)]


def _task_dir(asset: dict[str, Any]) -> Path:
    raw = str(asset.get("task_dir", "") or "")
    if raw:
        return Path(raw)
    files = asset.get("files") if isinstance(asset.get("files"), dict) else {}
    training_examples = str(files.get("training_examples", "") or "")
    return Path(training_examples).parent if training_examples else Path("")


def build_corpus_training_bundle(inp: CorpusTrainingBundleInput) -> CorpusTrainingBundleResult:
    """Build an auditable bundle that keeps holdout data out of training."""

    projectization_dir = inp.projectization_dir.resolve()
    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    projectization = _safe_json(projectization_dir / "corpus_projectization_manifest.json")
    projectization = projectization if isinstance(projectization, dict) else {}
    include_routes = {str(route) for route in inp.include_routes if str(route).strip()}
    train_assets: list[dict[str, Any]] = []
    holdout_assets: list[dict[str, Any]] = []
    excluded_assets: list[dict[str, Any]] = []
    for asset in _route_assets(projectization):
        route = str(asset.get("route", "") or "")
        task_dir = _task_dir(asset)
        row = {
            "route": route,
            "usage": str(asset.get("usage", "") or ""),
            "task_dir": str(task_dir),
            "training_examples": str((asset.get("files") or {}).get("training_examples", "")),
            "counts": asset.get("counts", {}) if isinstance(asset.get("counts"), dict) else {},
        }
        if route == "benchmark_holdout":
            holdout_assets.append(row)
        elif route in include_routes:
            train_assets.append(row)
        else:
            excluded_assets.append(row)
    learning_dirs = [
        Path(row["task_dir"])
        for row in train_assets
        if str(row.get("task_dir", "")).strip() and Path(str(row["task_dir"])).exists()
    ]
    training_output_dir = output_dir / "training_prepare"
    model_output_dir = output_dir / "model_prepare"
    blockers: list[str] = []
    warnings: list[str] = []
    if not learning_dirs:
        blockers.append("no_trainable_route_task_dirs")
    if holdout_assets:
        warnings.append("benchmark_holdout_assets_excluded_from_training")
    manifest = {
        "schema": "corpus_training_bundle_manifest.v1",
        "created_at": _now(),
        "source_projectization_dir": str(projectization_dir),
        "include_routes": sorted(include_routes),
        "learning_dirs": [str(path) for path in learning_dirs],
        "holdout_assets": holdout_assets,
        "excluded_assets": excluded_assets,
        "dataset_policy": {
            "benchmark_holdout_excluded": True,
            "prepare_dataset": bool(inp.prepare_dataset),
            "dataset_format": inp.dataset_format,
            "eval_ratio": float(inp.eval_ratio),
            "max_examples": int(inp.max_examples),
        },
        "recommended_actions": [
            {
                "type": "action",
                "action": "training_prepare",
                "args": {
                    "output_dir": str(training_output_dir),
                    "learning_dirs": [str(path) for path in learning_dirs],
                    "dataset_format": inp.dataset_format,
                    "eval_ratio": float(inp.eval_ratio),
                    "min_chars": int(inp.min_chars),
                    "max_examples": int(inp.max_examples),
                    "model_hint": inp.model_hint,
                    "include_protocol_examples": bool(inp.include_protocol_examples),
                    "protocol_example_limit": int(inp.protocol_example_limit),
                },
            },
            {
                "type": "action",
                "action": "backup_model_train",
                "args": {
                    "training_dir": str(training_output_dir),
                    "output_dir": str(model_output_dir),
                    "base_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
                    "adapter_name": "corpus-first-round-lora",
                    "launch": False,
                },
            },
        ],
        "validation": {
            "ok": not blockers,
            "blockers": blockers,
            "warnings": warnings,
        },
    }
    manifest_path = output_dir / "corpus_training_bundle_manifest.json"
    inputs_path = output_dir / "training_inputs.json"
    report_path = output_dir / "report.md"
    _write_json(manifest_path, manifest)
    _write_json(
        inputs_path,
        {
            "schema": "corpus_training_inputs.v1",
            "learning_dirs": [str(path) for path in learning_dirs],
            "holdout_dirs": [str(row["task_dir"]) for row in holdout_assets],
            "excluded_dirs": [str(row["task_dir"]) for row in excluded_assets],
        },
    )
    training_result: dict[str, Any] = {}
    if inp.prepare_dataset and not blockers:
        training_result = prepare_fine_tuning_dataset(
            TrainingPrepareInput(
                output_dir=training_output_dir,
                learning_dirs=tuple(learning_dirs),
                dataset_format=inp.dataset_format,
                eval_ratio=float(inp.eval_ratio),
                min_chars=int(inp.min_chars),
                max_examples=int(inp.max_examples),
                model_hint=inp.model_hint,
                include_protocol_examples=bool(inp.include_protocol_examples),
                protocol_example_limit=int(inp.protocol_example_limit),
            )
        ).to_dict()
        manifest["training_prepare"] = {
            "output_dir": training_result.get("output_dir", ""),
            "total_examples": training_result.get("total_examples", 0),
            "files": training_result.get("files", {}),
            "evaluation_summary": training_result.get("evaluation_summary", {}),
        }
        _write_json(manifest_path, manifest)
    report_path.write_text(
        "\n".join(
            [
                "# Corpus Training Bundle",
                "",
                f"- Trainable dirs: `{len(learning_dirs)}`",
                f"- Holdout assets excluded: `{len(holdout_assets)}`",
                f"- Validation: `{manifest['validation']['ok']}`",
                "",
                "## Safety",
                "",
                "- `benchmark_holdout` assets are never added to `learning_dirs`.",
                "- This bundle prepares data only; GPU training still requires explicit `backup_model_train` and server preflight.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = {
        "manifest": str(manifest_path),
        "training_inputs": str(inputs_path),
        "report": str(report_path),
    }
    return CorpusTrainingBundleResult(
        output_dir=str(output_dir),
        files=files,
        manifest=manifest,
        training_prepare=training_result,
    )
