"""Learning pipeline component and orchestration tests."""

from __future__ import annotations

import json
from pathlib import Path

from agent.learning.cli import main as learning_cli_main
from agent.learning.code_slicer import slice_repository
from agent.learning.filters import filter_repositories
from agent.learning.github_search import GitHubSearchClient
from agent.learning.knowledge_cards import build_knowledge_cards
from agent.learning.orchestrator import run_learning_pipeline
from agent.learning.readme_parser import parse_readme
from agent.learning.rag_qa import answer_question
from agent.learning.sandbox import run_sandbox_tests
from agent.learning.schemas import LearningPipelineConfig, RepoCandidate
from agent.learning.store import ask_learning_run
from agent.learning.structure_parser import parse_structure
from agent.learning.training_export import build_training_examples
from agent.learning.vector_store import build_vector_index
from agent.learning.web_search import search_web


def _make_repo(root: Path) -> Path:
    repo = root / "sample_repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "README.md").write_text(
        """# Sample Agent Toolkit

This project demonstrates a small Flask API and a RAG helper.

## Install

pip install flask

## Usage

Run python app.py and open /hello.
""",
        encoding="utf-8",
    )
    (repo / "app.py").write_text(
        """from flask import Flask

app = Flask(__name__)

@app.get('/hello')
def hello():
    return 'ok'
""",
        encoding="utf-8",
    )
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("flask>=3\n", encoding="utf-8")
    (repo / ".agent_state.json").write_text('{"internal": true}\n', encoding="utf-8")
    return repo


def _make_low_quality_repo(root: Path) -> Path:
    repo = root / "low_quality_repo"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return repo


def test_learning_components_parse_slice_vector_card_and_sandbox(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)

    readme = parse_readme(repo)
    structure = parse_structure(repo)
    slices = slice_repository(repo, max_lines=20)
    index = build_vector_index(slices)
    cards = build_knowledge_cards(
        RepoCandidate(full_name="local/sample_repo", html_url=f"file://{repo}", local_path=str(repo)),
        readme,
        structure,
        slices,
    )
    answer = answer_question("Flask hello route", index, cards)
    examples = build_training_examples(
        [
            run_learning_pipeline(
                LearningPipelineConfig(
                    query="Flask hello route",
                    output_dir=tmp_path / "component_out",
                    local_repos=(repo,),
                    repo_limit=1,
                    enable_sandbox=True,
                )
            ).repos[0]
        ],
        index,
        query="Flask hello route",
    )
    sandbox = run_sandbox_tests(repo)

    assert readme.title == "Sample Agent Toolkit"
    assert "python" in structure.languages
    assert "app.py" in structure.entrypoints
    assert ".agent_state.json" not in structure.files
    assert any(sl.path == "app.py" for sl in slices)
    assert index.search("Flask hello", top_k=2)
    assert cards
    assert "相关代码证据" in str(answer["answer"])
    assert examples
    assert examples[0].citations
    assert sandbox.ok is True


