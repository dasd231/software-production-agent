from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from agent.workflow.schema import WorkflowTraceEvent


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def load_agent_events(path: str | Path) -> list[dict[str, Any]]:
    event_path = Path(path)
    if not event_path.exists():
        raise FileNotFoundError(f"agent events file not found: {event_path}")
    rows: list[dict[str, Any]] = []
    with event_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _event_time(row: dict[str, Any]) -> float:
    return max(0.0, _safe_float(row.get("ts"), 0.0))


def _run_id(row: dict[str, Any]) -> str:
    return str(row.get("run_id") or "agent-events")


def _iteration(row: dict[str, Any], fallback: int) -> int:
    return max(0, _safe_int(row.get("iteration"), fallback))


def _score_from_reward(reward: dict[str, Any]) -> float:
    total = _safe_float(reward.get("total"), 0.0)
    # Existing reward is roughly unbounded but small. Map [-2, 2] to [0, 1].
    return max(0.0, min(1.0, (total + 2.0) / 4.0))


def _event_from_decision_policy(row: dict[str, Any], fallback_step: int) -> WorkflowTraceEvent | None:
    decision = _as_dict(row.get("decision"))
    if not decision:
        return None
    ts = _event_time(row)
    selected = str(decision.get("selected_action") or "unknown")
    strategy = str(decision.get("strategy") or "unknown")
    score = _safe_float(decision.get("selected_score"), 0.5)
    confidence = _safe_float(decision.get("selected_bandit_score"), score)
    return WorkflowTraceEvent(
        run_id=_run_id(row),
        step_index=_iteration(row, fallback_step),
        node="choose_action",
        status="ok",
        started_at=ts,
        ended_at=ts,
        latency_ms=0.0,
        route_key="decision_strategy",
        route_choice=strategy,
        score=max(0.0, min(score, 1.0)),
        confidence=max(0.0, min(confidence, 1.0)),
        cost=0.02,
        metadata={
            "source_kind": "decision_policy",
            "selected_action": selected,
            "candidate_count": len(_as_list(decision.get("candidate_actions"))),
            "reason": str(decision.get("reason", ""))[:240],
        },
    )


def _event_from_decision_trace(row: dict[str, Any], fallback_step: int) -> WorkflowTraceEvent | None:
    trace = _as_dict(row.get("trace"))
    if not trace:
        return None
    ts = _event_time(row)
    selected = str(trace.get("selected_action") or trace.get("policy_selected_action") or "unknown")
    reward = _as_dict(trace.get("reward_after_execution"))
    score = _score_from_reward(reward) if reward else 0.5
    ok = bool(reward.get("ok", True)) if reward else True
    return WorkflowTraceEvent(
        run_id=_run_id(row),
        step_index=_iteration(row, fallback_step),
        node="decision_feedback",
        status="ok" if ok else "error",
        started_at=ts,
        ended_at=ts,
        latency_ms=0.0,
        route_key="decision_action",
        route_choice=selected,
        score=score,
        confidence=score,
        cost=0.02,
        error=None if ok else "reward_signal_not_ok",
        metadata={
            "source_kind": "decision_trace",
            "strategy": str(trace.get("strategy", "")),
            "aligned_with_policy": bool(trace.get("aligned_with_policy", False)),
            "policy_selected_action": str(trace.get("policy_selected_action", "")),
        },
    )


def _event_from_execute(row: dict[str, Any], fallback_step: int) -> WorkflowTraceEvent | None:
    summary = _as_dict(row.get("result_summary"))
    if not summary:
        return None
    ts = _event_time(row)
    action = str(summary.get("action") or "unknown")
    ok = bool(summary.get("ok", False))
    duration_ms = _safe_float(summary.get("duration_ms"), 0.0)
    score = 0.82 if ok else 0.18
    kind = str(row.get("kind", "execute"))
    return WorkflowTraceEvent(
        run_id=_run_id(row),
        step_index=_iteration(row, fallback_step),
        node="execute_action" if kind == "execute" else "execute_repair",
        status="ok" if ok else "error",
        started_at=ts,
        ended_at=ts + (duration_ms / 1000.0 if duration_ms else 0.0),
        latency_ms=duration_ms,
        route_key="execution_action",
        route_choice=action,
        score=score,
        confidence=score,
        cost=min(duration_ms / 10_000.0, 0.3) if duration_ms else 0.05,
        error=None if ok else str(summary.get("stderr_head") or summary.get("error_code") or "execute_failed")[:240],
        metadata={"source_kind": kind, "returncode": summary.get("returncode")},
    )


def _event_from_reward(row: dict[str, Any], fallback_step: int) -> WorkflowTraceEvent | None:
    reward = _as_dict(row.get("reward"))
    if not reward:
        return None
    ts = _event_time(row)
    ok = bool(reward.get("ok", False))
    total = _safe_float(reward.get("total"), 0.0)
    score = _score_from_reward(reward)
    return WorkflowTraceEvent(
        run_id=_run_id(row),
        step_index=_iteration(row, fallback_step),
        node="reward_update",
        status="ok" if ok else "error",
        started_at=ts,
        ended_at=ts,
        latency_ms=0.0,
        route_key="reward_quality",
        route_choice="positive" if total >= 0 else "negative",
        score=score,
        confidence=score,
        cost=0.01,
        error=None if ok else "negative_reward",
        metadata={"source_kind": "reward_signal", "total": total, "components": _as_dict(reward.get("components"))},
    )


def agent_events_to_workflow_traces(rows: Iterable[dict[str, Any]]) -> list[WorkflowTraceEvent]:
    """Convert .agent_events.jsonl rows into workflow optimizer traces.

    This bridge is what makes the LangGraph-like runtime a project capability rather
    than a separate demo: existing agent_loop telemetry becomes optimization data.
    """

    out: list[WorkflowTraceEvent] = []
    for index, row in enumerate(rows, start=1):
        kind = str(row.get("kind", ""))
        event: WorkflowTraceEvent | None = None
        if kind == "decision_policy":
            event = _event_from_decision_policy(row, index)
        elif kind == "decision_trace":
            event = _event_from_decision_trace(row, index)
        elif kind in {"execute", "execute_fix"}:
            event = _event_from_execute(row, index)
        elif kind == "reward_signal":
            event = _event_from_reward(row, index)
        if event is not None:
            out.append(event)
    return out


def load_workflow_traces_from_agent_events(path: str | Path) -> list[WorkflowTraceEvent]:
    return agent_events_to_workflow_traces(load_agent_events(path))
