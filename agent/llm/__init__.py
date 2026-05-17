"""LLM provider package.

函数流程图：
    UI / CLI / Planner
      -> providers.resolve_llm_provider()
      -> providers.create_openai_compatible_client()
      -> Brain / Planner chat.completions

你可以继续练算法/工程化的点：
    1. Provider routing：按任务类型、额度、速度和错误率动态选择 provider。
    2. 模型选择：用历史 reward/latency 训练模型选择策略。
    3. 降级策略：429/5xx 时自动切换备用 provider，但仍记录 decision trace。
"""

from __future__ import annotations

