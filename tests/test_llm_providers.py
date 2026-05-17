"""LLM provider registry tests."""

from __future__ import annotations

from agent.llm.providers import provider_choices_for_ui, resolve_llm_provider


def test_resolve_openai_provider_default() -> None:
    provider = resolve_llm_provider("openai", "")

    assert provider.name == "openai"
    assert provider.label == "OPENAI"
    assert provider.api_key_env == "OPENAI_API_KEY"
    assert provider.base_url is None
    assert provider.model == "gpt-4o-mini"


def test_resolve_groq_provider_default() -> None:
    provider = resolve_llm_provider("groq", "")

    assert provider.name == "groq"
    assert provider.label == "GROQ"
    assert provider.api_key_env == "GROQ_API_KEY"
    assert provider.base_url == "https://api.groq.com/openai/v1"
    assert provider.model == "openai/gpt-oss-20b"


def test_resolve_deepseek_provider_default() -> None:
    provider = resolve_llm_provider("deepseek", "")

    assert provider.name == "deepseek"
    assert provider.label == "DEEPSEEK"
    assert provider.api_key_env == "DEEPSEEK_API_KEY"
    assert provider.base_url == "https://api.deepseek.com"
    assert provider.model == "deepseek-v4-flash"


def test_resolve_main_deepseek_provider_uses_deploy_defaults(monkeypatch) -> None:
    monkeypatch.delenv("MAIN_DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("MAIN_DEEPSEEK_MODEL", raising=False)

    provider = resolve_llm_provider("main_deepseek", "")

    assert provider.name == "main_deepseek"
    assert provider.label == "MAIN DEEPSEEK"
    assert provider.api_key_env == "MAIN_DEEPSEEK_API_KEY"
    assert provider.base_url == "http://127.0.0.1:8000/v1"
    assert provider.model == "deepseek-v4-pro"
    assert provider.has_api_key is True


def test_resolve_main_deepseek_provider_reads_deploy_env(monkeypatch) -> None:
    monkeypatch.setenv("MAIN_DEEPSEEK_BASE_URL", "https://deepseek.internal/v1")
    monkeypatch.setenv("MAIN_DEEPSEEK_MODEL", "deepseek-custom")

    provider = resolve_llm_provider("local_deepseek", "")

    assert provider.name == "main_deepseek"
    assert provider.base_url == "https://deepseek.internal/v1"
    assert provider.model == "deepseek-custom"


def test_unknown_provider_falls_back_to_openai() -> None:
    provider = resolve_llm_provider("missing", "custom-model")

    assert provider.name == "openai"
    assert provider.model == "custom-model"


def test_provider_choices_include_frontend_options() -> None:
    choices = provider_choices_for_ui()
    names = {str(item["name"]) for item in choices}

    assert {"openai", "groq", "deepseek"} <= names
    assert "main_deepseek" not in names
    assert all(item["models"] for item in choices)
