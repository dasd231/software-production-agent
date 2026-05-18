"""Conservative single-shot scheduler for long-running GitHub corpus ingestion."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agent.chains.github_crawler import CrawlProfileInput, crawl_frontend_backend_repos


@dataclass(frozen=True)
class CorpusSchedulerConfig:
    """Bounded runtime policy for one Linux-resident corpus program."""

    output_root: Path
    seed_queries: tuple[str, ...]
    local_repos: tuple[Path, ...] = ()
    web_results: tuple[dict[str, Any], ...] = ()
    enable_github_network: bool = False
    interval_seconds: int = 3600
    repo_limit: int = 5
    max_query_arms: int = 4
    min_stars: int = 50
    allowed_licenses: tuple[str, ...] = ()
    updated_after: str = ""
    quality_threshold: float = 6.5
    downstream_metrics: dict[str, float] = field(default_factory=dict)
    cpu_thread_budget: int = 2
    max_cycles_retained: int = 50


def _now(now: datetime | None = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_dt(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _stable_id(prefix: str, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.blake2b(text.encode("utf-8"), digest_size=8).hexdigest()
    return f"{prefix}-{digest}"


def _state_path(config: CorpusSchedulerConfig) -> Path:
    return config.output_root / "scheduler_state.json"


def _default_state() -> dict[str, Any]:
    return {
        "schema": "github_corpus_scheduler_state.v1",
        "latest_cycle_id": "",
        "latest_completed_at": "",
        "latest_strategy_path": "",
        "latest_feedback_path": "",
        "cycles": [],
    }


def load_corpus_scheduler_state(output_root: Path) -> dict[str, Any]:
    path = output_root / "scheduler_state.json"
    if not path.exists():
        return _default_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    if not isinstance(payload, dict):
        return _default_state()
    state = _default_state()
    state.update(payload)
    state["cycles"] = [row for row in state.get("cycles", []) if isinstance(row, dict)]
    return state


def _load_strategy(path_text: str) -> dict[str, Any]:
    path = Path(str(path_text or ""))
    if not str(path_text or "").strip() or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _config_validation(config: CorpusSchedulerConfig) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if not config.seed_queries and not config.local_repos:
        blockers.append("missing_seed_queries_or_local_repos")
    if int(config.interval_seconds) < 1:
        blockers.append("interval_seconds_must_be_positive")
    if int(config.repo_limit) < 1:
        blockers.append("repo_limit_must_be_positive")
    if int(config.max_query_arms) < 1:
        blockers.append("max_query_arms_must_be_positive")
    if int(config.cpu_thread_budget) < 1:
        blockers.append("cpu_thread_budget_must_be_positive")
    if int(config.max_cycles_retained) < 1:
        blockers.append("max_cycles_retained_must_be_positive")
    if not config.enable_github_network:
        warnings.append("github_network_disabled")
    return {"ok": not blockers, "blockers": blockers, "warnings": warnings}


def build_corpus_scheduler_plan(
    config: CorpusSchedulerConfig,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a transparent runtime plan for cron/systemd-style single-shot cycles."""

    current = _now(now)
    state = load_corpus_scheduler_state(config.output_root)
    latest_completed = _parse_dt(str(state.get("latest_completed_at", "")))
    next_due = latest_completed + timedelta(seconds=max(int(config.interval_seconds), 1)) if latest_completed else current
    due = latest_completed is None or current >= next_due
    prior_strategy = _load_strategy(str(state.get("latest_strategy_path", "")))
    validation = _config_validation(config)
    return {
        "schema": "github_corpus_scheduler_plan.v1",
        "generated_at": _iso(current),
        "runtime_mode": "single_shot_timer_friendly",
        "due": bool(due and validation["ok"]),
        "next_due_at": _iso(next_due),
        "state_path": str(_state_path(config)),
        "latest_cycle_id": str(state.get("latest_cycle_id", "") or ""),
        "strategy_source": {
            "path": str(state.get("latest_strategy_path", "") or ""),
            "schema": str(prior_strategy.get("schema", "") or ""),
        },
        "resource_policy": {
            "cpu_first": True,
            "gpu_required": False,
            "repo_limit": max(int(config.repo_limit), 1),
            "max_query_arms": max(int(config.max_query_arms), 1),
            "cpu_thread_budget": max(int(config.cpu_thread_budget), 1),
            "why": "bounded single-shot cycles avoid uncontrolled background contention on shared servers",
        },
        "cycle_action": {
            "type": "action",
            "action": "github_corpus_scheduler_cycle",
            "args": {
                "output_root": str(config.output_root),
                "seed_queries": list(config.seed_queries),
                "github": bool(config.enable_github_network),
                "interval_seconds": max(int(config.interval_seconds), 1),
                "repo_limit": max(int(config.repo_limit), 1),
                "max_query_arms": max(int(config.max_query_arms), 1),
            },
        },
        "recommended_hosting": {
            "mode": "systemd_timer_or_cron",
            "reason": "one bounded cycle per invocation is easier to audit, resume and stop than an immortal daemon",
        },
        "validation": validation,
    }


