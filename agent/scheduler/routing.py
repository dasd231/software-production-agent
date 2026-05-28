"""Model pool routing and admission planning.

The router is deliberately side-effect free: it estimates workload size,
selects a serving pool, and returns an admission plan. A later model gateway
can execute the plan against vLLM, SGLang, or an agent service.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import asdict, dataclass
from typing import Any


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_SPACE_RE = re.compile(r"\s+")

BUSINESS_TYPES = frozenset(
    {
        "short_api",
        "long_context_rag",
        "agent_tooling",
        "training_batch",
        "enterprise_planning",
    }
)


@dataclass(frozen=True)
class ModelPoolConfig:
    name: str
    runtime: str
    base_url_env: str
    default_base_url: str
    max_model_len: int
    max_prompt_tokens: int
    max_output_tokens: int
    max_num_seqs: int
    max_concurrency: int
    timeout_s: int
    priority_class: str
    preemption_policy: str
    features: tuple[str, ...]
    routing_rules: tuple[str, ...]
    serving_args: tuple[str, ...]

    def resolved_base_url(self) -> str:
        return os.environ.get(self.base_url_env, "").strip() or self.default_base_url

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["features"] = list(self.features)
        out["routing_rules"] = list(self.routing_rules)
        out["serving_args"] = list(self.serving_args)
        out["base_url"] = self.resolved_base_url()
        return out


DEFAULT_POOLS: dict[str, ModelPoolConfig] = {
    "short_pool": ModelPoolConfig(
        name="short_pool",
        runtime="vllm",
        base_url_env="MODEL_SHORT_BASE_URL",
        default_base_url="http://model-vllm-short:8000/v1",
        max_model_len=16_384,
        max_prompt_tokens=12_000,
        max_output_tokens=1_024,
        max_num_seqs=256,
        max_concurrency=128,
        timeout_s=30,
        priority_class="latency",
        preemption_policy="best_effort_retryable",
        features=("multi_replica", "low_timeout", "hot_prompt_prefix_cache"),
        routing_rules=("prompt<=12k", "output<=1k", "stateless_api_or_small_code_task"),
        serving_args=(
            "--max-model-len=16384",
            "--max-num-seqs=256",
            "--gpu-memory-utilization=0.88",
        ),
    ),
    "long_pool": ModelPoolConfig(
        name="long_pool",
        runtime="vllm_or_sglang",
        base_url_env="MODEL_LONG_BASE_URL",
        default_base_url="http://model-vllm-long:8000/v1",
        max_model_len=65_536,
        max_prompt_tokens=60_000,
        max_output_tokens=4_096,
        max_num_seqs=16,
        max_concurrency=8,
        timeout_s=180,
        priority_class="protected_context",
        preemption_policy="non_preemptible_isolated_queue",
        features=("chunked_prefill", "prefix_caching", "strict_concurrency", "separate_queue"),
        routing_rules=("prompt>12k", "32k_or_64k_context", "rag_or_large_design_doc"),
        serving_args=(
            "--max-model-len=65536",
            "--max-num-seqs=16",
            "--enable-prefix-caching",
            "--enable-chunked-prefill",
        ),
    ),
    "agent_pool": ModelPoolConfig(
        name="agent_pool",
        runtime="sglang_or_agent_service",
        base_url_env="MODEL_AGENT_BASE_URL",
        default_base_url="http://model-agent:8000/v1",
        max_model_len=32_768,
        max_prompt_tokens=24_000,
        max_output_tokens=2_048,
        max_num_seqs=64,
        max_concurrency=32,
        timeout_s=90,
        priority_class="stateful_agent",
        preemption_policy="non_preemptible_stateful_lease",
        features=("task_queue", "state_machine", "tool_call_limits", "structured_outputs", "token_budget"),
        routing_rules=("requires_json", "tool_calls", "workflow_state", "agent_orchestration"),
        serving_args=("--context-length=32768", "--max-running-requests=64"),
    ),
    "training_batch_pool": ModelPoolConfig(
        name="training_batch_pool",
        runtime="offline_batch",
        base_url_env="MODEL_BATCH_BASE_URL",
        default_base_url="http://model-batch:8000/v1",
        max_model_len=32_768,
        max_prompt_tokens=28_000,
        max_output_tokens=4_096,
        max_num_seqs=8,
        max_concurrency=4,
        timeout_s=600,
        priority_class="offline",
        preemption_policy="checkpointable_low_priority",
        features=("low_priority", "batch_queue", "checkpointable", "no_online_preemption"),
        routing_rules=("dataset_generation", "evaluation_batch", "fine_tuning_preparation"),
        serving_args=("--batch-scheduler=max_utilization", "--checkpoint-interval=300"),
    ),
}

DEFAULT_OUTPUT_TOKENS: dict[str, int] = {
    "short_api": 768,
    "long_context_rag": 2_048,
    "agent_tooling": 1_200,
    "training_batch": 4_096,
    "enterprise_planning": 2_048,
}

DEFAULT_SYSTEM_RESERVED_TOKENS = 768


def estimate_tokens(text: str) -> int:
    """Estimate tokens without a tokenizer dependency.

    It intentionally overestimates mixed code/English a little and treats CJK
    text as roughly one token per non-space character. This is stable enough
    for admission control; exact billing can still be delegated to the runtime.
    """

    text = str(text or "")
    if not text.strip():
        return 0
    cjk_count = len(_CJK_RE.findall(text))
    words = _WORD_RE.findall(text)
    word_chars = sum(len(word) for word in words)
    word_tokens = sum(max(1, math.ceil(len(word) / 4)) for word in words)
    non_space_chars = len(_SPACE_RE.sub("", text))
    residual_chars = max(non_space_chars - cjk_count - word_chars, 0)
    residual_tokens = math.ceil(residual_chars / 2)
    return max(1, int(cjk_count + word_tokens + residual_tokens))


def _normalise_business_type(value: str) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "short": "short_api",
        "api": "short_api",
        "short_pool": "short_api",
        "long": "long_context_rag",
        "rag": "long_context_rag",
        "long_pool": "long_context_rag",
        "agent": "agent_tooling",
        "agent_pool": "agent_tooling",
        "tool": "agent_tooling",
        "training": "training_batch",
        "train": "training_batch",
        "batch": "training_batch",
        "training_batch_pool": "training_batch",
        "enterprise": "enterprise_planning",
        "architecture": "enterprise_planning",
        "planning": "enterprise_planning",
    }
    return aliases.get(key, key)


def classify_business_type(goal: str, prompt: str = "", *, require_json: bool = False) -> dict[str, Any]:
    text = f"{goal}\n{prompt}".lower()
    signals: list[str] = []

    def hit(label: str, keywords: tuple[str, ...]) -> bool:
        matched = [kw for kw in keywords if kw.lower() in text]
        if matched:
            signals.append(f"{label}:{','.join(matched[:5])}")
            return True
        return False

    is_training = hit(
        "training",
        ("训练", "微调", "sft", "lora", "qlora", "dataset", "数据集", "样本", "checkpoint"),
    )
    is_agent = require_json or hit(
        "agent",
        ("agent", "多agent", "工具调用", "tool", "function call", "状态机", "workflow", "分链", "主链"),
    )
    is_long = hit(
        "long_context",
        ("长上下文", "32k", "64k", "rag", "知识库", "方案库", "文档", "上下文", "chunk", "prefix"),
    )
    is_enterprise = hit(
        "enterprise",
        ("企业", "上市", "工业", "架构", "灰度", "承载", "vllm", "sglang", "k8s", "高并发", "池", "抢占"),
    )

    if is_training:
        business_type = "training_batch"
        confidence = 0.86
    elif is_agent:
        business_type = "agent_tooling"
        confidence = 0.82 if require_json else 0.76
        if require_json:
            signals.append("agent:requires_json")
    elif is_long:
        business_type = "long_context_rag"
        confidence = 0.74
    elif is_enterprise:
        business_type = "enterprise_planning"
        confidence = 0.70
    else:
        business_type = "short_api"
        confidence = 0.58
        signals.append("default:short_api")

    return {
        "type": business_type,
        "source": "heuristic",
        "confidence": confidence,
        "signals": signals,
    }


def _pool_for_business_type(business_type: str, *, require_json: bool) -> str:
    if business_type == "training_batch":
        return "training_batch_pool"
    if require_json or business_type == "agent_tooling":
        return "agent_pool"
    if business_type in {"long_context_rag", "enterprise_planning"}:
        return "long_pool"
    return "short_pool"


def _fits(pool: ModelPoolConfig, prompt_tokens: int, output_tokens: int) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    total = prompt_tokens + output_tokens
    if prompt_tokens > pool.max_prompt_tokens:
        reasons.append(f"prompt_tokens>{pool.max_prompt_tokens}")
    if output_tokens > pool.max_output_tokens:
        reasons.append(f"max_output_tokens>{pool.max_output_tokens}")
    if total > pool.max_model_len:
        reasons.append(f"total_tokens>{pool.max_model_len}")
    return not reasons, reasons


def _pool_brief(pool: ModelPoolConfig, prompt_tokens: int, output_tokens: int) -> dict[str, Any]:
    fits, reasons = _fits(pool, prompt_tokens, output_tokens)
    return {
        "name": pool.name,
        "runtime": pool.runtime,
        "base_url": pool.resolved_base_url(),
        "priority_class": pool.priority_class,
        "fits": fits,
        "reject_reasons": reasons,
        "max_model_len": pool.max_model_len,
        "max_num_seqs": pool.max_num_seqs,
        "max_concurrency": pool.max_concurrency,
        "timeout_s": pool.timeout_s,
        "features": list(pool.features),
    }


def _remediation(reasons: list[str], selected_pool: str) -> list[str]:
    out: list[str] = []
    if any(reason.startswith("prompt_tokens>") for reason in reasons):
        out.append("summarize_or_chunk_context_before_model_call")
        out.append("retrieve_top_k_evidence_instead_of_full_documents")
    if any(reason.startswith("max_output_tokens>") for reason in reasons):
        out.append("reduce_max_output_tokens_or_split_answer_into_sections")
    if any(reason.startswith("total_tokens>") for reason in reasons):
        out.append("split_task_into_workflow_nodes_with_intermediate_artifacts")
    if selected_pool in {"long_pool", "agent_pool"}:
        out.append("keep_request_on_isolated_queue_to_avoid_short_pool_preemption")
    if not out:
        out.append("admit_request_with_pool_limits")
    return out


def _queue_policy(pool: ModelPoolConfig) -> dict[str, Any]:
    return {
        "queue_key": f"model:{pool.name}:{pool.priority_class}",
        "max_concurrency": pool.max_concurrency,
        "max_num_seqs": pool.max_num_seqs,
        "timeout_s": pool.timeout_s,
        "preemption_policy": pool.preemption_policy,
        "preemptible": pool.preemption_policy.startswith("best_effort"),
        "lease_required": pool.name in {"long_pool", "agent_pool", "training_batch_pool"},
        "isolation": {
            "dedicated_endpoint": pool.name != "short_pool",
            "dedicated_queue": pool.name != "short_pool",
            "reason": "protect_kv_cache_prefill_and_agent_state" if pool.name != "short_pool" else "latency_pool_is_retryable",
        },
    }


def _context_budget(
    pool: ModelPoolConfig,
    *,
    prompt_tokens: int,
    output_tokens: int,
    business_type: str,
) -> dict[str, Any]:
    """Compute the token budget exposed to context slicing / RAG.

    The model route plan is the earliest place that knows the selected pool's
    prompt window, output reservation and concurrency class.  By returning a
    budget here, retrieval and PV slice routing can avoid loading 64k worth of
    evidence into a 12k short-pool request.
    """

    system_reserved = min(DEFAULT_SYSTEM_RESERVED_TOKENS, max(pool.max_model_len // 16, 128))
    prompt_window_after_output = max(pool.max_model_len - output_tokens - system_reserved, 0)
    effective_prompt_budget = min(pool.max_prompt_tokens, prompt_window_after_output)
    available_context_tokens = max(effective_prompt_budget - prompt_tokens, 0)
    target_slice_tokens = 2_048 if pool.name in {"long_pool", "training_batch_pool"} else 1_024
    if pool.name == "short_pool":
        target_slice_tokens = 768
    recommended_top_k = max(1, min(12, available_context_tokens // max(target_slice_tokens, 1)))
    pressure = (prompt_tokens + output_tokens + system_reserved) / max(pool.max_model_len, 1)
    if available_context_tokens <= 0:
        strategy = "summarize_before_retrieval"
    elif business_type in {"long_context_rag", "enterprise_planning", "training_batch"}:
        strategy = "semantic_pv_slice_budget"
    elif pressure > 0.72:
        strategy = "aggressive_rerank_then_slice"
    else:
        strategy = "direct_topk_context"
    return {
        "schema": "token_context_budget.v1",
        "pool": pool.name,
        "system_reserved_tokens": system_reserved,
        "effective_prompt_budget": effective_prompt_budget,
        "available_context_tokens": available_context_tokens,
        "target_slice_tokens": target_slice_tokens,
        "recommended_route_top_k": recommended_top_k,
        "context_pressure": round(pressure, 4),
        "strategy": strategy,
        "slice_policy": {
            "must_respect_budget": True,
            "drop_low_score_slices_first": True,
            "preserve_critical_slice_when_possible": True,
            "overflow_action": "summarize_or_second_pass",
        },
    }


def _output_tokens_for(business_type: str, max_output_tokens: int | None) -> int:
    if max_output_tokens is not None:
        return max(int(max_output_tokens), 1)
    return DEFAULT_OUTPUT_TOKENS.get(business_type, DEFAULT_OUTPUT_TOKENS["short_api"])


def list_model_pools() -> dict[str, Any]:
    return {
        "schema": "model_pool_catalog.v1",
        "pools": [DEFAULT_POOLS[name].to_dict() for name in sorted(DEFAULT_POOLS)],
        "routing_order": ["training_batch_pool", "agent_pool", "long_pool", "short_pool"],
    }


def build_model_route_plan(
    goal: str,
    prompt: str = "",
    *,
    max_output_tokens: int | None = None,
    business_type: str = "",
    require_json: bool = False,
) -> dict[str, Any]:
    goal = str(goal or "")
    prompt = str(prompt or "")
    prompt_tokens = estimate_tokens(f"{goal}\n{prompt}")

    normalised = _normalise_business_type(business_type)
    if normalised in BUSINESS_TYPES:
        classification = {
            "type": normalised,
            "source": "explicit",
            "confidence": 1.0,
            "signals": [f"explicit:{normalised}"],
        }
    else:
        classification = classify_business_type(goal, prompt, require_json=require_json)
        if business_type:
            classification["signals"] = [
                f"ignored_unknown_explicit_type:{business_type}",
                *classification.get("signals", []),
            ]

    biz_type = str(classification["type"])
    output_tokens = _output_tokens_for(biz_type, max_output_tokens)
    selected_name = _pool_for_business_type(biz_type, require_json=require_json)

    short_pool = DEFAULT_POOLS["short_pool"]
    if selected_name == "short_pool":
        short_fits, _ = _fits(short_pool, prompt_tokens, output_tokens)
        if not short_fits:
            selected_name = "long_pool"

    selected = DEFAULT_POOLS[selected_name]
    admitted, reasons = _fits(selected, prompt_tokens, output_tokens)
    status = "admitted" if admitted else "blocked"
    usage_ratio = (prompt_tokens + output_tokens) / max(selected.max_model_len, 1)

    return {
        "schema": "model_route_plan.v1",
        "business_type": classification,
        "token_estimate": {
            "prompt_tokens": prompt_tokens,
            "max_output_tokens": output_tokens,
            "total_tokens": prompt_tokens + output_tokens,
            "estimator": "heuristic_cjk_word_v1",
        },
        "selected_pool": selected_name,
        "pool": selected.to_dict(),
        "queue_policy": _queue_policy(selected),
        "context_budget": _context_budget(
            selected,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            business_type=biz_type,
        ),
        "token_accounting": {
            "estimate": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens_reserved": output_tokens,
                "total_reserved_tokens": prompt_tokens + output_tokens,
            },
            "actual_usage": None,
            "reconcile_policy": "record runtime usage by lease_id; fall back to estimate when provider does not return usage",
        },
        "admission": {
            "status": status,
            "admitted": admitted,
            "reject_reasons": reasons,
            "context_usage_ratio": round(usage_ratio, 4),
            "remediation": _remediation(reasons, selected_name),
        },
        "alternatives": [
            _pool_brief(DEFAULT_POOLS[name], prompt_tokens, output_tokens)
            for name in sorted(DEFAULT_POOLS)
            if name != selected_name
        ],
        "routing_trace": {
            "rule": "training>agent_json>long_context_or_enterprise>short_api_then_size_overflow",
            "require_json": bool(require_json),
            "explicit_business_type": business_type,
        },
    }
