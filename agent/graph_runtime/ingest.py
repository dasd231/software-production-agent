from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from agent.graph_runtime.property_graph import PropertyGraph


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "ok", "success"}
    return bool(value)


def _stable_id(prefix: str, *parts: Any) -> str:
    raw = "\0".join(str(part) for part in parts)
    return f"{prefix}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def load_agent_events_jsonl(path: str | Path) -> list[dict[str, Any]]:
    event_path = Path(path)
    rows: list[dict[str, Any]] = []
    with event_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _run_id(row: dict[str, Any]) -> str:
    return str(row.get("run_id") or "agent-events")


def _event_id(row: dict[str, Any], index: int) -> str:
    return str(row.get("event_id") or _stable_id("event", _run_id(row), index, row.get("kind"), row.get("ts")))


def _add_run(graph: PropertyGraph, row: dict[str, Any]) -> str:
    run_id = _run_id(row)
    goal = str(row.get("goal") or row.get("task") or "")
    graph.add_node(
        f"run:{run_id}",
        ("AgentRun",),
        run_id=run_id,
        goal=goal,
        status=str(row.get("status") or ""),
        started_at=row.get("ts") if row.get("kind") == "loop_start" else "",
    )
    return f"run:{run_id}"


def _add_event(graph: PropertyGraph, row: dict[str, Any], index: int, run_node: str) -> str:
    kind = str(row.get("kind") or row.get("node") or "unknown")
    event_id = _event_id(row, index)
    event_node = f"event:{event_id}"
    graph.add_node(
        event_node,
        ("Event",),
        kind=kind,
        node=str(row.get("node") or kind),
        status=str(row.get("status") or ""),
        ts=_safe_float(row.get("ts"), 0.0),
        iteration=row.get("iteration", ""),
        schema_version=str(row.get("schema_version", "")),
    )
    graph.add_node(f"workflow_node:{kind}", ("WorkflowNode",), workflow_node_id=kind, role=_role_for_event_kind(kind))
    graph.add_edge(run_node, "HAS_EVENT", event_node, order=index)
    graph.add_edge(event_node, "AT_NODE", f"workflow_node:{kind}")
    return event_node


def _role_for_event_kind(kind: str) -> str:
    if kind in {"plan", "context_enriched", "loop_start"}:
        return "context"
    if kind in {"decision_policy", "decide", "decision_trace"}:
        return "decision"
    if kind in {"execute", "execute_fix", "fix"}:
        return "actuation"
    if kind in {"reward_signal", "finish", "stopped"}:
        return "evaluation"
    if kind in {"assess_similarity_collapse", "rewind_blind_fanout"}:
        return "diversity_control"
    return "runtime"


def _add_decision(graph: PropertyGraph, row: dict[str, Any], event_node: str, run_node: str) -> str | None:
    kind = str(row.get("kind") or "")
    if row.get("route_key") or row.get("route_choice"):
        decision = {
            "route_key": row.get("route_key"),
            "selected_action": row.get("route_choice"),
            "selected_score": row.get("score"),
            "selected_bandit_score": row.get("confidence"),
            "reason": _as_dict(row.get("metadata")).get("message", ""),
            "policy_family": "workflow_route",
        }
    else:
        decision = _as_dict(row.get("decision")) if kind == "decision_policy" else _as_dict(row.get("trace"))
    if not decision:
        return None
    selected_action = str(decision.get("selected_action") or decision.get("policy_selected_action") or "unknown")
    route_key = str(decision.get("strategy") or decision.get("route_key") or "decision")
    score = _safe_float(decision.get("selected_score"), _safe_float(decision.get("selected_bandit_score"), 0.0))
    decision_node = _stable_id("decision", run_node, event_node, route_key, selected_action)
    graph.add_node(
        decision_node,
        ("Decision",),
        route_key=route_key,
        choice=selected_action,
        confidence=_safe_float(decision.get("selected_bandit_score"), score),
        score=score,
        reason=str(decision.get("reason", ""))[:400],
    )
    policy_family = str(decision.get("policy_family") or "decision_policy")
    policy_node = "policy:workflow-route-current" if policy_family == "workflow_route" else "policy:agent-loop-current"
    graph.add_node(policy_node, ("PolicyVersion",), version=policy_node.removeprefix("policy:"), family=policy_family)
    graph.add_edge(run_node, "MADE", decision_node)
    graph.add_edge(event_node, "RECORDED", decision_node)
    graph.add_edge(decision_node, "USED_POLICY", policy_node)
    action_node = _add_action(graph, selected_action, ok="", duration_ms=0.0, error_code="")
    graph.add_edge(decision_node, "SELECTED", action_node)
    if route_key == "collapse_route":
        graph.add_edge(decision_node, "CONTROLS_DIVERSITY", run_node)
    return decision_node


