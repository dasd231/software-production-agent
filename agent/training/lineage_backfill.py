"""Backfill lineage metadata for legacy training and evaluation artifacts.

This module upgrades old artifacts conservatively:

- deterministic fields are reconstructed automatically;
- ambiguous evaluation-to-model links require explicit operator overrides;
- every run can be inspected in dry-run mode before files are mutated.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.training.jobs import create_training_job_manifest, transition_training_job
from agent.training.promotion import evaluate_promotion, write_promotion_artifacts
from agent.training.specs import build_training_job_spec


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_json(path: Path, payload: dict[str, Any], *, apply: bool) -> None:
    if not apply:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _child_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name)


def _benchmark_signatures(benchmark_dir: Path) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for path in sorted(benchmark_dir.glob("*.json")):
        raw = _safe_json(path)
        cases = raw.get("cases") if isinstance(raw.get("cases"), list) else []
        case_ids = tuple(str(row.get("case_id", "")) for row in cases if isinstance(row, dict))
        if case_ids:
            out[path.name] = case_ids
    return out


def infer_benchmark_id(report: dict[str, Any], benchmark_dir: Path) -> str:
    """Infer a benchmark filename by exact case-id signature match."""

    existing = str(report.get("benchmark_id", "") or "")
    if existing:
        return existing
    case_ids = tuple(
        str(row.get("case_id", ""))
        for row in report.get("cases", [])
        if isinstance(row, dict) and str(row.get("case_id", "")).strip()
    )
    if not case_ids:
        return ""
    matches = [name for name, signature in _benchmark_signatures(benchmark_dir).items() if signature == case_ids]
    return matches[0] if len(matches) == 1 else ""


def _dataset_snapshot_for(version: dict[str, Any]) -> dict[str, Any]:
    training_dir_raw = str(version.get("training_dir", "") or "").strip()
    if not training_dir_raw:
        return {}
    return _safe_json(Path(training_dir_raw) / "dataset_snapshot_manifest.json")


def _job_status_for(version: dict[str, Any]) -> str:
    if str(version.get("training_status", "")) == "completed" or str(version.get("rollout_stage", "")) == "trained":
        return "completed"
    return "queued"


def _reconstruct_job_manifest(
    *,
    job_id: str,
    spec_path: Path,
    dataset_snapshot_id: str,
    final_status: str,
) -> dict[str, Any]:
    manifest = create_training_job_manifest(
        job_id=job_id,
        spec_path=spec_path,
        dataset_snapshot_id=dataset_snapshot_id,
        backend="local_trl",
        execution_target="local",
    )
    manifest = transition_training_job(manifest, "validated", detail="legacy_backfill_reconstructed")
    manifest = transition_training_job(manifest, "queued", detail="legacy_backfill_reconstructed")
    if final_status == "completed":
        manifest = transition_training_job(manifest, "completed", detail="legacy_backfill_reconstructed")
    return manifest


def backfill_model_run(run_dir: Path, *, apply: bool) -> dict[str, Any]:
    """Reconstruct deterministic lineage artifacts for one legacy model run."""

    version_path = run_dir / "model_version_manifest.json"
    spec_path = run_dir / "backup_training_spec.json"
    run_manifest_path = run_dir / "run_manifest.json"
    version = _safe_json(version_path)
    training_spec = _safe_json(spec_path)
    run_manifest = _safe_json(run_manifest_path)
    if not version or not training_spec:
        return {"run": run_dir.name, "changed": False, "skipped": "missing_model_version_or_training_spec"}

    dataset_snapshot = _dataset_snapshot_for(version)
    if not dataset_snapshot:
        return {"run": run_dir.name, "changed": False, "skipped": "missing_dataset_snapshot"}

    output_dir = run_dir.resolve()
    job_spec_path = run_dir / "training_job_spec.json"
    job_manifest_path = run_dir / "training_job_manifest.json"
    existing_job_spec = _safe_json(job_spec_path)
    hyper = training_spec.get("hyperparameters") if isinstance(training_spec.get("hyperparameters"), dict) else {}
    job_spec = existing_job_spec or build_training_job_spec(
        base_model=str(version.get("base_model", "") or training_spec.get("base_model", "")),
        adapter_name=str(version.get("adapter_name", "") or training_spec.get("adapter_name", "")),
        dataset_snapshot=dataset_snapshot,
        backend="local_trl",
        hyperparameters=hyper,
        evaluation_benchmark="./benchmarks/backup_model_eval.v3.json",
        output_dir=output_dir,
    )

    final_status = _job_status_for(version)
    existing_job_manifest = _safe_json(job_manifest_path)
    job_manifest = existing_job_manifest or _reconstruct_job_manifest(
        job_id=str(job_spec.get("job_spec_id", "")),
        spec_path=job_spec_path,
        dataset_snapshot_id=str(dataset_snapshot.get("dataset_id", "")),
        final_status=final_status,
    )

    changes: list[str] = []
    if not existing_job_spec:
        changes.append("created_training_job_spec")
        _write_json(job_spec_path, job_spec, apply=apply)
    if not existing_job_manifest:
        changes.append("created_training_job_manifest")
        _write_json(job_manifest_path, job_manifest, apply=apply)

    dataset_id = str(dataset_snapshot.get("dataset_id", "") or "")
    job_spec_id = str(job_spec.get("job_spec_id", "") or "")
    if dataset_id and not str(version.get("dataset_snapshot_id", "") or ""):
        version["dataset_snapshot_id"] = dataset_id
        changes.append("backfilled_dataset_snapshot_id")
    if job_spec_id and not str(version.get("training_job_spec_id", "") or ""):
        version["training_job_spec_id"] = job_spec_id
        changes.append("backfilled_training_job_spec_id")
    if changes:
        lineage = version.setdefault("lineage_backfill", {})
        if isinstance(lineage, dict):
            lineage.update(
                {
                    "backfilled_at": _now(),
                    "method": "deterministic_reconstruction",
                    "changes": changes,
                }
            )
        _write_json(version_path, version, apply=apply)

    if run_manifest:
        manifest_changed = False
        input_summary = run_manifest.setdefault("input_summary", {})
        if isinstance(input_summary, dict):
            if dataset_id and not str(input_summary.get("dataset_snapshot_id", "") or ""):
                input_summary["dataset_snapshot_id"] = dataset_id
                manifest_changed = True
            if job_spec_id and not str(input_summary.get("training_job_spec_id", "") or ""):
                input_summary["training_job_spec_id"] = job_spec_id
                manifest_changed = True
        files = run_manifest.setdefault("files", {})
        if isinstance(files, dict):
            if not files.get("training_job_spec"):
                files["training_job_spec"] = str(job_spec_path)
                manifest_changed = True
            if not files.get("training_job_manifest"):
                files["training_job_manifest"] = str(job_manifest_path)
                manifest_changed = True
        artifacts = run_manifest.setdefault("artifacts", [])
        if isinstance(artifacts, list):
            for item in (str(job_spec_path), str(job_manifest_path)):
                if item not in artifacts:
                    artifacts.append(item)
                    manifest_changed = True
        if manifest_changed:
            backfill = run_manifest.setdefault("lineage_backfill", {})
            if isinstance(backfill, dict):
                backfill.update({"backfilled_at": _now(), "method": "deterministic_reconstruction"})
            changes.append("updated_run_manifest")
            _write_json(run_manifest_path, run_manifest, apply=apply)

    return {
        "run": run_dir.name,
        "changed": bool(changes),
        "changes": changes,
        "dataset_snapshot_id": dataset_id,
        "training_job_spec_id": job_spec_id,
    }


def _load_overrides(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return _safe_json(path)


def _model_index(model_runs_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for run_dir in _child_dirs(model_runs_dir):
        version = _safe_json(run_dir / "model_version_manifest.json")
        if version:
            out[run_dir.name] = {
                "run_dir": run_dir,
                "version": version,
            }
    return out


def _eval_index(model_evals_dir: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for run_dir in _child_dirs(model_evals_dir):
        report = _safe_json(run_dir / "model_evaluation_report.json")
        if report:
            out[run_dir.name] = {
                "run_dir": run_dir,
                "report": report,
            }
    return out


def _subject_from_model_version(version: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_version": version.get("model_version", ""),
        "base_model": version.get("base_model", ""),
        "adapter_name": version.get("adapter_name", ""),
        "dataset_snapshot_id": version.get("dataset_snapshot_id", ""),
        "training_job_spec_id": version.get("training_job_spec_id", ""),
    }


def _is_baseline_report(report: dict[str, Any]) -> bool:
    subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
    if str(subject.get("subject_type", "") or "") == "base_model":
        return True
    label = str(report.get("label", "") or "").lower()
    return label == "base" or label == "baseline" or label.startswith("base_") or "_base" in label


def _backfill_benchmark_ids(
    evals: dict[str, dict[str, Any]],
    *,
    benchmark_dir: Path,
    apply: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for eval_name, entry in evals.items():
        report = entry["report"]
        inferred = infer_benchmark_id(report, benchmark_dir)
        changed = bool(inferred and not str(report.get("benchmark_id", "") or ""))
        if changed:
            report["benchmark_id"] = inferred
            lineage = report.setdefault("lineage_backfill", {})
            if isinstance(lineage, dict):
                lineage.update(
                    {
                        "backfilled_at": _now(),
                        "benchmark_method": "exact_case_signature",
                    }
                )
            _write_json(entry["run_dir"] / "model_evaluation_report.json", report, apply=apply)
        rows.append(
            {
                "evaluation_run": eval_name,
                "changed": changed,
                "benchmark_id": report.get("benchmark_id", "") or inferred,
            }
        )
    return rows


def _backfill_evaluation_links(
    evals: dict[str, dict[str, Any]],
    models: dict[str, dict[str, Any]],
    overrides: dict[str, Any],
    *,
    apply: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    links = overrides.get("evaluation_links") if isinstance(overrides.get("evaluation_links"), list) else []
    for raw in links:
        if not isinstance(raw, dict):
            continue
        eval_name = str(raw.get("evaluation_run", "") or "")
        model_run = str(raw.get("model_run", "") or "")
        if eval_name not in evals:
            rows.append({"evaluation_run": eval_name, "changed": False, "skipped": "missing_evaluation_run"})
            continue
        if model_run not in models:
            rows.append({"evaluation_run": eval_name, "changed": False, "skipped": "missing_model_run"})
            continue
        report = evals[eval_name]["report"]
        existing_subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
        target_subject = _subject_from_model_version(models[model_run]["version"])
        existing_version = str(existing_subject.get("model_version", "") or "")
        target_version = str(target_subject.get("model_version", "") or "")
        if existing_version and existing_version != target_version:
            rows.append(
                {
                    "evaluation_run": eval_name,
                    "changed": False,
                    "skipped": "conflicting_existing_subject",
                    "existing_model_version": existing_version,
                    "target_model_version": target_version,
                }
            )
            continue
        changed = existing_subject != target_subject
        if changed:
            report["subject"] = target_subject
            lineage = report.setdefault("lineage_backfill", {})
            if isinstance(lineage, dict):
                lineage.update(
                    {
                        "backfilled_at": _now(),
                        "subject_method": "explicit_override",
                        "model_run": model_run,
                    }
                )
            _write_json(evals[eval_name]["run_dir"] / "model_evaluation_report.json", report, apply=apply)
        rows.append(
            {
                "evaluation_run": eval_name,
                "changed": changed,
                "model_run": model_run,
                "model_version": target_version,
            }
        )
    return rows


def _generate_promotion_decisions(
    evals: dict[str, dict[str, Any]],
    models: dict[str, dict[str, Any]],
    overrides: dict[str, Any],
    *,
    apply: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    links = overrides.get("evaluation_links") if isinstance(overrides.get("evaluation_links"), list) else []
    for raw in links:
        if not isinstance(raw, dict):
            continue
        eval_name = str(raw.get("evaluation_run", "") or "")
        baseline_name = str(raw.get("baseline_evaluation_run", "") or "")
        model_run = str(raw.get("model_run", "") or "")
        if not baseline_name:
            continue
        if eval_name not in evals or baseline_name not in evals or model_run not in models:
            rows.append(
                {
                    "evaluation_run": eval_name,
                    "changed": False,
                    "skipped": "missing_candidate_or_baseline_or_model",
                }
            )
            continue
        decision = evaluate_promotion(
            baseline_report=evals[baseline_name]["report"],
            candidate_report=evals[eval_name]["report"],
            model_version=models[model_run]["version"],
        )
        decision_dir = evals[eval_name]["run_dir"]
        decision_path = decision_dir / "model_promotion_decision.json"
        existing_decision = _safe_json(decision_path)
        comparable_existing = {k: v for k, v in existing_decision.items() if k != "generated_at"}
        comparable_new = {k: v for k, v in decision.items() if k != "generated_at"}
        changed = not existing_decision or comparable_existing != comparable_new
        if apply and changed:
            write_promotion_artifacts(decision_dir, decision)
        rows.append(
            {
                "evaluation_run": eval_name,
                "changed": changed,
                "status": decision.get("status", ""),
                "passed": decision.get("passed", False),
                "baseline_evaluation_run": baseline_name,
            }
        )
    return rows


def run_lineage_backfill(
    root: Path,
    *,
    overrides_path: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    model_runs_dir = root / "model_runs"
    model_evals_dir = root / "model_evals"
    benchmark_dir = root / "benchmarks"
    overrides = _load_overrides(overrides_path)

    model_rows = [backfill_model_run(run_dir, apply=apply) for run_dir in _child_dirs(model_runs_dir)]
    models = _model_index(model_runs_dir)
    evals = _eval_index(model_evals_dir)
    benchmark_rows = _backfill_benchmark_ids(evals, benchmark_dir=benchmark_dir, apply=apply)
    eval_link_rows = _backfill_evaluation_links(evals, models, overrides, apply=apply)
    promotion_rows = _generate_promotion_decisions(evals, models, overrides, apply=apply)
    linked_eval_names = {
        str(row.get("evaluation_run", "") or "")
        for row in eval_link_rows
        if str(row.get("model_version", "") or "")
    }
    baseline_only_evaluations = [
        name for name, entry in evals.items() if _is_baseline_report(entry["report"])
    ]
    unresolved_candidate_evaluations = [
        name
        for name, entry in evals.items()
        if not _is_baseline_report(entry["report"])
        and (
            not isinstance(entry["report"].get("subject"), dict)
            or not str((entry["report"].get("subject") or {}).get("model_version", "") or "")
        )
    ]
    report = {
        "schema": "training_lineage_backfill_report.v1",
        "generated_at": _now(),
        "mode": "apply" if apply else "dry_run",
        "overrides_path": str(overrides_path) if overrides_path else "",
        "summary": {
            "model_runs": len(model_rows),
            "changed_model_runs": sum(1 for row in model_rows if row.get("changed")),
            "evaluation_runs": len(evals),
            "benchmark_ids_backfilled": sum(1 for row in benchmark_rows if row.get("changed")),
            "evaluation_links_backfilled": sum(1 for row in eval_link_rows if row.get("changed")),
            "promotion_decisions_generated": sum(1 for row in promotion_rows if row.get("changed")),
            "linked_evaluations": len(linked_eval_names),
            "baseline_only_evaluations": len(baseline_only_evaluations),
            "unresolved_candidate_evaluations": len(unresolved_candidate_evaluations),
        },
        "model_runs": model_rows,
        "benchmark_backfill": benchmark_rows,
        "evaluation_links": eval_link_rows,
        "promotion_decisions": promotion_rows,
        "baseline_only_evaluations": baseline_only_evaluations,
        "unresolved_candidate_evaluations": unresolved_candidate_evaluations,
        "notes": [
            "模型训练产物只做可确定重建，不改写历史 model_version。",
            "评测到模型版本的关联只接受显式 override，避免根据命名猜测错误挂接。",
            "benchmark_id 通过 case-id 精确签名匹配反推，而不是通过目录名模糊猜测。",
            "baseline 评测不要求挂到 adapter 版本，只有缺少 model_version 的候选评测才算待处理项。",
        ],
    }
    return report


def write_backfill_report(root: Path, report: dict[str, Any], *, apply: bool) -> Path:
    report_path = root / "research_workbench" / "dashboards" / "lineage_backfill_report.json"
    if apply:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill deterministic lineage metadata for legacy training artifacts")
    parser.add_argument("--root", default=".")
    parser.add_argument("--overrides", default="./research_workbench/lineage_overrides.json")
    parser.add_argument("--apply", action="store_true", help="写入文件；默认只做 dry-run 报告")
    args = parser.parse_args(argv)
    root = Path(args.root)
    overrides = Path(args.overrides) if str(args.overrides).strip() else None
    if overrides is not None and not overrides.is_absolute():
        overrides = (root / overrides).resolve()
    report = run_lineage_backfill(root, overrides_path=overrides, apply=bool(args.apply))
    write_backfill_report(root.resolve(), report, apply=bool(args.apply))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
