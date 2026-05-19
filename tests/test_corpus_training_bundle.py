from __future__ import annotations

import json
from pathlib import Path

from agent.chains.github_crawler import CrawlProfileInput, crawl_frontend_backend_repos
from agent.core.executor import run_action
from agent.corpus_intelligence.projectization import CorpusProjectizationInput, materialize_corpus_projectization
from agent.corpus_intelligence.training_bundle import CorpusTrainingBundleInput, build_corpus_training_bundle


def _make_repo(root: Path) -> Path:
    repo = root / "bundle_repo"
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


def _projectize(tmp_path: Path, *, allowed_routes: tuple[str, ...]) -> Path:
    repo = _make_repo(tmp_path)
    crawl = crawl_frontend_backend_repos(
        CrawlProfileInput(
            query="spring boot",
            output_dir=tmp_path / "crawl",
            local_repos=(repo,),
            repo_limit=1,
            min_stars=0,
            quality_threshold=0.0,
        )
    )
    projectized = materialize_corpus_projectization(
        CorpusProjectizationInput(
            crawl_output_dir=Path(crawl.output_dir),
            output_dir=tmp_path / "projectized",
            allowed_routes=allowed_routes,
        )
    )
    return Path(projectized.output_dir)


def test_training_bundle_excludes_holdout_and_reports_blocker(tmp_path: Path) -> None:
    projectized_dir = _projectize(tmp_path, allowed_routes=("train_now", "distill_pool", "benchmark_holdout"))

    result = build_corpus_training_bundle(
        CorpusTrainingBundleInput(projectization_dir=projectized_dir, output_dir=tmp_path / "bundle")
    )

    assert result.manifest["schema"] == "corpus_training_bundle_manifest.v1"
    assert result.manifest["validation"]["ok"] is False
    assert "no_trainable_route_task_dirs" in result.manifest["validation"]["blockers"]
    assert result.manifest["holdout_assets"]
    assert result.manifest["learning_dirs"] == []


def test_training_bundle_can_materialize_training_prepare_for_train_route(tmp_path: Path) -> None:
    projectized_dir = _projectize(tmp_path, allowed_routes=("train_now", "distill_pool"))

    result = build_corpus_training_bundle(
        CorpusTrainingBundleInput(
            projectization_dir=projectized_dir,
            output_dir=tmp_path / "bundle",
            include_routes=("train_now",),
            prepare_dataset=True,
            min_chars=4,
            include_protocol_examples=False,
        )
    )

    assert result.manifest["validation"]["ok"] is True
    assert result.manifest["learning_dirs"]
    assert result.training_prepare["total_examples"] >= 1
    assert Path(result.training_prepare["files"]["dataset"]).exists()
    inputs = json.loads(Path(result.files["training_inputs"]).read_text(encoding="utf-8"))
    assert inputs["holdout_dirs"] == []


def test_training_bundle_action_is_available(tmp_path: Path) -> None:
    projectized_dir = _projectize(tmp_path, allowed_routes=("train_now",))

    result = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "github_corpus_training_bundle",
            "args": {
                "projectization_dir": str(projectized_dir),
                "output_dir": "./bundle",
                "include_routes": ["train_now"],
                "prepare_dataset": True,
                "min_chars": 4,
                "include_protocol_examples": False,
            },
        },
    )

    assert result["ok"] is True
    assert result["manifest"]["validation"]["ok"] is True
    assert result["training_prepare"]["total_examples"] >= 1
