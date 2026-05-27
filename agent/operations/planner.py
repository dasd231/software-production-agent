from __future__ import annotations

from typing import Any

from agent.operations.health import build_health_contract, build_k8s_probe_patch, evaluate_health_checks
from agent.operations.logging_contract import build_logging_contract
from agent.operations.monitoring import build_monitoring_contract
from agent.operations.multi_agent import build_multi_agent_failover_decision, build_multi_agent_resilience_plan
from agent.operations.dashboards import build_grafana_alertmanager_bundle
from agent.operations.task_queue import build_task_queue_backend_plan


def build_operations_readiness_plan(
    *,
    service_name: str = "software-production-agent",
    replicas: int = 3,
    slo_target: float = 0.995,
    checks: list[dict[str, Any]] | None = None,
    agents: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    health_snapshot = evaluate_health_checks(
        checks
        if checks is not None
        else [
            {"name": "process", "ok": True, "critical": True, "latency_ms": 5, "timeout_ms": 50},
            {"name": "workspace_fs", "ok": True, "critical": True, "latency_ms": 12, "timeout_ms": 100},
            {"name": "model_router", "ok": True, "critical": True, "latency_ms": 80, "timeout_ms": 500},
            {"name": "graph_memory", "ok": True, "critical": False, "latency_ms": 30, "timeout_ms": 500},
        ]
    )
    failover_decision = build_multi_agent_failover_decision(
        agents if agents is not None else _default_agents(replicas),
        tasks if tasks is not None else [],
    )
    return {
        "schema": "operations_readiness_plan.v1",
        "service": service_name,
        "health": {
            "contract": build_health_contract(),
            "snapshot": health_snapshot,
            "k8s": build_k8s_probe_patch(),
        },
        "logging": build_logging_contract(),
        "monitoring": build_monitoring_contract(service_name=service_name, slo_target=slo_target),
        "multi_agent": {
            "resilience_plan": build_multi_agent_resilience_plan(replicas=replicas),
            "failover_decision": failover_decision,
            "task_queue_backend": build_task_queue_backend_plan(),
        },
        "dashboards_and_alerts": build_grafana_alertmanager_bundle(service_name=service_name),
        "release_gates": [
            "health_snapshot.status != unhealthy",
            "readiness endpoint returns ready before receiving traffic",
            "all public actions emit trace_id/run_id/action/status",
            "all secrets are redacted before log/graph persistence",
            "multi-agent dead_letter_count == 0 for release smoke tests",
            "task queue oldest_visible_age_s and dead_letter_count stay below SLO gates",
            "policy canary holds are reviewed before promotion",
        ],
        "implementation_order": [
            "1. add /healthz /readyz /startupz /metrics endpoints",
            "2. enforce structured JSON logging and redaction",
            "3. emit Prometheus metrics around executor, supervisor, graph runtime and task queue",
            "4. add multi-agent heartbeat/lease/task-queue tables",
            "5. connect alerts to runbooks and scorecard evidence",
        ],
    }


def _default_agents(replicas: int) -> list[dict[str, Any]]:
    count = max(1, int(replicas))
    roles = ["orchestrator", "planner", "researcher", "coder", "verifier", "sandbox_runner"]
    return [
        {
            "agent_id": f"agent-{idx:02d}",
            "role": roles[idx % len(roles)],
            "status": "healthy",
            "last_seen_seconds": 5,
            "load": 0.1 + (idx % 3) * 0.1,
        }
        for idx in range(count)
    ]
