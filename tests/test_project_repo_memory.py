from __future__ import annotations

import json
from pathlib import Path

from agent.core.executor import run_action
from agent.project_model.repo_memory import RepoMemoryBuildInput, build_repo_memory


def _build_demo_repo(root: Path) -> None:
    (root / "README.md").write_text("# Demo\n\nA tiny demo repository.", encoding="utf-8")
    (root / "app.py").write_text(
        "\n".join(
            [
                "class Greeter:",
                "    def hello(self):",
                "        return 'hello'",
                "",
                "def main():",
                "    return Greeter().hello()",
            ]
        ),
        encoding="utf-8",
    )
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("def test_demo():\n    assert True\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")


def test_build_repo_memory_writes_project_level_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_demo_repo(repo)

    result = build_repo_memory(RepoMemoryBuildInput(repo_path=repo, output_dir=tmp_path / "out"))
    symbols = [
        json.loads(line)
        for line in Path(result.files["symbol_index"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result.manifest["schema"] == "repo_memory_manifest.v1"
    assert result.counts["files"] >= 4
    assert {row["name"] for row in symbols} >= {"Greeter", "hello", "main"}
    assert Path(result.files["evidence_index"]).exists()


def test_project_repo_memory_build_action_uses_workspace_relative_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_demo_repo(repo)

    out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "project_repo_memory_build",
            "args": {"repo_path": "./repo", "output_dir": "./memory"},
        },
    )

    assert out["ok"] is True
    assert Path(out["files"]["manifest"]).exists()
    assert out["counts"]["symbols"] >= 3
