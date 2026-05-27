from __future__ import annotations

from typing import Any


def evaluate_health_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate component checks into app health/readiness.

    Status semantics:
    - healthy: all critical checks pass
    - degraded: non-critical checks fail, or critical checks are slow
    - unhealthy: any critical check fails/hard times out
    """

    normalized: list[dict[str, Any]] = []
    critical_failed = 0
    noncritical_failed = 0
    slow_critical = 0
    for raw in checks:
        name = str(raw.get("name", "unknown") or "unknown")
        critical = bool(raw.get("critical", True))
        ok = bool(raw.get("ok", False))
        latency_ms = _safe_float(raw.get("latency_ms"), 0.0)
        timeout_ms = _safe_float(raw.get("timeout_ms"), 1000.0)
        status = "ok" if ok else "failed"
        if ok and critical and timeout_ms > 0 and latency_ms > timeout_ms * 0.8:
            status = "slow"
            slow_critical += 1
        if not ok and critical:
            critical_failed += 1
        elif not ok:
            noncritical_failed += 1
        normalized.append(
            {
                "name": name,
                "ok": ok,
                "critical": critical,
                "latency_ms": latency_ms,
                "timeout_ms": timeout_ms,
                "status": status,
                "detail": str(raw.get("detail", "") or ""),
            }
        )

    if critical_failed:
        status = "unhealthy"
        ready = False
        live = False
    elif noncritical_failed or slow_critical:
        status = "degraded"
        ready = True
        live = True
    else:
        status = "healthy"
        ready = True
        live = True

    return {
        "schema": "app_health_snapshot.v1",
        "status": status,
        "live": live,
        "ready": ready,
        "startup_complete": not critical_failed,
        "summary": {
            "check_count": len(normalized),
            "critical_failed": critical_failed,
            "noncritical_failed": noncritical_failed,
            "slow_critical": slow_critical,
        },
        "checks": normalized,
    }


def build_health_contract() -> dict[str, Any]:
    return {
        "schema": "health_contract.v1",
        "endpoints": [
            {
                "path": "/healthz",
                "purpose": "liveness: process event loop is alive; avoid checking slow dependencies",
                "failure_action": "restart container",
            },
            {
                "path": "/readyz",
                "purpose": "readiness: can accept traffic; checks DB/cache/model-router essential dependencies",
                "failure_action": "remove from service endpoints without killing pod",
            },
            {
                "path": "/startupz",
                "purpose": "startup: model indexes, migrations and warm caches initialized",
                "failure_action": "delay liveness until startup completes",
            },
            {
                "path": "/metrics",
                "purpose": "Prometheus scrape endpoint",
                "failure_action": "alert observability gap; do not restart app immediately",
            },
        ],
        "component_checks": [
            {"name": "process", "critical": True, "timeout_ms": 50},
            {"name": "workspace_fs", "critical": True, "timeout_ms": 100},
            {"name": "event_log_writer", "critical": True, "timeout_ms": 100},
            {"name": "model_router", "critical": True, "timeout_ms": 500},
            {"name": "graph_memory", "critical": False, "timeout_ms": 500},
            {"name": "solution_library", "critical": False, "timeout_ms": 300},
            {"name": "k8s_sandbox_dispatcher", "critical": False, "timeout_ms": 800},
            {"name": "payment_reconcile_worker", "critical": False, "timeout_ms": 800},
        ],
        "aggregation_rule": "any failed critical check => unhealthy; failed non-critical check => degraded",
    }


def build_k8s_probe_patch() -> dict[str, Any]:
    return {
        "schema": "k8s_probe_patch.v1",
        "container_probe_defaults": {
            "startupProbe": {
                "httpGet": {"path": "/startupz", "port": 8000},
                "periodSeconds": 5,
                "failureThreshold": 24,
            },
            "livenessProbe": {
                "httpGet": {"path": "/healthz", "port": 8000},
                "periodSeconds": 10,
                "failureThreshold": 3,
                "timeoutSeconds": 2,
            },
            "readinessProbe": {
                "httpGet": {"path": "/readyz", "port": 8000},
                "periodSeconds": 5,
                "failureThreshold": 2,
                "timeoutSeconds": 2,
            },
        },
        "pdb": {
            "apiVersion": "policy/v1",
            "kind": "PodDisruptionBudget",
            "spec": {"minAvailable": 1, "selector": {"matchLabels": {"app.kubernetes.io/name": "software-production-agent"}}},
        },
    }


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default

