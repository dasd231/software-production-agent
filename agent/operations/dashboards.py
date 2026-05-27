from __future__ import annotations

from typing import Any


def build_grafana_alertmanager_bundle(*, service_name: str = "software-production-agent") -> dict[str, Any]:
    dashboards = [
        {
            "title": "Agent Executive Overview",
            "panels": [
                "SLO availability and error budget",
                "agent run p95 latency",
                "action error rate by action",
                "human intervention level distribution",
                "release gates and policy canary holds",
            ],
        },
        {
            "title": "Multi-Agent Runtime Pool",
            "panels": [
                "heartbeat staleness by role",
                "task queue depth by role/priority",
                "lease expiry and reassignment rate",
                "dead letter growth",
                "idempotent replay count",
            ],
        },
        {
            "title": "Cloud Native Scheduling Pressure",
            "panels": [
                "CNI IP pressure by node",
                "CSI attach p95 latency by storage class",
                "PodOverhead CPU/memory pressure by RuntimeClass",
                "storage topology reject count",
                "DRA pending ResourceClaims",
            ],
        },
    ]
    alert_rules = [
        {
            "name": "HighErrorRate",
            "expr": "rate(agent_action_total{status='error'}[5m]) > 0.05",
            "for": "10m",
            "severity": "critical",
            "runbook": "Check recent deployment, action error_code distribution and supervisor denials.",
        },
        {
            "name": "HeartbeatStale",
            "expr": "agent_heartbeat_staleness_seconds > 30",
            "for": "2m",
            "severity": "critical",
            "runbook": "Fence stale lease, requeue visible tasks and inspect worker logs.",
        },
        {
            "name": "DeadLetterGrowing",
            "expr": "increase(agent_task_dead_letter_total[15m]) > 0",
            "for": "1m",
            "severity": "critical",
            "runbook": "Pause affected role queue, sample DLQ payloads and route to human/verifier.",
        },
        {
            "name": "CniIpPressure",
            "expr": "agent_cni_ip_pressure_ratio > 0.95",
            "for": "5m",
            "severity": "critical",
            "runbook": "Stop scheduling new Agent pods to exhausted node pool or expand IPAM capacity.",
        },
        {
            "name": "CsiAttachLatencyHigh",
            "expr": "histogram_quantile(0.95, sum(rate(agent_csi_attach_latency_seconds_bucket[5m])) by (le,driver,storageclass,zone)) > 60",
            "for": "10m",
            "severity": "critical",
            "runbook": "Inspect CSI controller attach queue, StorageClass topology and StatefulSet rollout status.",
        },
        {
            "name": "PodOverheadPressure",
            "expr": "agent_pod_overhead_cpu_pressure_ratio > 0.2 or agent_pod_overhead_memory_pressure_ratio > 0.2",
            "for": "10m",
            "severity": "warning",
            "runbook": "Separate sandbox-heavy RuntimeClass workloads and tune requests/overhead.",
        },
    ]
    return {
        "schema": "grafana_alertmanager_bundle.v1",
        "service": service_name,
        "dashboards": dashboards,
        "alert_rules": alert_rules,
        "notification_policy": {
            "critical": "page_oncall_or_owner",
            "warning": "ticket_and_daily_review",
            "security": "never_sample_and_notify_owner",
        },
    }
