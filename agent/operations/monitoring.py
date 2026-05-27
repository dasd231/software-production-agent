from __future__ import annotations

from typing import Any


def build_monitoring_contract(*, service_name: str = "software-production-agent", slo_target: float = 0.995) -> dict[str, Any]:
    return {
        "schema": "monitoring_contract.v1",
        "service": service_name,
        "slo": {
            "availability": slo_target,
            "p95_agent_run_latency_seconds": 120,
            "p95_action_latency_seconds": 30,
            "error_budget_policy": "burn-rate alerts page humans before budget exhaustion",
        },
        "golden_signals": [
            "latency",
            "traffic",
            "errors",
            "saturation",
        ],
        "agent_specific_metrics": [
            "agent_runs_total{status,tenant,policy_version}",
            "agent_action_total{action,status,error_code}",
            "agent_action_latency_ms_bucket{action}",
            "agent_supervisor_denials_total{reason}",
            "agent_human_intervention_total{level}",
            "agent_graph_rag_query_total{status}",
            "agent_policy_canary_hold_total{reason}",
            "agent_task_queue_depth{role,priority}",
            "agent_heartbeat_staleness_seconds{agent_id,role}",
            "agent_dead_letter_total{role,reason}",
            "agent_cni_ip_pressure_ratio{node,cni,tenant}",
            "agent_csi_attach_latency_seconds_bucket{driver,storageclass,zone}",
            "agent_pod_overhead_cpu_pressure_ratio{node,runtimeclass}",
            "agent_pod_overhead_memory_pressure_ratio{node,runtimeclass}",
            "agent_scheduler_storage_topology_reject_total{storageclass,zone,reason}",
        ],
        "logs": [
            "application_json_logs",
            ".agent_events.jsonl",
            "audit_jsonl",
            "security_jsonl",
            "cost_ledger_jsonl",
        ],
        "traces": [
            "user_request -> agent_run -> decision -> action -> verifier -> artifact",
            "agent_run -> graph_events_ingest -> graph_rag -> policy_review",
            "sandbox_plan -> k8s_job -> result_ingest",
        ],
        "alerts": [
            {"name": "HighErrorRate", "expr": "rate(agent_action_total{status='error'}[5m]) > 0.05", "severity": "critical"},
            {"name": "AgentRunLatencyBurn", "expr": "p95(agent_run_latency_seconds) > 120", "severity": "warning"},
            {"name": "SupervisorDenialSpike", "expr": "increase(agent_supervisor_denials_total[10m]) > 10", "severity": "warning"},
            {"name": "HeartbeatStale", "expr": "agent_heartbeat_staleness_seconds > 30", "severity": "critical"},
            {"name": "DeadLetterGrowing", "expr": "increase(agent_dead_letter_total[15m]) > 0", "severity": "critical"},
            {"name": "PolicyCanaryHold", "expr": "increase(agent_policy_canary_hold_total[30m]) > 0", "severity": "warning"},
            {"name": "GraphIngestFailure", "expr": "increase(agent_graph_ingest_failures_total[10m]) > 0", "severity": "warning"},
            {"name": "CniIpPressure", "expr": "agent_cni_ip_pressure_ratio > 0.95", "severity": "critical"},
            {
                "name": "CsiAttachLatencyHigh",
                "expr": "histogram_quantile(0.95, sum(rate(agent_csi_attach_latency_seconds_bucket[5m])) by (le,driver,storageclass,zone)) > 60",
                "severity": "critical",
            },
            {"name": "PodOverheadPressure", "expr": "agent_pod_overhead_cpu_pressure_ratio > 0.2 or agent_pod_overhead_memory_pressure_ratio > 0.2", "severity": "warning"},
        ],
        "dashboards": [
            {
                "name": "Agent Executive Overview",
                "panels": ["availability", "run latency", "error budget", "human intervention", "release gate"],
            },
            {
                "name": "Multi-Agent Pool",
                "panels": ["heartbeat staleness", "task queue depth", "role saturation", "dead letters", "reassignments"],
            },
            {
                "name": "Graph Runtime",
                "panels": ["graph ingest throughput", "Graph-RAG latency", "policy canary holds", "failed action subgraphs"],
            },
            {
                "name": "Security/Sandbox",
                "panels": ["supervisor denials", "sandbox required", "network denies", "secret redaction violations"],
            },
        ],
    }