def _find_similarity_assessment(row: dict[str, Any]) -> dict[str, Any]:
    candidates = [
        row.get("similarity_collapse_assessment"),
        row.get("assessment"),
        _as_dict(row.get("metadata")).get("similarity_collapse_assessment"),
        _as_dict(row.get("result_summary")).get("similarity_collapse_assessment"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and (
            candidate.get("schema") == "similarity_collapse_assessment.v1" or "metrics" in candidate or "alarm" in candidate
        ):
            return candidate
    return {}


def _add_similarity_collapse(graph: PropertyGraph, row: dict[str, Any], event_node: str, run_node: str) -> tuple[int, int]:
    route_key = str(row.get("route_key") or "")
    route_choice = str(row.get("route_choice") or "")
    assessment = _find_similarity_assessment(row)
    if not assessment and route_key != "collapse_route":
        return 0, 0
    metrics = _as_dict(assessment.get("metrics"))
    alarm = _safe_bool(assessment.get("alarm")) or route_choice == "rewind_blind_fanout"
    collapse_node = _stable_id("collapse", run_node, event_node, route_key, route_choice)
    graph.add_node(
        collapse_node,
        ("SimilarityCollapse", "QualityRisk"),
        alarm=alarm,
        severity=str(assessment.get("severity") or ("warning" if alarm else "none")),
        route_choice=route_choice,
        avg_pairwise_rationale_cosine=_safe_float(metrics.get("avg_pairwise_rationale_cosine"), 0.0),
        max_pairwise_rationale_cosine=_safe_float(metrics.get("max_pairwise_rationale_cosine"), 0.0),
        effective_rank=_safe_float(metrics.get("effective_rank"), 0.0),
        effective_rank_ratio=_safe_float(metrics.get("effective_rank_ratio"), 0.0),
        avg_evidence_jaccard=_safe_float(metrics.get("avg_evidence_jaccard"), 0.0),
    )
    graph.add_edge(event_node, "DETECTED", collapse_node)
    graph.add_edge(run_node, "HAS_QUALITY_RISK", collapse_node)
    if route_choice:
        route_node = f"workflow_node:{route_choice}"
        graph.add_node(route_node, ("WorkflowNode",), workflow_node_id=route_choice, role=_role_for_event_kind(route_choice))
        graph.add_edge(collapse_node, "ROUTED_TO", route_node)
    retention = row.get("diversity_retention_decision") or _as_dict(row.get("metadata")).get("diversity_retention_decision")
    rewind_count = 1 if route_choice == "rewind_blind_fanout" else 0
    if isinstance(retention, dict) and retention:
        retention_node = _stable_id("diversity_retention", run_node, event_node)
        graph.add_node(
            retention_node,
            ("DiversityRetention",),
            input_count=int(retention.get("input_count", 0) or 0),
            retained_count=int(retention.get("retained_count", 0) or 0),
            policy=str(retention.get("policy", "")),
        )
        graph.add_edge(collapse_node, "MITIGATED_BY", retention_node)
        rewind_count = max(rewind_count, 1)
    return (1 if alarm else 0), rewind_count


def _add_action(graph: PropertyGraph, action: str, *, ok: Any, duration_ms: float, error_code: str) -> str:
    action_key = str(action or "unknown")
    action_node = f"action:{action_key}"
    graph.add_node(
        action_node,
        ("Action",),
        action=action_key,
        ok=ok,
        duration_ms=duration_ms,
        error_code=error_code,
    )
    return action_node


def _add_action_event(graph: PropertyGraph, row: dict[str, Any], event_node: str, run_node: str) -> str | None:
    kind = str(row.get("kind") or "")
    action_summary = _as_dict(row.get("action_summary"))
    result_summary = _as_dict(row.get("result_summary"))
    if not action_summary and not result_summary:
        return None
    action = str(action_summary.get("action") or result_summary.get("action") or "unknown")
    ok = result_summary.get("ok", "") if result_summary else ""
    duration_ms = _safe_float(result_summary.get("duration_ms"), 0.0) if result_summary else 0.0
    error_code = str(result_summary.get("error_code") or result_summary.get("stderr_head") or "")
    action_node = _add_action(graph, action, ok=ok, duration_ms=duration_ms, error_code=error_code[:240])
    relation = "EXECUTED" if kind in {"execute", "execute_fix"} else "PLANNED_ACTION"
    graph.add_edge(event_node, relation, action_node)
    graph.add_edge(run_node, relation, action_node, event_kind=kind)
    if result_summary:
        artifact_path = str(result_summary.get("path") or result_summary.get("output_path") or "")
        if artifact_path:
            artifact_node = _stable_id("artifact", run_node, artifact_path)
            graph.add_node(artifact_node, ("Artifact",), path=artifact_path, kind="file")
            graph.add_edge(action_node, "PRODUCED", artifact_node)
        if "evaluation_score" in result_summary or "evaluation_grade" in result_summary:
            reward_node = _stable_id("reward", run_node, event_node, result_summary.get("evaluation_score"))
            graph.add_node(
                reward_node,
                ("Reward",),
                total=_safe_float(result_summary.get("evaluation_score"), 0.0),
                grade=str(result_summary.get("evaluation_grade", "")),
                source="result_summary",
            )
            graph.add_edge(action_node, "REWARDED_BY", reward_node)
    return action_node


def _add_reward(graph: PropertyGraph, row: dict[str, Any], event_node: str, run_node: str) -> str | None:
    reward = _as_dict(row.get("reward"))
    if not reward:
        return None
    reward_node = _stable_id("reward", run_node, event_node, reward.get("total"))
    graph.add_node(
        reward_node,
        ("Reward",),
        total=_safe_float(reward.get("total"), 0.0),
        ok=_safe_bool(reward.get("ok")),
        source=str(reward.get("source", "reward_signal")),
        components=json.dumps(_as_dict(reward.get("components")), ensure_ascii=False, sort_keys=True),
    )
    graph.add_edge(event_node, "RECORDED", reward_node)
    graph.add_edge(run_node, "REWARDED_BY", reward_node)
    return reward_node


def _add_evidence(graph: PropertyGraph, row: dict[str, Any], event_node: str, run_node: str) -> None:
    payloads = []
    for key in ("citations", "evidence", "source_paths"):
        value = row.get(key)
        if isinstance(value, list):
            payloads.extend(value)
    trace = _as_dict(row.get("trace"))
    for item in _as_list(trace.get("citations")):
        payloads.append(item)
    for idx, item in enumerate(payloads[:20]):
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("url") or item.get("source") or f"inline-{idx}")
            source = str(item.get("source") or item.get("type") or "event")
            confidence = _safe_float(item.get("confidence"), 0.0)
        else:
            path = str(item)
            source = "event"
            confidence = 0.0
        evidence_node = _stable_id("evidence", run_node, path, source)
        graph.add_node(evidence_node, ("Evidence",), path=path, source=source, confidence=confidence)
        graph.add_edge(event_node, "CITED", evidence_node)


def _add_human_review(graph: PropertyGraph, row: dict[str, Any], event_node: str, run_node: str) -> None:
    kind = str(row.get("kind") or "")
    if kind not in {"human_review", "human_gate", "interrupt"} and "human" not in json.dumps(row, ensure_ascii=False).lower():
        return
    review_node = _stable_id("human_review", run_node, event_node)
    graph.add_node(
        review_node,
        ("HumanReview",),
        level=str(row.get("level") or row.get("human_level") or "unknown"),
        decision=str(row.get("decision") or row.get("status") or kind),
        reason=str(row.get("reason") or row.get("interrupt_reason") or "")[:400],
    )
    graph.add_edge(event_node, "REQUIRES_REVIEW", review_node)
    graph.add_edge(review_node, "PATCHED_STATE", run_node)


def agent_events_to_property_graph(rows: Iterable[dict[str, Any]]) -> tuple[PropertyGraph, dict[str, Any]]:
    graph = PropertyGraph()
    previous_event_by_run: dict[str, str] = {}
    counts: dict[str, int] = {}
    run_ids: set[str] = set()
    failed_actions = 0
    human_reviews = 0
    collapse_alarms = 0
    diversity_rewinds = 0

    for index, row in enumerate(rows, start=1):
        kind = str(row.get("kind") or row.get("node") or "unknown")
        counts[kind] = counts.get(kind, 0) + 1
        run_node = _add_run(graph, row)
        run_ids.add(run_node)
        event_node = _add_event(graph, row, index, run_node)
        previous = previous_event_by_run.get(run_node)
        if previous:
            graph.add_edge(previous, "NEXT_EVENT", event_node)
        previous_event_by_run[run_node] = event_node

        _add_decision(graph, row, event_node, run_node)
        action_node = _add_action_event(graph, row, event_node, run_node)
        if action_node and any(edge.target == action_node and edge.type == "EXECUTED" for edge in graph.edges):
            result_summary = _as_dict(row.get("result_summary"))
            if result_summary and result_summary.get("ok") is False:
                failed_actions += 1
        _add_reward(graph, row, event_node, run_node)
        _add_evidence(graph, row, event_node, run_node)
        before_reviews = len(graph.nodes_by_label("HumanReview"))
        _add_human_review(graph, row, event_node, run_node)
        human_reviews += max(0, len(graph.nodes_by_label("HumanReview")) - before_reviews)
        alarms, rewinds = _add_similarity_collapse(graph, row, event_node, run_node)
        collapse_alarms += alarms
        diversity_rewinds += rewinds

    summary = {
        "schema": "agent_event_graph_ingest_summary.v1",
        "event_count": sum(counts.values()),
        "run_count": len(run_ids),
        "event_kinds": counts,
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "failed_actions": failed_actions,
        "human_reviews": human_reviews,
        "collapse_alarms": collapse_alarms,
        "diversity_rewinds": diversity_rewinds,
    }
    return graph, summary


def load_agent_events_graph(path: str | Path) -> tuple[PropertyGraph, dict[str, Any]]:
    return agent_events_to_property_graph(load_agent_events_jsonl(path))