def test_training_export_can_expand_grounded_answer_queries(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    result = run_learning_pipeline(
        LearningPipelineConfig(
            query="Flask hello route",
            output_dir=tmp_path / "rag_multi_out",
            local_repos=(repo,),
            repo_limit=1,
            enable_sandbox=True,
            rag_training_queries=("如何运行这个项目？",),
            rag_training_query_limit=3,
        )
    )
    examples = [
        json.loads(line)
        for line in (Path(result.output_dir) / "training_examples.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    grounded = [row for row in examples if row.get("task_type") == "rag_grounded_answer"]

    assert len(grounded) == 3
    assert {row["metadata"]["query"] for row in grounded} >= {"Flask hello route", "如何运行这个项目？"}


def test_filter_repositories_by_stars_license_and_time() -> None:
    repos = [
        RepoCandidate(
            full_name="a/old",
            html_url="https://example.test/old",
            stargazers_count=10,
            license_spdx="MIT",
            updated_at="2020-01-01T00:00:00Z",
        ),
        RepoCandidate(
            full_name="b/new",
            html_url="https://example.test/new",
            stargazers_count=100,
            license_spdx="Apache-2.0",
            updated_at="2026-01-01T00:00:00Z",
        ),
    ]

    out = filter_repositories(
        repos,
        min_stars=50,
        allowed_licenses=["Apache-2.0"],
        updated_after="2025-01-01T00:00:00Z",
    )

    assert [x.full_name for x in out] == ["b/new"]


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_github_search_parses_repository_items() -> None:
    payload = {
        "items": [
            {
                "full_name": "owner/repo",
                "html_url": "https://github.com/owner/repo",
                "clone_url": "https://github.com/owner/repo.git",
                "description": "demo",
                "stargazers_count": 42,
                "license": {"spdx_id": "MIT"},
                "pushed_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-02T00:00:00Z",
                "default_branch": "main",
                "topics": ["agent"],
            }
        ]
    }
    client = GitHubSearchClient(opener=lambda *_args, **_kwargs: _FakeResponse(payload))

    out = client.search("agent", per_page=1)

    assert out[0].full_name == "owner/repo"
    assert out[0].license_spdx == "MIT"
    assert out[0].topics == ("agent",)


def test_web_search_parses_duckduckgo_payload() -> None:
    payload = {
        "Heading": "Agent",
        "AbstractURL": "https://example.test/agent",
        "AbstractText": "Agent docs",
        "RelatedTopics": [{"FirstURL": "https://example.test/rag", "Text": "RAG - retrieval docs"}],
    }
    results = search_web("agent", opener=lambda *_args, **_kwargs: _FakeResponse(payload))

    assert results[0].url == "https://example.test/agent"
    assert results[1].title == "RAG"


def test_learning_orchestrator_runs_local_pipeline(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    out_dir = tmp_path / "learning_out"

    result = run_learning_pipeline(
        LearningPipelineConfig(
            query="Flask hello RAG",
            output_dir=out_dir,
            local_repos=(repo,),
            repo_limit=1,
            enable_web_search=False,
            enable_sandbox=True,
        )
    )

    assert len(result.repos) == 1
    assert result.promoted_repos == 1
    assert result.rejected_repos == 0
    assert result.vector_records > 0
    assert (out_dir / "vector_index.jsonl").exists()
    assert (out_dir / "vector_meta.json").exists()
    assert (out_dir / "knowledge_cards.json").exists()
    assert (out_dir / "knowledge_quality_report.json").exists()
    assert (out_dir / "knowledge_promotion.json").exists()
    assert (out_dir / "slice_quality_report.json").exists()
    assert (out_dir / "card_quality_report.json").exists()
    assert (out_dir / "quality_funnel.json").exists()
    assert (out_dir / "training_examples.jsonl").exists()
    assert (out_dir / "result.json").exists()
    assert Path(result.report_path).exists()
    assert result.training_examples > 0
    copied_repo = out_dir / "repos" / "local_sample_repo"
    assert not (copied_repo / ".agent_state.json").exists()

    answer = ask_learning_run(out_dir, "hello route 在哪里", top_k=2)
    assert "相关代码证据" in str(answer["answer"])
    assert (out_dir / "answers.jsonl").exists()


def test_learning_orchestrator_only_publishes_promoted_assets(tmp_path: Path) -> None:
    good_repo = _make_repo(tmp_path)
    low_quality_repo = _make_low_quality_repo(tmp_path)
    out_dir = tmp_path / "learning_gated"

    result = run_learning_pipeline(
        LearningPipelineConfig(
            query="Flask hello RAG",
            output_dir=out_dir,
            local_repos=(good_repo, low_quality_repo),
            repo_limit=2,
            enable_web_search=False,
            enable_sandbox=True,
        )
    )

    promotion = json.loads((out_dir / "knowledge_promotion.json").read_text(encoding="utf-8"))
    cards = json.loads((out_dir / "knowledge_cards.json").read_text(encoding="utf-8"))
    examples = [
        json.loads(line)
        for line in (out_dir / "training_examples.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert len(result.repos) == 2
    assert result.promoted_repos == 1
    assert result.rejected_repos == 1
    assert promotion["summary"] == {"repos": 2, "promoted": 1, "rejected": 1}
    assert promotion["rejected"][0]["repo"] == "local/low_quality_repo"
    assert "missing_readme" in promotion["rejected"][0]["reasons"]
    assert cards
    assert all("low_quality_repo" not in row.get("metadata", {}).get("repo", "") for row in examples)


def test_learning_cli_can_ask_existing_output(tmp_path: Path, capsys) -> None:
    repo = _make_repo(tmp_path)
    out_dir = tmp_path / "learning_cli"
    code = learning_cli_main(
        [
            "--query",
            "Flask hello",
            "--local-repo",
            str(repo),
            "--output",
            str(out_dir),
            "--ask",
            "hello route 在哪里",
        ]
    )
    first = capsys.readouterr().out
    assert code == 0
    assert "training examples:" in first
    assert (out_dir / "answers.jsonl").exists()

    code2 = learning_cli_main(["--output", str(out_dir), "--ask", "Flask 怎么运行"])
    second = capsys.readouterr().out
    assert code2 == 0
    assert "相关代码证据" in second
