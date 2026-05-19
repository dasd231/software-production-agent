from __future__ import annotations

import json
from pathlib import Path

from agent.core.executor import run_action
from agent.corpus_intelligence.flywheel import CorpusFlywheelInput, run_corpus_flywheel_cycle


def _make_repo(root: Path) -> Path:
    repo = root / "flywheel_repo"
    (repo / "backend" / "src" / "main" / "java" / "demo").mkdir(parents=True)
    (repo / "backend" / "src" / "test" / "java" / "demo").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "README.md").write_text("# Demo\n\nSpring Boot demo.", encoding="utf-8")
    (repo / "docs" / "ARCHITECTURE.md").write_text("backend api", encoding="utf-8")
    (repo / "pom.xml").write_text(
        "<project><dependencies><dependency><artifactId>spring-boot-starter-web</artifactId></dependency></dependencies></project>",
        encoding="utf-8",
    )
    (repo / "backend" / "src" / "main" / "java" / "demo" / "DemoApplication.java").write_text(
        "@SpringBootApplication\n@RestController\nclass DemoApplication {}",
        encoding="utf-8",
    )
    (repo / "backend" / "src" / "test" / "java" / "demo" / "DemoApplicationTest.java").write_text(
        "class DemoApplicationTest {}",
        encoding="utf-8",
    )
    return repo


def test_flywheel_cycle_runs_crawl_projectize_and_benchmark(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    result = run_corpus_flywheel_cycle(
        CorpusFlywheelInput(
            output_root=tmp_path / "corpus",
            seed_queries=("spring boot",),
            local_repos=(repo,),
            repo_limit=1,
            min_stars=0,
            quality_threshold=0.0,
            force=True,
        )
    )

    assert result["schema"] == "github_corpus_flywheel_cycle.v1"
    assert result["ran"] is True
    assert result["projectization"]["manifest"]["counts"]["selected_repos"] == 1
    assert result["holdout_benchmark"]["counts"]["cases"] >= 1
    assert Path(result["files"]["flywheel_report"]).exists()
    state = json.loads((tmp_path / "corpus" / "scheduler_state.json").read_text(encoding="utf-8"))
    assert Path(state["latest_projectization_manifest"]).exists()
    assert Path(state["latest_holdout_benchmark_path"]).exists()


def test_flywheel_cycle_consumes_previous_holdout_deltas(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    previous_eval = tmp_path / "previous_eval.json"
    previous_eval.write_text(
        json.dumps({"feedback_deltas": {"recall_at_5_delta": -0.2, "citation_precision_delta": -0.1}}),
        encoding="utf-8",
    )

    result = run_corpus_flywheel_cycle(
        CorpusFlywheelInput(
            output_root=tmp_path / "corpus",
            seed_queries=("spring boot",),
            local_repos=(repo,),
            repo_limit=1,
            min_stars=0,
            quality_threshold=0.0,
            downstream_metrics_path=previous_eval,
            force=True,
        )
    )

    assert result["downstream_metrics"]["recall_at_5_delta"] == -0.2
    feedback_path = Path(result["scheduler_cycle"]["cycle_record_path"]).parent / "feedback_report.json"
    feedback = json.loads(feedback_path.read_text(encoding="utf-8"))
    assert "retrieval_repair" in feedback["strategy"]["mode"]
    assert feedback["strategy"]["routing"]["grounding_required"] is True


def test_flywheel_action_is_available(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    result = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "github_corpus_flywheel_cycle",
            "args": {
                "output_root": "./corpus",
                "seed_queries": ["spring boot"],
                "local_repos": [str(repo)],
                "repo_limit": 1,
                "min_stars": 0,
                "quality_threshold": 0.0,
                "force": True,
            },
        },
    )

    assert result["ok"] is True
    assert result["flywheel"]["status"] == "completed"
    assert result["flywheel"]["holdout_benchmark"]["counts"]["cases"] >= 1
