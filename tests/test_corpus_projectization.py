from __future__ import annotations

import json
from pathlib import Path

from agent.chains.github_crawler import CrawlProfileInput, crawl_frontend_backend_repos
from agent.core.executor import run_action
from agent.corpus_intelligence.projectization import (
    CorpusProjectizationInput,
    build_corpus_projectization_plan,
    materialize_corpus_projectization,
)


def _make_repo(root: Path) -> Path:
    repo = root / "project_repo"
    (repo / "backend" / "src" / "main" / "java" / "demo").mkdir(parents=True)
    (repo / "backend" / "src" / "test" / "java" / "demo").mkdir(parents=True)
    (repo / "frontend" / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "README.md").write_text("# Demo\n\nSpring Boot + Vue demo.", encoding="utf-8")
    (repo / "docs" / "ARCHITECTURE.md").write_text("frontend/backend split", encoding="utf-8")
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
    (repo / "package.json").write_text(
        json.dumps({"dependencies": {"vue": "^3.0.0"}, "devDependencies": {"@vitejs/plugin-vue": "^5.0.0"}}),
        encoding="utf-8",
    )
    (repo / "vite.config.js").write_text("import vue from '@vitejs/plugin-vue'", encoding="utf-8")
    (repo / "frontend" / "src" / "App.vue").write_text("<template>Demo</template>", encoding="utf-8")
    return repo


def _crawl(tmp_path: Path) -> Path:
    repo = _make_repo(tmp_path)
    result = crawl_frontend_backend_repos(
        CrawlProfileInput(
            query="spring vue",
            output_dir=tmp_path / "crawl",
            local_repos=(repo,),
            repo_limit=1,
            min_stars=0,
            quality_threshold=0.0,
        )
    )
    return Path(result.output_dir)


def test_projectization_plan_isolates_holdout_before_training(tmp_path: Path) -> None:
    crawl_dir = _crawl(tmp_path)
    plan = build_corpus_projectization_plan(
        CorpusProjectizationInput(crawl_output_dir=crawl_dir, output_dir=tmp_path / "projectized")
    )

    assert plan["schema"] == "corpus_projectization_plan.v1"
    assert plan["selected"][0]["primary_route"] == "benchmark_holdout"
    assert plan["selected"][0]["usage"] == "holdout_only_no_training"
    assert plan["selection_policy"]["holdout_isolation"].startswith("benchmark_holdout")


def test_materialize_projectization_builds_route_separated_assets(tmp_path: Path) -> None:
    crawl_dir = _crawl(tmp_path)
    result = materialize_corpus_projectization(
        CorpusProjectizationInput(crawl_output_dir=crawl_dir, output_dir=tmp_path / "projectized")
    )

    assert result.manifest["schema"] == "corpus_projectization_manifest.v1"
    assert result.manifest["counts"]["selected_repos"] == 1
    assert result.manifest["counts"]["routes"]["benchmark_holdout"] == 1
    task_assets = result.manifest["task_assets"]
    assert task_assets[0]["route"] == "benchmark_holdout"
    assert task_assets[0]["usage"] == "holdout_only_no_training"
    assert Path(task_assets[0]["files"]["training_examples"]).exists()
    assert Path(result.files["manifest"]).exists()


def test_projectization_actions_are_available(tmp_path: Path) -> None:
    crawl_dir = _crawl(tmp_path)
    plan = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "github_corpus_projectization_plan",
            "args": {"crawl_output_dir": str(crawl_dir), "output_dir": "./projectized-plan"},
        },
    )
    result = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "github_corpus_projectize",
            "args": {"crawl_output_dir": str(crawl_dir), "output_dir": "./projectized"},
        },
    )

    assert plan["ok"] is True
    assert plan["plan"]["schema"] == "corpus_projectization_plan.v1"
    assert result["ok"] is True
    assert result["manifest"]["schema"] == "corpus_projectization_manifest.v1"
