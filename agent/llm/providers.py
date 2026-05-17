"""LLM Provider registry：OPENAI / GROQ / DEEPSEEK 的 OpenAI-compatible 接入层。

函数流程图：
    provider_choices_for_ui()
      -> 返回前端可渲染的 provider/model 列表

    resolve_llm_provider(provider, model)
      -> normalise provider
      -> 读取 ProviderSpec
      -> 选择显式 model / model_env / provider 默认 model
      -> 选择 base_url_env / provider 默认 base_url
      -> 生成 LLMProvider

    create_openai_compatible_client(provider)
      -> 从 provider.api_key_env 读取 key，本地 provider 可用 dummy key
      -> base_url 存在时传入 OpenAI(base_url=...)
      -> 返回 OpenAI SDK client

你可以继续练算法/工程化的点：
    1. 可用性探测：缓存 models.list()，只展示当前 key 可用模型。
    2. 动态路由：按 quota、latency、失败率和任务类型切换 provider。
    3. 模型评分：把 reward_avg、token 成本、响应格式成功率纳入选择。
    4. 降级策略：429/insufficient_quota 自动回退到离线模板或备用 provider。
    5. DeepSeek 路由：可按 deepseek-v4-flash/pro 的速度、reasoning 成本和 Action 合法率做模型选择。
    6. Secret 管理：现在读环境变量；生产可接 secret manager / keyring。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    api_key_env: str
    base_url: str | None
    default_model: str
    models: tuple[str, ...]
    api_key_required: bool = True
    ui_enabled: bool = True
    base_url_env: str | None = None
    model_env: str | None = None


@dataclass(frozen=True)
class LLMProvider:
    name: str
    label: str
    api_key_env: str
    base_url: str | None
    model: str
    api_key_required: bool = True

    @property
    def has_api_key(self) -> bool:
        if not self.api_key_required:
            return True
        return bool(os.environ.get(self.api_key_env, "").strip())


PROVIDER_SPECS: dict[str, ProviderSpec] = {
    "openai": ProviderSpec(
        name="openai",
        label="OPENAI",
        api_key_env="OPENAI_API_KEY",
        base_url=None,
        default_model="gpt-4o-mini",
        models=(
            "gpt-4o-mini",
            "gpt-4.1-mini",
            "gpt-4.1",
        ),
    ),
    "groq": ProviderSpec(
        name="groq",
        label="GROQ",
        api_key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        default_model="openai/gpt-oss-20b",
        models=(
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
            "llama-3.1-8b-instant",
            "qwen/qwen3-32b",
        ),
    ),
    "deepseek": ProviderSpec(
        name="deepseek",
        label="DEEPSEEK",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        models=(
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "deepseek-chat",
            "deepseek-reasoner",
        ),
    ),
    "main_deepseek": ProviderSpec(
        name="main_deepseek",
        label="MAIN DEEPSEEK",
        api_key_env="MAIN_DEEPSEEK_API_KEY",
        base_url="http://127.0.0.1:8000/v1",
        default_model="deepseek-v4-pro",
        models=(
            "deepseek-v4-pro",
            "deepseek-v4-flash",
            "deepseek-ai/DeepSeek-V4-Flash",
            "deepseek-r1-distill-qwen-32b",
            "deepseek-r1-distill-llama-70b",
        ),
        api_key_required=False,
        ui_enabled=False,
        base_url_env="MAIN_DEEPSEEK_BASE_URL",
        model_env="MAIN_DEEPSEEK_MODEL",
    ),
}


def normalise_provider(value: str | None) -> str:
    provider = str(value or "openai").strip().lower()
    if provider in ("local_deepseek", "local-deepseek", "main-deepseek"):
        provider = "main_deepseek"
    return provider if provider in PROVIDER_SPECS else "openai"


def resolve_llm_provider(provider: str | None, model: str | None = None) -> LLMProvider:
    name = normalise_provider(provider)
    spec = PROVIDER_SPECS[name]
    env_model = os.environ.get(spec.model_env or "", "").strip() if spec.model_env else ""
    selected_model = str(model or "").strip() or env_model or spec.default_model
    env_base_url = os.environ.get(spec.base_url_env or "", "").strip() if spec.base_url_env else ""
    return LLMProvider(
        name=spec.name,
        label=spec.label,
        api_key_env=spec.api_key_env,
        base_url=env_base_url or spec.base_url,
        model=selected_model,
        api_key_required=spec.api_key_required,
    )


def provider_choices_for_ui() -> list[dict[str, object]]:
    return [
        {
            "name": spec.name,
            "label": spec.label,
            "api_key_env": spec.api_key_env,
            "default_model": spec.default_model,
            "models": list(spec.models),
        }
        for spec in PROVIDER_SPECS.values()
        if spec.ui_enabled
    ]


def create_openai_compatible_client(
    provider: LLMProvider,
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
):
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("pip install openai") from e
    api_key = os.environ.get(provider.api_key_env, "").strip()
    if not api_key and provider.api_key_required:
        raise RuntimeError(f"{provider.api_key_env} is required for {provider.label} modes")
    kwargs: dict[str, object] = {"api_key": api_key or "local-deepseek"}
    if provider.base_url:
        kwargs["base_url"] = provider.base_url
    if timeout is not None:
        kwargs["timeout"] = float(timeout)
    if max_retries is not None:
        kwargs["max_retries"] = max(0, int(max_retries))
    return OpenAI(**kwargs)
