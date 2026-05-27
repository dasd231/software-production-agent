from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.operations import (
    InMemoryAgentTaskQueue,
    build_multi_agent_failover_decision,
    build_operations_readiness_plan,
    evaluate_health_checks,
    redact_log_payload,
)


def test_health_checks_distinguish_healthy_degraded_and_unhealthy() -> None:
    healthy = evaluate_health_checks([{"name": "process", "ok": True, "critical": True, "latency_ms": 5, "timeout_ms": 50}])
    degraded = evaluate_health_checks(
        [
            {"name": "process", "ok": True, "critical": True, "latency_ms": 5, "timeout_ms": 50},
            {"name": "graph_memory", "ok": False, "critical": False, "latency_ms": 10, "timeout_ms": 100},
        ]
    )
    unhealthy = evaluate_health_checks(
        [
            {"name": "process", "ok": False, "critical": True, "latency_ms": 0, "timeout_ms": 50},
        ]
    )

    assert healthy["status"] == "healthy"
    assert degraded["status"] == "degraded"
    assert degraded["ready"] is True
    assert unhealthy["status"] == "unhealthy"
    assert unhealthy["ready"] is False


def test_redact_log_payload_removes_nested_secrets() -> None:
    payload = {
        "user": "alice",
        "password": "secret",
        "headers": {"Authorization": "Bearer token"},
        "items": [{"api_key": "k"}],
    }

    redacted = redact_log_payload(payload)

    assert redacted["user"] == "alice"
    assert redacted["password"] == "***REDACTED***"
    assert redacted["headers"]["Authorization"] == "***REDACTED***"
    assert redacted["items"][0]["api_key"] == "***REDACTED***"


def test_multi_agent_failover_reassigns_stale_agent_tasks_and_suppresses_duplicates() -> None:
    agents = [
        {"agent_id": "a1", "role": "coder", "status": "healthy", "last_seen_seconds": 5, "load": 0.2},
        {"agent_id": "a2", "role": "coder", "status": "healthy", "last_seen_seconds": 60, "load": 0.1},
        {"agent_id": "v1", "role": "verifier", "status": "unhealthy", "last_seen_seconds": 3, "load": 0.1},
    ]
    tasks = [
        {"task_id": "t1", "required_role": "coder", "assigned_agent_id": "a2", "idempotency_key": "k1"},
        {"task_id": "t2", "required_role": "coder", "assigned_agent_id": "a2", "idempotency_key": "k1"},
        {"task_id": "t3", "required_role": "verifier", "assigned_agent_id": "v1", "idempotency_key": "k3"},
    ]

    decision = build_multi_agent_failover_decision(agents, tasks, stale_after_seconds=30)

    assert decision["summary"]["unavailable_count"] == 2
    assert any(item["task_id"] == "t1" and item["to_agent"] == "a1" for item in decision["reassignments"])
    assert decision["duplicate_tasks"][0]["decision"] == "suppress_duplicate"
    # No verifier is healthy, so verifier work falls back to any healthy agent only when role-specific pool is absent.
    assert decision["summary"]["reassignment_count"] >= 2


def test_operations_readiness_plan_contains_monitoring_logs_health_and_multi_agent() -> None:
    plan = build_operations_readiness_plan(replicas=4)

    assert plan["schema"] == "operations_readiness_plan.v1"
    assert plan["health"]["contract"]["endpoints"]
    assert plan["logging"]["required_fields"]
    assert "agent_action_total{action,status,error_code}" in plan["monitoring"]["agent_specific_metrics"]
    assert plan["multi_agent"]["resilience_plan"]["roles"]
    assert plan["multi_agent"]["task_queue_backend"]["state_machine"] == ["queued", "leased", "completed", "dead_letter"]
    assert any(rule["name"] == "DeadLetterGrowing" for rule in plan["dashboards_and_alerts"]["alert_rules"])
    assert plan["multi_agent"]["failover_decision"]["summary"]["agent_count"] == 4
    assert any("health_snapshot" in gate for gate in plan["release_gates"])


def test_agent_task_queue_supports_lease_visibility_idempotency_and_dlq() -> None:
    now = [100.0]
    queue = InMemoryAgentTaskQueue(clock=lambda: now[0], visibility_timeout_s=5)
    queue.heartbeat("coder-1", role="coder", load=0.2)

    first = queue.submit(
        run_id="r1",
        required_role="coder",
        payload={"step": "implement"},
        idempotency_key="r1:coder:implement",
        max_attempts=2,
    )
    replay = queue.submit(
        run_id="r1",
        required_role="coder",
        payload={"step": "implement-again"},
        idempotency_key="r1:coder:implement",
    )
    acquired = queue.acquire(agent_id="coder-1", role="coder", lease_ttl_s=5)

    assert first["reason"] == "queued"
    assert replay["reason"] == "idempotent_replay"
    assert acquired["acquired"] is True
    lease_id = acquired["task"]["lease_id"]

    now[0] += 6
    reaped = queue.reap_expired_leases()
    assert reaped["requeued"] == 1

    second = queue.acquire(agent_id="coder-1", role="coder", lease_ttl_s=5)
    failed = queue.fail(second["task"]["lease_id"], error="poison task", retry=True)
    snapshot = queue.snapshot()

    assert failed["reason"] == "dead_letter"
    assert snapshot["states"]["dead_letter"] == 1
    assert snapshot["dead_letter_count"] == 1


def test_operations_readiness_action_writes_file_and_respects_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"operations_readiness_plan","args":'
        '{"service_name":"agent-saas","replicas":3,"output_path":"plans/ops.json"}}'
    )
    direct = run_action(tmp_path, action)
    assert direct["ok"] is True
    assert direct["summary"]["health_status"] == "healthy"
    assert (tmp_path / "plans" / "ops.json").exists()

    denied = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "PERMISSION_DENIED"

    allowed = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"ops:plan", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"
