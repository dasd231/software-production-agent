from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from agent.core.executor import run_action
from agent.corpus_intelligence.scheduler import (
    CorpusSchedulerConfig,
    build_corpus_scheduler_plan,
    run_corpus_scheduler_cycle,
)


def _make_repo(root: Path) -> Path:
    repo = root / "demo_repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs").mkdir()
    (repo / "README.md").write_text("# Demo\n\nFastAPI demo.", encoding="utf-8")
    (repo / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (repo / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (repo / "tests" / "test_demo.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    (repo / "docs" / "ARCHITECTURE.md").write_text("backend api", encoding="utf-8")
    return repo


def test_scheduler_plan_is_due_before_first_cycle(tmp_path: Path) -> None:
    config = CorpusSchedulerConfig(
        output_root=tmp_path / "scheduler",
        seed_queries=("fastapi backend",),
        local_repos=(_make_repo(tmp_path),),
        interval_seconds=3600,
        repo_limit=1,
    )

    plan = build_corpus_scheduler_plan(config, now=datetime(2026, 5, 18, tzinfo=timezone.utc))

    assert plan["schema"] == "github_corpus_scheduler_plan.v1"
    assert plan["due"] is True
    assert plan["resource_policy"]["cpu_first"] is True
    assert plan["recommended_hosting"]["mode"] == "systemd_timer_or_cron"


def test_scheduler_cycle_persists_state_and_respects_cooldown(tmp_path: Path) -> None:
    config = CorpusSchedulerConfig(
        output_root=tmp_path / "scheduler",
        seed_queries=("fastapi backend",),
        local_repos=(_make_repo(tmp_path),),
        interval_seconds=3600,
        repo_limit=1,
        min_stars=0,
        quality_threshold=0.0,
    )
    now = datetime(2026, 5, 18, tzinfo=timezone.utc)

    first = run_corpus_scheduler_cycle(config, now=now)
    second = run_corpus_scheduler_cycle(config, now=now)

    assert first["status"] == "completed"
    assert first["ran"] is True
    assert second["status"] == "skipped_cooldown"
    state = json.loads(Path(first["state_path"]).read_text(encoding="utf-8"))
    assert state["schema"] == "github_corpus_scheduler_state.v1"
    assert state["latest_cycle_id"] == first["cycle_id"]
    assert Path(state["latest_strategy_path"]).exists()
    assert Path(first["cycle_record_path"]).exists()
    assert first["next_plan"]["due"] is False


def test_scheduler_actions_are_available(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    plan = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "github_corpus_scheduler_plan",
            "args": {
                "output_root": "./scheduler",
                "seed_queries": ["fastapi backend"],
                "local_repos": [str(repo)],
                "repo_limit": 1,
                "min_stars": 0,
            },
        },
    )
    cycle = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "github_corpus_scheduler_cycle",
            "args": {
                "output_root": "./scheduler-action",
                "seed_queries": ["fastapi backend"],
                "local_repos": [str(repo)],
                "repo_limit": 1,
                "min_stars": 0,
                "quality_threshold": 0.0,
            },
        },
    )

    assert plan["ok"] is True
    assert plan["plan"]["schema"] == "github_corpus_scheduler_plan.v1"
    assert cycle["ok"] is True
    assert cycle["cycle"]["status"] == "completed"
