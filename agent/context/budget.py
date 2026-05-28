"""Token-budget aware context slicing and message assembly.

This module is the business-layer governor before a prompt reaches a model.
vLLM chunked prefill can optimize long prompts *after* they enter the inference
engine; this module decides which evidence, history, code, and tool schemas are
worth admitting into the prompt in the first place.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent.scheduler.routing import build_model_route_plan, estimate_tokens


SOURCE_PRIORITY: dict[str, int] = {
    "system": 100,
    "developer": 96,
    "safety": 94,
    "user_input": 92,
    "business_params": 88,
    "recent_history": 76,
    "code": 72,
    "rag": 68,
    "tools": 58,
    "old_history": 44,
    "upload": 42,
    "misc": 20,
}

SOURCE_BUDGET_WEIGHTS: dict[str, float] = {
    "system": 0.16,
    "developer": 0.10,
    "safety": 0.08,
    "user_input": 0.18,
    "business_params": 0.08,
    "recent_history": 0.14,
    "rag": 0.20,
    "code": 0.18,
    "tools": 0.08,
    "old_history": 0.06,
    "upload": 0.06,
    "misc": 0.03,
}

MUST_KEEP_SOURCES = frozenset(
    {"system", "developer", "safety", "user_input", "business_params"}
)
VALID_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})


@dataclass(slots=True)
class ContextSegment:
    """A typed unit of context before it is packed into model messages."""

    source: str
    text: str
    role: str = "user"
    name: str = ""
    score: float = 0.0
    must_keep: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    @property
    def priority(self) -> int:
        base = SOURCE_PRIORITY.get(self.source, SOURCE_PRIORITY["misc"])
        if self.must_keep or self.source in MUST_KEEP_SOURCES:
            base += 100
        return base

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["tokens"] = self.tokens
        out["priority"] = self.priority
        return out


def _normalise_segment(raw: ContextSegment | dict[str, Any] | Any) -> ContextSegment:
    if isinstance(raw, ContextSegment):
        return raw
    if not isinstance(raw, dict):
        return ContextSegment(source="misc", text=str(raw or ""))
    metadata = raw.get("metadata", {})
    return ContextSegment(
        source=str(raw.get("source", "misc") or "misc"),
        text=str(raw.get("text", "") or ""),
        role=str(raw.get("role", "user") or "user"),
        name=str(raw.get("name", "") or ""),
        score=float(raw.get("score", 0.0) or 0.0),
        must_keep=bool(raw.get("must_keep", False)),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def _truncate_by_tokens(text: str, budget: int) -> str:
    """Approximate token clipping while preserving both head and tail.

    The project currently keeps tokenization dependency-light, so this uses the
    shared estimator. The important property is not perfect token counting; it is
    deterministic budget behavior with explicit compression markers.
    """

    if budget <= 0 or not text:
        return ""
    current = estimate_tokens(text)
    if current <= budget:
        return text

    ratio = max(min(budget / max(current, 1), 1.0), 0.02)
    char_budget = max(80, int(len(text) * ratio))
    if char_budget >= len(text):
        return text

    head = int(char_budget * 0.72)
    tail = max(char_budget - head - 80, 0)
    omitted = max(current - budget, 1)
    suffix = text[-tail:] if tail else ""
    return (
        text[:head].rstrip()
        + f"\n\n[已按 token 预算压缩，约省略 {omitted} tokens]\n"
        + suffix.lstrip()
    )


def _summary_for_segments(segments: list[ContextSegment], budget: int) -> ContextSegment:
    if not segments:
        return ContextSegment(
            source="old_history",
            text="",
            role="system",
            name="rolling_summary",
        )

    lines: list[str] = []
    for seg in segments:
        head = seg.text.replace("\n", " ").strip()[:180]
        if head:
            lines.append(f"- [{seg.source}] {head}")

    text = "长期记忆摘要：\n" + "\n".join(lines[:24])
    return ContextSegment(
        source="old_history",
        role="system",
        name="rolling_summary",
        text=_truncate_by_tokens(text, max(budget, 80)),
        score=0.5,
        metadata={"compressed_from": len(segments)},
    )


def allocate_source_budgets(total_input_budget: int) -> dict[str, int]:
    """Distribute a total prompt budget across context sources."""

    budget = max(int(total_input_budget), 1)
    weight_sum = sum(SOURCE_BUDGET_WEIGHTS.values()) or 1.0
    return {
        source: max(64, int(budget * weight / weight_sum))
        for source, weight in SOURCE_BUDGET_WEIGHTS.items()
    }


def _route_max_context(route_plan: dict[str, Any], fallback: int) -> int:
    pool = route_plan.get("pool") if isinstance(route_plan.get("pool"), dict) else {}
    return int(pool.get("max_model_len") or fallback)


def _route_reserved_output(route_plan: dict[str, Any], fallback: int) -> int:
    estimate = route_plan.get("token_estimate")
    if isinstance(estimate, dict):
        return max(int(fallback), int(estimate.get("max_output_tokens", 0) or 0))
    return int(fallback)


def build_context_budget_plan(
    segments: list[ContextSegment | dict[str, Any] | Any],
    *,
    goal: str = "",
    model_max_context: int | None = None,
    max_output_tokens: int = 1024,
    safety_margin_tokens: int = 256,
    route_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pack source-aware context into model messages under a token budget.

    Flow:
    input segments -> token estimate -> budget check -> split by source ->
    priority clipping -> rolling-summary compression -> message assembly.
    """

    normalized = [_normalise_segment(seg) for seg in segments]
    if route_plan is None:
        joined = "\n".join(seg.text for seg in normalized)
        route_plan = build_model_route_plan(
            goal or joined[:500],
            prompt=joined,
            max_output_tokens=max_output_tokens,
        )

    max_context = int(model_max_context or _route_max_context(route_plan, 8192))
    output_reserved = _route_reserved_output(route_plan, max_output_tokens)
    input_budget = max(max_context - output_reserved - int(safety_margin_tokens), 1)
    source_budgets = allocate_source_budgets(input_budget)

    sorted_segments = sorted(
        normalized,
        key=lambda seg: (-seg.priority, -seg.score, seg.tokens),
    )
    selected: list[ContextSegment] = []
    dropped: list[ContextSegment] = []
    compressed: list[dict[str, Any]] = []
    used = 0
    used_by_source: dict[str, int] = {}

    for seg in sorted_segments:
        seg_tokens = seg.tokens
        source_budget = source_budgets.get(seg.source, source_budgets["misc"])
        source_used = used_by_source.get(seg.source, 0)
        remaining_total = max(input_budget - used, 0)
        remaining_source = max(source_budget - source_used, 0)
        allowed = (
            remaining_total
            if (seg.must_keep or seg.source in MUST_KEEP_SOURCES)
            else min(remaining_total, remaining_source)
        )

        if seg_tokens <= allowed:
            selected.append(seg)
            used += seg_tokens
            used_by_source[seg.source] = source_used + seg_tokens
            continue

        compressible = (
            seg.must_keep
            or seg.source in MUST_KEEP_SOURCES
            or seg.source in {"recent_history", "rag", "code", "tools"}
        )
        if not compressible:
            dropped.append(seg)
            continue

        clipped = _truncate_by_tokens(seg.text, allowed)
        if not clipped:
            dropped.append(seg)
            continue

        clipped_seg = ContextSegment(
            source=seg.source,
            role=seg.role,
            name=seg.name,
            text=clipped,
            score=seg.score,
            must_keep=seg.must_keep,
            metadata={**seg.metadata, "compressed_from_tokens": seg_tokens},
        )
        clipped_tokens = clipped_seg.tokens
        selected.append(clipped_seg)
        used += clipped_tokens
        used_by_source[seg.source] = source_used + clipped_tokens
        compressed.append(
            {
                "source": seg.source,
                "name": seg.name,
                "from": seg_tokens,
                "to": clipped_tokens,
            }
        )

    # Far history should not disappear entirely; compress it into a rolling
    # summary if there is still room.
    old_history = [seg for seg in dropped if seg.source == "old_history"]
    if old_history and used < input_budget:
        summary_budget = min(
            max(input_budget - used, 0),
            source_budgets.get("old_history", 256),
        )
        summary = _summary_for_segments(old_history, summary_budget)
        if summary.text:
            selected.append(summary)
            used += summary.tokens
            compressed.append(
                {
                    "source": "old_history",
                    "name": "rolling_summary",
                    "from": sum(seg.tokens for seg in old_history),
                    "to": summary.tokens,
                }
            )
            dropped = [seg for seg in dropped if seg.source != "old_history"]

    messages: list[dict[str, str]] = []
    for seg in selected:
        label = f"[{seg.source}:{seg.name}]" if seg.name else f"[{seg.source}]"
        role = seg.role if seg.role in VALID_MESSAGE_ROLES else "user"
        messages.append({"role": role, "content": f"{label}\n{seg.text}"})

    final_tokens = sum(estimate_tokens(msg["content"]) for msg in messages)
    still_over_budget = final_tokens > input_budget
    escalation: list[str] = []
    if still_over_budget:
        escalation.extend(
            [
                "task_split_or_map_reduce_required",
                "build_temporary_index_and_retrieve_relevant_slices",
            ]
        )
    elif dropped:
        escalation.append("some_low_priority_context_dropped")
    if route_plan.get("context_budget"):
        escalation.append(f"route_pool={route_plan.get('selected_pool')}")

    return {
        "schema": "context_budget_plan.v1",
        "model_max_context": max_context,
        "reserved": {
            "output_tokens": output_reserved,
            "safety_margin_tokens": int(safety_margin_tokens),
        },
        "input_budget": input_budget,
        "source_budgets": source_budgets,
        "used_tokens": final_tokens,
        "over_budget": still_over_budget,
        "messages": messages,
        "selected_segments": [seg.to_dict() for seg in selected],
        "dropped_segments": [seg.to_dict() for seg in dropped],
        "compressed_segments": compressed,
        "route_plan": {
            "selected_pool": route_plan.get("selected_pool"),
            "context_budget": route_plan.get("context_budget"),
            "token_estimate": route_plan.get("token_estimate"),
        },
        "escalation": escalation,
    }


__all__ = [
    "ContextSegment",
    "allocate_source_budgets",
    "build_context_budget_plan",
]
