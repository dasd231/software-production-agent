from __future__ import annotations

import json
from pathlib import Path

from agent.core.executor import run_action
from agent.project_model.repo_memory import RepoMemoryBuildInput, build_repo_memory
from agent.project_model.task_synthesis import ProjectTaskSynthesisInput, synthesize_project_tasks


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
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")


def test_synthesize_project_tasks_exports_sft_and_retrieval_pairs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_demo_repo(repo)
    memory = build_repo_memory(RepoMemoryBuildInput(repo_path=repo, output_dir=tmp_path / "memory"))

    result = synthesize_project_tasks(
        ProjectTaskSynthesisInput(memory_dirs=(Path(memory.output_dir),), output_dir=tmp_path / "tasks")
    )
    examples = [
        json.loads(line)
        for line in Path(result.files["training_examples"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert result.manifest["schema"] == "project_task_manifest.v1"
    assert result.counts["repo_structure_mapping"] == 1
    assert result.counts["architecture_summary"] == 1
    assert result.counts["symbol_grounding"] >= 3
    assert result.counts["evidence_retrieval"] >= 3
    assert all(row["citations"] for row in examples)
    assert Path(result.files["retrieval_pairs"]).exists()


def test_project_task_synthesis_build_action_resolves_memory_dirs(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _build_demo_repo(repo)
    run_action(
        tmp_path,
        {
            "type": "action",
            "action": "project_repo_memory_build",
            "args": {"repo_path": "./repo", "output_dir": "./memory"},
        },
    )

    out = run_action(
        tmp_path,
        {
            "type": "action",
            "action": "project_task_synthesis_build",
            "args": {"memory_dirs": ["./memory"], "output_dir": "./tasks"},
        },
    )

    assert out["ok"] is True
    assert out["counts"]["training_examples"] >= 8
    assert Path(out["files"]["manifest"]).exists()
