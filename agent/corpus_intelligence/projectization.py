"""Bridge routed crawl outputs into repo-memory and project-task assets."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.project_model.repo_memory import RepoMemoryBuildInput, build_repo_memory
from agent.project_model.task_synthesis import ProjectTaskSynthesisInput, synthesize_project_tasks


_PRIMARY_ROUTE_PRIORITY = ("benchmark_holdout", "train_now", "distill_pool")
_USAGE_BY_ROUTE = {
    "train_now": "supervised_training_candidate",
    "distill_pool": "teacher_distillation_candidate",
    "benchmark_holdout": "holdout_only_no_training",
}


@dataclass(frozen=True)
class CorpusProjectizationInput:
    crawl_output_dir: Path
    output_dir: Path
    allowed_routes: tuple[str, ...] = ("train_now", "distill_pool", "benchmark_holdout")
    max_repos: int = 50
    max_files: int = 500
    max_slices: int = 800
    max_symbol_examples_per_repo: int = 64


@dataclass(frozen=True)
class CorpusProjectizationResult:
    output_dir: str
    files: dict[str, str] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "files": dict(self.files),
            "counts": dict(self.counts),
            "manifest": dict(self.manifest),
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return text.strip("._") or "repo"


def _primary_route(routes: list[str], allowed: set[str]) -> str:
    route_set = {str(route) for route in routes if str(route) in allowed}
    for route in _PRIMARY_ROUTE_PRIORITY:
        if route in route_set:
            return route
    return ""


def _load_profiles(crawl_output_dir: Path) -> list[dict[str, Any]]:
    payload = _safe_json(crawl_output_dir / "repo_profiles.json")
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def build_corpus_projectization_plan(inp: CorpusProjectizationInput) -> dict[str, Any]:
    """Select routed repositories and make split policy explicit before materialization."""

    crawl_output_dir = inp.crawl_output_dir.resolve()
    profiles = _load_profiles(crawl_output_dir)
    allowed = {str(route) for route in inp.allowed_routes if str(route).strip()}
    selected: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for profile in profiles:
        repo = profile.get("repo") if isinstance(profile.get("repo"), dict) else {}
        routing = profile.get("routing") if isinstance(profile.get("routing"), dict) else {}
        routes = [str(route) for route in routing.get("routes", []) if str(route)]
        primary_route = _primary_route(routes, allowed)
        workspace = Path(str(profile.get("workspace", "") or ""))
        if not primary_route:
            skipped.update(["route_not_selected"])
            continue
        if not workspace.exists():
            skipped.update(["workspace_missing"])
            continue
        selected.append(
            {
                "repo": str(repo.get("full_name", "") or workspace.name),
                "workspace": str(workspace),
                "all_routes": routes,
                "primary_route": primary_route,
                "usage": _USAGE_BY_ROUTE.get(primary_route, "observe_only"),
            }
        )
    selected = selected[: max(int(inp.max_repos), 0)]
    route_counts: Counter[str] = Counter(str(row["primary_route"]) for row in selected)
    return {
        "schema": "corpus_projectization_plan.v1",
        "created_at": _now(),
        "crawl_output_dir": str(crawl_output_dir),
        "selection_policy": {
            "allowed_routes": sorted(allowed),
            "primary_route_priority": list(_PRIMARY_ROUTE_PRIORITY),
            "holdout_isolation": "benchmark_holdout wins over train/distill to avoid leakage",
            "max_repos": max(int(inp.max_repos), 0),
        },
        "selected": selected,
        "summary": {
            "profiles": len(profiles),
            "selected": len(selected),
            "route_counts": dict(route_counts),
            "skipped": dict(skipped),
        },
    }


def materialize_corpus_projectization(inp: CorpusProjectizationInput) -> CorpusProjectizationResult:
    """Build CPU-first repo memories and route-separated task assets."""

    output_dir = inp.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    plan = build_corpus_projectization_plan(inp)
    plan_path = output_dir / "projectization_plan.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

    memory_rows: list[dict[str, Any]] = []
    memory_dirs_by_route: dict[str, list[Path]] = defaultdict(list)
    for row in plan.get("selected", []):
        if not isinstance(row, dict):
            continue
        repo = str(row.get("repo", "") or "repo")
        route = str(row.get("primary_route", "") or "")
        workspace = Path(str(row.get("workspace", "") or ""))
        memory_dir = output_dir / "memories" / route / _safe_name(repo)
        memory = build_repo_memory(
            RepoMemoryBuildInput(
                repo_path=workspace,
                output_dir=memory_dir,
                max_files=max(int(inp.max_files), 1),
                max_slices=max(int(inp.max_slices), 1),
            )
        )
        memory_dirs_by_route[route].append(Path(memory.output_dir))
        memory_rows.append(
            {
                "repo": repo,
                "primary_route": route,
                "usage": row.get("usage", ""),
                "memory_dir": memory.output_dir,
                "repo_id": memory.repo_id,
                "counts": dict(memory.counts),
            }
        )

    task_rows: list[dict[str, Any]] = []
    for route, memory_dirs in sorted(memory_dirs_by_route.items()):
        if not memory_dirs:
            continue
        task_result = synthesize_project_tasks(
            ProjectTaskSynthesisInput(
                memory_dirs=tuple(memory_dirs),
                output_dir=output_dir / "tasks" / route,
                max_symbol_examples_per_repo=max(int(inp.max_symbol_examples_per_repo), 0),
            )
        )
        task_rows.append(
            {
                "route": route,
                "usage": _USAGE_BY_ROUTE.get(route, "observe_only"),
                "task_dir": task_result.output_dir,
                "files": dict(task_result.files),
                "counts": dict(task_result.counts),
            }
        )

    manifest = {
        "schema": "corpus_projectization_manifest.v1",
        "created_at": _now(),
        "crawl_output_dir": str(inp.crawl_output_dir.resolve()),
        "split_policy": {
            "train_now": "may feed supervised training",
            "distill_pool": "may feed teacher prompts / reviewed distillation",
            "benchmark_holdout": "holdout only; must not feed training_prepare",
            "primary_route_priority": list(_PRIMARY_ROUTE_PRIORITY),
        },
        "counts": {
            "selected_repos": len(memory_rows),
            "memory_assets": len(memory_rows),
            "task_buckets": len(task_rows),
            "routes": dict(Counter(str(row["primary_route"]) for row in memory_rows)),
        },
        "memory_assets": memory_rows,
        "task_assets": task_rows,
        "files": {
            "plan": str(plan_path),
        },
    }
    manifest_path = output_dir / "corpus_projectization_manifest.json"
    report_path = output_dir / "report.md"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path.write_text(
        "\n".join(
            [
                "# Corpus Projectization",
                "",
                f"- Selected repos: `{len(memory_rows)}`",
                f"- Task buckets: `{len(task_rows)}`",
                "",
                "## Route Buckets",
                "",
                *[
                    f"- `{row['route']}` -> `{row['usage']}`: `{row['counts'].get('training_examples', 0)}` examples"
                    for row in task_rows
                ],
                "",
                "## Leakage Policy",
                "",
                "- `benchmark_holdout` has highest route priority and is never merged into training buckets.",
                "- `train_now` and `distill_pool` remain separate assets so later training/distillation gates can audit them independently.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files = {
        "plan": str(plan_path),
        "manifest": str(manifest_path),
        "report": str(report_path),
    }
    return CorpusProjectizationResult(
        output_dir=str(output_dir),
        files=files,
        counts=dict(manifest["counts"]),
        manifest=manifest,
    )
