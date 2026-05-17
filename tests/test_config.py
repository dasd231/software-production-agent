from agent.config import AppConfig


def test_config_llm_provider_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_LLM_PROVIDER", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.llm_provider == "openai"

    monkeypatch.setenv("AGENT_LLM_PROVIDER", "groq")
    cfg2 = AppConfig.from_env()
    assert cfg2.llm_provider == "groq"

    monkeypatch.setenv("AGENT_LLM_PROVIDER", "deepseek")
    cfg3 = AppConfig.from_env()
    assert cfg3.llm_provider == "deepseek"


def test_config_ship_gate_defaults(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_SHIP_MIN_REVIEW_SCORE", raising=False)
    monkeypatch.delenv("AGENT_SHIP_MIN_HEALTH_SCORE", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.ship_gate_min_review_score == 6.0
    assert cfg.ship_gate_min_health_score == 7.0


def test_config_ship_gate_override(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_SHIP_MIN_REVIEW_SCORE", "6.8")
    monkeypatch.setenv("AGENT_SHIP_MIN_HEALTH_SCORE", "7.5")
    cfg = AppConfig.from_env()
    assert cfg.ship_gate_min_review_score == 6.8
    assert cfg.ship_gate_min_health_score == 7.5


def test_config_context_enrichment_defaults_and_override(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_ENABLE_SKILL_HINTS", raising=False)
    monkeypatch.delenv("AGENT_ENABLE_RAG_HINTS", raising=False)
    monkeypatch.delenv("AGENT_ENABLE_MCP_CAPABILITIES", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.enable_skill_hints is True
    assert cfg.enable_rag_hints is True
    assert cfg.enable_mcp_capabilities is True

    monkeypatch.setenv("AGENT_ENABLE_SKILL_HINTS", "0")
    monkeypatch.setenv("AGENT_ENABLE_RAG_HINTS", "0")
    monkeypatch.setenv("AGENT_ENABLE_MCP_CAPABILITIES", "0")
    monkeypatch.setenv("AGENT_SKILL_HINTS_LIMIT", "2")
    monkeypatch.setenv("AGENT_RAG_HINTS_TOP_K", "1")
    cfg2 = AppConfig.from_env()
    assert cfg2.enable_skill_hints is False
    assert cfg2.enable_rag_hints is False
    assert cfg2.enable_mcp_capabilities is False
    assert cfg2.skill_hints_limit == 2
    assert cfg2.rag_hints_top_k == 1


def test_config_learning_rag_dirs_enable_learning_rag(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_LEARNING_RAG_DIRS", "runs/a;runs/b")
    monkeypatch.delenv("AGENT_ENABLE_LEARNING_RAG", raising=False)
    monkeypatch.setenv("AGENT_LEARNING_RAG_TOP_K", "3")
    monkeypatch.setenv("AGENT_LEARNING_RAG_BM25", "0")

    cfg = AppConfig.from_env()

    assert cfg.enable_learning_rag is True
    assert cfg.learning_rag_dirs == ("runs/a", "runs/b")
    assert cfg.learning_rag_top_k == 3
    assert cfg.learning_rag_bm25 is False


def test_config_command_limits_defaults_and_override(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_CMD_TIMEOUT", raising=False)
    monkeypatch.delenv("AGENT_CMD_MAX_TIMEOUT", raising=False)
    monkeypatch.delenv("AGENT_CMD_MAX_OUTPUT_CHARS", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.default_command_timeout == 120.0
    assert cfg.max_command_timeout == 600.0
    assert cfg.max_command_output_chars == 200_000

    monkeypatch.setenv("AGENT_CMD_TIMEOUT", "bad")
    monkeypatch.setenv("AGENT_CMD_MAX_TIMEOUT", "240")
    monkeypatch.setenv("AGENT_CMD_MAX_OUTPUT_CHARS", "1234")
    cfg2 = AppConfig.from_env()
    assert cfg2.default_command_timeout == 120.0
    assert cfg2.max_command_timeout == 240.0
    assert cfg2.max_command_output_chars == 1234

    monkeypatch.setenv("AGENT_CMD_TIMEOUT", "nan")
    monkeypatch.setenv("AGENT_CMD_MAX_TIMEOUT", "inf")
    cfg3 = AppConfig.from_env()
    assert cfg3.default_command_timeout == 120.0
    assert cfg3.max_command_timeout == 600.0


def test_config_execution_governance_defaults_and_override(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_GRANTED_PERMISSIONS", raising=False)
    monkeypatch.delenv("AGENT_CONFIRMED_ACTIONS", raising=False)
    cfg = AppConfig.from_env()
    assert cfg.granted_permissions == ("*",)
    assert cfg.confirmed_actions == ()

    monkeypatch.setenv("AGENT_GRANTED_PERMISSIONS", "workspace:read,workspace:write")
    monkeypatch.setenv("AGENT_CONFIRMED_ACTIONS", "git_init;solution_publish")
    cfg2 = AppConfig.from_env()
    assert cfg2.granted_permissions == ("workspace:read", "workspace:write")
    assert cfg2.confirmed_actions == ("git_init", "solution_publish")
