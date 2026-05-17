from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from agent.core.executor import run_action
from agent.corpus_intelligence.feedback import build_corpus_feedback_report
from agent.corpus_intelligence.program import build_github_corpus_program
from agent.corpus_intelligence.ranking import build_github_query_plan, rank_repo_profiles


def _profile(
    name: str,
    *,
    quality: float,
    license_id: str = "MIT",
    shape: str = "backend",
    tags: list[str] | None = None,
) -> dict:
    return {
        "repo": {
            "full_name": name,
            "description": "spring boot project",
            "license_spdx": license_id,
            "updated_at": "2026-05-01T00:00:00+00:00",
            "topics": ["spring", "backend"],
        },
        "architecture": {"shape": shape, "tags": tags or ["spring-boot", "backend"]},
        "quality": {"score": quality},
        "training_tags": tags or ["spring-boot", "backend"],
    }


def test_github_corpus_program_exposes_modules_metrics_and_student_policy() -> None:
    program = build_github_corpus_program()

    assert program["schema"] == "github_corpus_program.v1"
    assert program["student_model_policy"]["family"] == "deepseek_open_family"
    assert program["modules"][0]["id"] == "discovery"
    assert "tokens_per_correct_answer" in program["metric_taxonomy"]["model"]


def test_query_plan_uses_web_facets_and_diversifies() -> None:
    plan = build_github_query_plan(
        seed_queries=["spring boot vue"],
        web_results=[
            {"title": "Spring Boot Vue dashboard", "snippet": "admin panel workflow"},
            {"title": "Spring Boot SaaS starter", "snippet": "multi tenant starter"},
        ],
        max_queries=4,
    )

    assert plan["schema"] == "github_query_plan.v1"
    assert plan["queries"][0]["kind"] == "seed"
    assert any(row["kind"] == "web_expansion" for row in plan["queries"])


def test_ranker_routes_high_quality_and_quarantines_bad_governance() -> None:
    ranking = rank_repo_profiles(
        query="spring boot backend",
        profiles=[
            _profile("org/high-quality", quality=8.6),
            _profile("org/no-license", quality=8.2, license_id=""),
        ],
        allowed_licenses={"mit"},
        min_quality=6.5,
        now=datetime(2026, 5, 18, tzinfo=timezone.utc),
    )

    rows = {row["repo"]: row for row in ranking["rows"]}
    assert "train_now" in rows["org/high-quality"]["routes"]
    assert rows["org/no-license"]["routes"] == ["quarantine"]
    assert "missing_license" in rows["org/no-license"]["gates"]


def test_feedback_recommends_more_exploration_when_distribution_collapses() -> None:
    ranking = rank_repo_profiles(
        query="spring boot",
        profiles=[
            _profile("org/a", quality=8.0, shape="backend"),
            _profile("org/b", quality=8.0, shape="backend"),
            _profile("org/c", quality=8.0, shape="backend"),
        ],
        now=datetime(2026, 5, 18, tzinfo=timezone.utc),
    )
    feedback = build_corpus_feedback_report(
        ranking=ranking,
        downstream_metrics={"recall_at_5_delta": -0.1},
    )

    ids = {row["id"] for row in feedback["recommended_actions"]}
    assert "increase_exploration" in ids
    assert "oversample_evidence_rich_repos" in ids


def test_corpus_actions_return_control_plane_objects(tmp_path: Path) -> None:
    program = run_action(tmp_path, {"type": "action", "action": "github_corpus_program_plan", "args": {}})
    query_plan = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "github_query_plan_build",
            "args": {"seed_queries": ["spring boot vue"], "web_results": [], "max_queries": 3},
        },
    )
    ranking = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "github_candidate_rank",
            "args": {
                "query": "spring boot",
                "profiles": [_profile("org/demo", quality=8.0)],
                "allowed_licenses": ["MIT"],
            },
        },
    )
    feedback = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "corpus_feedback_plan",
            "args": {"ranking": ranking["ranking"], "downstream_metrics": {}},
        },
    )

    assert program["plan"]["schema"] == "github_corpus_program.v1"
    assert query_plan["plan"]["schema"] == "github_query_plan.v1"
    assert ranking["ranking"]["schema"] == "github_repo_ranking.v1"
    assert feedback["feedback"]["schema"] == "corpus_feedback_report.v1"
