from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.corpus_intelligence.cli import main
from agent.corpus_intelligence.flywheel import CorpusFlywheelInput, run_corpus_flywheel_cycle
from agent.corpus_intelligence.status import build_corpus_flywheel_status


def _make_repo(root: Path) -> Path:
    repo = root / "status_repo"
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


def test_corpus_status_reads_latest_flywheel_artifacts(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    run_corpus_flywheel_cycle(
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

    status = build_corpus_flywheel_status(tmp_path / "corpus")

    assert status["schema"] == "github_corpus_flywheel_status.v1"
    assert status["state"]["exists"] is True
    assert status["artifacts"]["latest_holdout_benchmark"]["exists"] is True
    assert status["counts"]["projectization"]["selected_repos"] == 1
    assert "run offline predictions" in status["next_steps"][0]


def test_corpus_status_action_and_cli_are_available(tmp_path: Path) -> None:
    result = run_action(
        tmp_path,
        {"type": "action", "action": "github_corpus_status", "args": {"output_root": "./missing"}},
    )
    code = main(["status", "--output-root", str(tmp_path / "missing")])

    assert result["ok"] is True
    assert result["status"]["state"]["exists"] is False
    assert code == 0
