"""集中配置：环境变量优先，本地 .env.local 兜底，便于部署与调参。

函数流程图：
    AppConfig.from_env()
      -> _load_project_env() 读取 AGENT_ENV_FILE 或项目根 .env.local
      -> 不覆盖系统环境变量，只补缺失 key
      -> 读取环境变量
      -> 读取 AGENT_LLM_PROVIDER / 模型配置
      -> _env_int/_env_float/_env_bool 做容错转换
      -> 对关键数值做下限保护
      -> 返回不可变 AppConfig
      -> agent_loop.run_agent_loop()
        -> 转成 ExecutionLimits / Planner / Brain / RAG / ship gate 等运行时策略

你可以继续练算法/工程化的点：
    1. 配置校验：现在是简单默认值兜底；可以做成 typed schema + 错误报告。
    2. 参数调优：timeout/output 上限现在是静态值；可以按项目规模和历史失败动态估计。
    3. 配置来源：现在只读环境变量；可以合并 pyproject、JSON、CLI，并设计优先级。
    4. 安全策略：可以把危险命令、输出裁剪、重试预算统一建模成 policy profile。
    5. 密钥管理：现在是 .env.local 本地兜底；生产环境可接入系统 keyring/secret manager。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

_ENV_LOADED = False


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _strip_env_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _load_env_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        if not key or key in os.environ:
            continue
        os.environ[key] = _strip_env_quotes(value)


def _load_project_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    explicit = os.environ.get("AGENT_ENV_FILE", "").strip()
    env_path = Path(explicit).expanduser() if explicit else (_project_root() / ".env.local")
    _load_env_file(env_path.resolve())
    _ENV_LOADED = True


def _env_bool(key: str, default: bool) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if v is None or not v.strip():
        return default
    try:
        return int(v)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    if v is None or not v.strip():
        return default
    try:
        out = float(v)
    except ValueError:
        return default
    return out if math.isfinite(out) else default


def _env_list(key: str) -> tuple[str, ...]:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return ()
    normalized = raw.replace(";", ",").replace("\n", ",")
    return tuple(part.strip() for part in normalized.split(",") if part.strip())


@dataclass(frozen=True)
class AppConfig:
    """运行时策略；不改变 AIread 目录契约，只增加可调旋钮。"""

    max_agent_iterations: int
    max_write_bytes: int
    default_command_timeout: float
    max_command_timeout: float
    max_command_output_chars: int
    llm_provider: str
    planner_use_llm: bool
    brain_model: str
    planner_model: str
    session_log_jsonl: bool
    verbose_logging: bool
    policy_extra_path: str | None
    event_log: bool
    granted_permissions: tuple[str, ...]
    confirmed_actions: tuple[str, ...]
    resume_clear_errors: bool
    ship_gate_min_review_score: float
    ship_gate_min_health_score: float
    enable_skill_hints: bool
    enable_rag_hints: bool
    enable_mcp_capabilities: bool
    skill_hints_limit: int
    rag_hints_top_k: int
    enable_learning_rag: bool
    learning_rag_dirs: tuple[str, ...]
    learning_rag_top_k: int
    learning_rag_bm25: bool

    @staticmethod
    def from_env() -> AppConfig:
        _load_project_env()
        pol = os.environ.get("AGENT_POLICY_JSON", "").strip()
        learning_rag_dirs = _env_list("AGENT_LEARNING_RAG_DIRS")
        return AppConfig(
            max_agent_iterations=_env_int("AGENT_MAX_ITERATIONS", 48),
            max_write_bytes=_env_int("AGENT_MAX_WRITE_BYTES", 1_500_000),
            default_command_timeout=max(_env_float("AGENT_CMD_TIMEOUT", 120.0), 1.0),
            max_command_timeout=max(_env_float("AGENT_CMD_MAX_TIMEOUT", 600.0), 1.0),
            max_command_output_chars=max(_env_int("AGENT_CMD_MAX_OUTPUT_CHARS", 200_000), 0),
            llm_provider=os.environ.get("AGENT_LLM_PROVIDER", "openai").strip().lower() or "openai",
            planner_use_llm=_env_bool("AGENT_PLANNER_LLM", False),
            brain_model=os.environ.get("OPENAI_BRAIN_MODEL", "gpt-4o-mini"),
            planner_model=os.environ.get("OPENAI_PLANNER_MODEL", "gpt-4o-mini"),
            session_log_jsonl=_env_bool("AGENT_SESSION_LOG", True),
            verbose_logging=_env_bool("AGENT_VERBOSE", False),
            policy_extra_path=pol or None,
            event_log=_env_bool("AGENT_EVENTS_LOG", False),
            granted_permissions=_env_list("AGENT_GRANTED_PERMISSIONS") or ("*",),
            confirmed_actions=_env_list("AGENT_CONFIRMED_ACTIONS"),
            resume_clear_errors=_env_bool("AGENT_RESUME_CLEAR_ERRORS", False),
            ship_gate_min_review_score=_env_float("AGENT_SHIP_MIN_REVIEW_SCORE", 6.0),
            ship_gate_min_health_score=_env_float("AGENT_SHIP_MIN_HEALTH_SCORE", 7.0),
            enable_skill_hints=_env_bool("AGENT_ENABLE_SKILL_HINTS", True),
            enable_rag_hints=_env_bool("AGENT_ENABLE_RAG_HINTS", True),
            enable_mcp_capabilities=_env_bool("AGENT_ENABLE_MCP_CAPABILITIES", True),
            skill_hints_limit=max(_env_int("AGENT_SKILL_HINTS_LIMIT", 4), 1),
            rag_hints_top_k=max(_env_int("AGENT_RAG_HINTS_TOP_K", 3), 1),
            enable_learning_rag=_env_bool("AGENT_ENABLE_LEARNING_RAG", bool(learning_rag_dirs)),
            learning_rag_dirs=learning_rag_dirs,
            learning_rag_top_k=max(_env_int("AGENT_LEARNING_RAG_TOP_K", 2), 1),
            learning_rag_bm25=_env_bool("AGENT_LEARNING_RAG_BM25", True),
        )
