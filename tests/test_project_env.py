"""Project-local environment file loading tests."""

from __future__ import annotations

from pathlib import Path

import agent.config as config_mod
from agent.config import AppConfig


def test_project_env_file_sets_missing_values(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                "# local settings",
                "OPENAI_BRAIN_MODEL=local-brain",
                "OPENAI_PLANNER_MODEL='local-planner'",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config_mod, "_ENV_LOADED", False)
    monkeypatch.setenv("AGENT_ENV_FILE", str(env_file))
    monkeypatch.delenv("OPENAI_BRAIN_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_PLANNER_MODEL", raising=False)

    cfg = AppConfig.from_env()

    assert cfg.brain_model == "local-brain"
    assert cfg.planner_model == "local-planner"


def test_project_env_file_does_not_override_existing_env(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("OPENAI_BRAIN_MODEL=from-file\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ENV_LOADED", False)
    monkeypatch.setenv("AGENT_ENV_FILE", str(env_file))
    monkeypatch.setenv("OPENAI_BRAIN_MODEL", "from-real-env")

    cfg = AppConfig.from_env()

    assert cfg.brain_model == "from-real-env"


def test_project_env_file_accepts_utf8_bom(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("OPENAI_API_KEY=local-key\n", encoding="utf-8-sig")
    monkeypatch.setattr(config_mod, "_ENV_LOADED", False)
    monkeypatch.setenv("AGENT_ENV_FILE", str(env_file))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    AppConfig.from_env()

    assert config_mod.os.environ["OPENAI_API_KEY"] == "local-key"
