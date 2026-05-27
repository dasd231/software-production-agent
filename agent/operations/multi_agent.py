from __future__ import annotations

from typing import Any


def build_multi_agent_failover_decision(
    agents: list[dict[str, Any]],
    tasks: list[dict[str, Any]],
    *,
    stale_after_seconds: int = 30,
    max_load: float = 0.85,
) -> dict[str, Any]:
    normalized_agents: list[dict[str, Any]] = []
    healthy_agents: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []

    for raw in agents:
        agent_id = str(raw.get("agent_id") or raw.get("id") or "unknown")
        role = str(raw.get("role") or "worker")
        status = str(raw.get("status") or "unknown")
        last_seen = _safe_float(raw.get("last_seen_seconds"), 999999.0)
        load = _safe_float(raw.get("load"), 0.0)
        healthy = status == "healthy" and last_seen <= stale_after_seconds and load <= max_load
        item = {
            "agent_id": agent_id,
            "role": role,
            "status": status,
            "last_seen_seconds": last_seen,
            "load": load,
            "healthy": healthy,
        }
        normalized_agents.append(item)
        if healthy:
            healthy_agents.append(item)
        else:
            reason = []
            if status != "healthy":
                reason.append(f"status={status}")
            if last_seen > stale_after_seconds:
                reason.append("heartbeat_stale")
            if load > max_load:
                reason.append("overloaded")
            unavailable.append({**item, "reason": reason or ["unavailable"]})

    healthy_by_role: dict[str, list[dict[str, Any]]] = {}
    for agent in healthy_agents:
        healthy_by_role.setdefault(agent["role"], []).append(agent)
    for role_agents in healthy_by_role.values():
        role_agents.sort(key=lambda item: (float(item["load"]), str(item["agent_id"])))

    reassignments: list[dict[str, Any]] = []
    dead_letter: list[dict[str, Any]] = []
    unavailable_ids = {agent["agent_id"] for agent in unavailable}
    seen_idempotency: set[str] = set()
    duplicate_tasks: list[dict[str, Any]] = []

    for task in tasks:
        task_id = str(task.get("task_id") or task.get("id") or "unknown")
        required_role = str(task.get("required_role") or task.get("role") or "worker")
        assigned = str(task.get("assigned_agent_id") or "")
        key = str(task.get("idempotency_key") or task_id)
        if key in seen_idempotency:
            duplicate_tasks.append({"task_id": task_id, "idempotency_key": key, "decision": "suppress_duplicate"})
            continue
        seen_idempotency.add(key)
        needs_reassign = assigned in unavailable_ids or not assigned
        if not needs_reassign:
            continue
        candidates = healthy_by_role.get(required_role) or healthy_agents
        if candidates:
            target = candidates[0]
            reassignments.append(
                {
                    "task_id": task_id,
                    "from_agent": assigned,
                    "to_agent": target["agent_id"],
                    "required_role": required_role,
                    "idempotency_key": key,
                    "decision": "reassign_with_idempotency_guard",
                }
            )
            target["load"] = min(1.0, float(target["load"]) + 0.05)
            healthy_by_role.get(target["role"], healthy_agents).sort(key=lambda item: (float(item["load"]), str(item["agent_id"])))
        else:
            dead_letter.append(
                {
                    "task_id": task_id,
                    "assigned_agent_id": assigned,
                    "required_role": required_role,
                    "idempotency_key": key,
                    "reason": "no_healthy_agent_for_role",
                }
            )

    status = "healthy"
    if dead_letter:
        status = "degraded"
    if not healthy_agents and tasks:
        status = "unavailable"

    return {
        "schema": "multi_agent_failover_decision.v1",
        "status": status,
        "stale_after_seconds": stale_after_seconds,
        "max_load": max_load,
        "agents": normalized_agents,
        "healthy_agents": healthy_agents,
        "unavailable_agents": unavailable,
        "reassignments": reassignments,
        "dead_letter": dead_letter,
        "duplicate_tasks": duplicate_tasks,
        "summary": {
            "agent_count": len(normalized_agents),
            "healthy_count": len(healthy_agents),
            "unavailable_count": len(unavailable),
            "task_count": len(tasks),
            "reassignment_count": len(reassignments),
            "dead_letter_count": len(dead_letter),
            "duplicate_suppressed": len(duplicate_tasks),
        },
    }


def build_multi_agent_resilience_plan(*, replicas: int = 3) -> dict[str, Any]:
    return {
        "schema": "multi_agent_resilience_plan.v1",
        "replicas": max(1, int(replicas)),
        "roles": [
            {"role": "orchestrator", "responsibility": "task graph ownership, policy version, global admission"},
            {"role": "planner", "responsibility": "decompose user goals into graph/subtasks"},
            {"role": "researcher", "responsibility": "RAG/Web/GitHub evidence gathering"},
            {"role": "coder", "responsibility": "bounded code changes"},
            {"role": "verifier", "responsibility": "tests, scorecard, evidence verification"},
            {"role": "sandbox_runner", "responsibility": "high-risk action execution in isolated K8s jobs"},
        ],
        "availability_patterns": [
            "heartbeat + lease per agent",
            "durable task queue with visibility timeout",
            "idempotency key on every task and side effect",
            "work stealing from stale leases",
            "dead letter queue for tasks with no healthy role owner",
            "bulkhead isolation by role and tenant",
            "circuit breaker around model providers/tools",
            "backpressure through global admission controller",
            "checkpoint/resume for graph state",
        ],
        "failure_modes": [
            {"mode": "agent_crash", "detection": "heartbeat stale", "recovery": "lease expires; task reassigned"},
            {"mode": "model_provider_timeout", "detection": "timeout/error budget burn", "recovery": "fallback provider or smaller model"},
            {"mode": "tool_hallucination", "detection": "protocol/supervisor denial", "recovery": "route to verifier/human gate"},
            {"mode": "duplicate_execution", "detection": "idempotency key conflict", "recovery": "suppress duplicate and return previous result"},
            {"mode": "split_brain_orchestrator", "detection": "lease fencing token mismatch", "recovery": "single-writer lease and epoch fencing"},
            {"mode": "queue_backlog", "detection": "oldest task age / depth", "recovery": "scale role replicas and shed low priority work"},
        ],
        "slo": {
            "agent_heartbeat_freshness_seconds": 30,
            "task_reassignment_seconds": 60,
            "dead_letter_rate": "< 1%",
            "duplicate_side_effect_rate": "0",
            "critical_path_availability": "99.5%",
        },
        "runbook": [
            "If heartbeat stale, do not kill immediately; fence lease and reassign visible tasks.",
            "If verifier unavailable, block release but allow research/coding to continue in queue.",
            "If model provider degraded, switch route policy to cheaper/faster fallback and lower concurrency.",
            "If sandbox runner unavailable, high-risk actions become human_required rather than local execution.",
        ],
    }


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default

