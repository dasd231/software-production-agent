from __future__ import annotations

import json
from pathlib import Path

from agent.chains.github_crawler import (
    CrawlProfileInput,
    crawl_frontend_backend_repos,
    detect_architecture,
)
from agent.chains.training import TrainingPrepareInput, prepare_fine_tuning_dataset
from agent.learning.structure_parser import parse_structure


def _make_fullstack_repo(root: Path) -> Path:
    repo = root / "fullstack_repo"
    (repo / "backend" / "src" / "main" / "java" / "demo").mkdir(parents=True)
    (repo / "backend" / "src" / "test" / "java" / "demo").mkdir(parents=True)
    (repo / "frontend" / "src").mkdir(parents=True)
    (repo / "docs").mkdir()
    (repo / "README.md").write_text("# Demo\n\nSpring Boot + Vue employee CRUD.", encoding="utf-8")
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
    (repo / "frontend" / "src" / "App.vue").write_text("<template>Employee CRUD</template>", encoding="utf-8")
    return repo


def test_detect_architecture_finds_fullstack_spring_vue(tmp_path: Path) -> None:
    repo = _make_fullstack_repo(tmp_path)
    structure = parse_structure(repo)

    arch = detect_architecture(repo, structure)

    assert arch["shape"] == "fullstack"
    assert "spring-boot" in arch["backend"]
    assert "vue" in arch["frontend"]
    assert "frontend-backend" in arch["tags"]


def test_crawl_frontend_backend_repos_exports_solution_backup(tmp_path: Path) -> None:
    repo = _make_fullstack_repo(tmp_path)
    out_dir = tmp_path / "crawl"

    result = crawl_frontend_backend_repos(
        CrawlProfileInput(
            query="spring vue",
            output_dir=out_dir,
            local_repos=(repo,),
            repo_limit=1,
            min_stars=0,
            quality_threshold=0.0,
        )
    )

    assert len(result.profiles) == 1
    profile = result.profiles[0]
    assert profile["architecture"]["shape"] == "fullstack"
    assert profile["quality"]["score"] >= 6.5
    assert "routing" in profile
    assert "train_now" in profile["routing"]["routes"]
    assert profile["evaluation"]["stage"] == "crawler.repo_profile"
    assert result.evaluation["stage"] == "crawler.run"
    assert Path(result.files["evaluation_report"]).exists()
    assert Path(result.files["routing_report"]).exists()
    assert Path(result.files["feedback_report"]).exists()
    assert Path(result.files["run_manifest"]).exists()
    assert result.exported_solutions
    solution_dir = Path(result.exported_solutions[0])
    assert (solution_dir / "solution_manifest.json").exists()
    assert (solution_dir / "docs" / "SOLUTION_BACKUP.md").exists()
    manifest = json.loads((solution_dir / "solution_manifest.json").read_text(encoding="utf-8"))
    assert "frontend-backend" in manifest["retrieval_tags"]
    assert manifest["schema_version"] == "solution_manifest.v2"
    assert manifest["training_eligible"] is True


def test_crawled_solution_can_feed_training_prepare(tmp_path: Path) -> None:
    repo = _make_fullstack_repo(tmp_path)
    crawl = crawl_frontend_backend_repos(
        CrawlProfileInput(
            query="spring vue",
            output_dir=tmp_path / "crawl",
            local_repos=(repo,),
            repo_limit=1,
            min_stars=0,
            quality_threshold=0.0,
        )
    )

    training = prepare_fine_tuning_dataset(
        TrainingPrepareInput(
            output_dir=tmp_path / "training",
            solution_dirs=(Path(crawl.files["solutions_dir"]),),
            eval_ratio=0.0,
            min_chars=20,
        )
    )

    assert training.total_examples >= 1
    assert Path(training.files["dataset"]).exists()
    assert training.quality["with_citations"] >= 1
    assert training.evaluation["stage"] == "training.dataset_prepare"
    assert training.governance["stage"] == "training.dataset_governance"