def run_corpus_scheduler_cycle(
    config: CorpusSchedulerConfig,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run one bounded crawl/profile/feedback cycle and persist scheduler state."""

    current = _now(now)
    plan = build_corpus_scheduler_plan(config, now=current)
    if not bool(plan.get("validation", {}).get("ok")):
        return {
            "schema": "github_corpus_scheduler_cycle.v1",
            "status": "blocked_invalid_config",
            "ran": False,
            "plan": plan,
        }
    if not bool(plan.get("due")) and not force:
        return {
            "schema": "github_corpus_scheduler_cycle.v1",
            "status": "skipped_cooldown",
            "ran": False,
            "plan": plan,
        }

    root = config.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    state = load_corpus_scheduler_state(root)
    prior_strategy = _load_strategy(str(state.get("latest_strategy_path", "")))
    cycle_payload = {
        "at": _iso(current),
        "sequence": len([row for row in state.get("cycles", []) if isinstance(row, dict)]) + 1,
        "seed_queries": list(config.seed_queries),
        "repo_limit": max(int(config.repo_limit), 1),
        "max_query_arms": max(int(config.max_query_arms), 1),
        "prior_strategy_schema": str(prior_strategy.get("schema", "") or ""),
    }
    cycle_id = _stable_id("cycle", cycle_payload)
    cycle_dir = root / "cycles" / cycle_id
    crawl = crawl_frontend_backend_repos(
        CrawlProfileInput(
            query=" ".join(config.seed_queries),
            output_dir=cycle_dir,
            local_repos=config.local_repos,
            seed_queries=config.seed_queries,
            web_results=config.web_results,
            enable_github_network=config.enable_github_network,
            repo_limit=max(int(config.repo_limit), 1),
            max_query_arms=max(int(config.max_query_arms), 1),
            min_stars=max(int(config.min_stars), 0),
            allowed_licenses=config.allowed_licenses,
            updated_after=config.updated_after,
            quality_threshold=float(config.quality_threshold),
            downstream_metrics={
                str(key): float(value)
                for key, value in config.downstream_metrics.items()
                if isinstance(value, (int, float))
            },
            prior_strategy=prior_strategy,
        )
    )
    cycle_record = {
        "schema": "github_corpus_scheduler_cycle_record.v1",
        "cycle_id": cycle_id,
        "completed_at": _iso(current),
        "output_dir": str(cycle_dir),
        "profiles": len(crawl.profiles),
        "exported_solutions": len(crawl.exported_solutions),
        "files": dict(crawl.files),
        "evaluation": dict(crawl.evaluation),
        "manifest_id": str(crawl.manifest.get("manifest_id", "") or ""),
    }
    cycle_record_path = cycle_dir / "scheduler_cycle.json"
    cycle_record_path.write_text(json.dumps(cycle_record, ensure_ascii=False, indent=2), encoding="utf-8")
    cycles = [row for row in state.get("cycles", []) if isinstance(row, dict)]
    cycles.append(cycle_record)
    cycles = cycles[-max(int(config.max_cycles_retained), 1) :]
    state.update(
        {
            "schema": "github_corpus_scheduler_state.v1",
            "latest_cycle_id": cycle_id,
            "latest_completed_at": _iso(current),
            "latest_strategy_path": crawl.files.get("corpus_strategy", ""),
            "latest_feedback_path": crawl.files.get("feedback_report", ""),
            "cycles": cycles,
        }
    )
    state_path = _state_path(config)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "schema": "github_corpus_scheduler_cycle.v1",
        "status": "completed",
        "ran": True,
        "cycle_id": cycle_id,
        "state_path": str(state_path),
        "cycle_record_path": str(cycle_record_path),
        "crawl": crawl.to_dict(),
        "next_plan": build_corpus_scheduler_plan(config, now=current),
    }
