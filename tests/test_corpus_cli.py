from __future__ import annotations

from pathlib import Path

from agent.corpus_intelligence.cli import main


def _make_repo(root: Path) -> Path:
    repo = root / "cli_repo"
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


def test_corpus_cli_flywheel_runs_one_off_cycle(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    code = main(
        [
            "flywheel",
            "--output-root",
            str(tmp_path / "corpus"),
            "--seed-query",
            "spring boot",
            "--local-repo",
            str(repo),
            "--repo-limit",
            "1",
            "--min-stars",
            "0",
            "--quality-threshold",
            "0",
            "--force",
        ]
    )

    assert code == 0
    assert (tmp_path / "corpus" / "scheduler_state.json").exists()


def test_corpus_cli_training_bundle_reports_invalid_without_train_route(tmp_path: Path) -> None:
    projectization_dir = tmp_path / "projectized"
    projectization_dir.mkdir()
    (projectization_dir / "corpus_projectization_manifest.json").write_text(
        '{"schema":"corpus_projectization_manifest.v1","task_assets":[]}',
        encoding="utf-8",
    )

    code = main(
        [
            "training-bundle",
            "--projectization-dir",
            str(projectization_dir),
            "--output-dir",
            str(tmp_path / "bundle"),
        ]
    )

    assert code == 2
    assert (tmp_path / "bundle" / "corpus_training_bundle_manifest.json").exists()
