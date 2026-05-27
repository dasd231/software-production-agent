from __future__ import annotations

from typing import Any


def _ratio(numerator: Any, denominator: Any) -> float:
    try:
        n = float(numerator or 0.0)
        d = float(denominator or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if d <= 0:
        return 0.0
    return n / d


def _severity(value: float, *, warning: float, critical: float, higher_is_worse: bool = True) -> str:
    if higher_is_worse:
        if value >= critical:
            return "critical"
        if value >= warning:
            return "warning"
    else:
        if value <= critical:
            return "critical"
        if value <= warning:
            return "warning"
    return "ok"


def build_cloud_native_prometheus_scorecard(samples: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Prometheus-oriented scorecard for scheduler/storage/network runtime pressure.

    The scorecard is intentionally data-shape-first: it can run with no Prometheus
    dependency in tests, while every metric maps cleanly to a Prometheus query.
    """

    metric_contracts = [
        {
            "metric": "agent_cni_ip_pressure_ratio",
            "type": "gauge",
            "labels": ["node", "cni", "tenant"],
            "query": "max by(node,cni,tenant) (agent_cni_ip_allocated / clamp_min(agent_cni_ip_capacity, 1))",
            "warning": 0.85,
            "critical": 0.95,
            "why": "IPAM exhaustion turns scheduling success into runtime network setup failures.",
        },
        {
            "metric": "agent_csi_attach_latency_seconds_p95",
            "type": "summary_or_histogram_quantile",
            "labels": ["driver", "storageclass", "zone"],
            "query": "histogram_quantile(0.95, sum(rate(agent_csi_attach_latency_seconds_bucket[5m])) by (le,driver,storageclass,zone))",
            "warning": 30.0,
            "critical": 60.0,
            "why": "High attach latency blocks StatefulSet rollout and PV-bound Agent workloads.",
        },
        {
            "metric": "agent_pod_overhead_cpu_pressure_ratio",
            "type": "gauge",
            "labels": ["node", "runtimeclass"],
            "query": "sum by(node,runtimeclass)(agent_pod_overhead_cpu_millicores) / clamp_min(kube_node_status_allocatable_cpu_cores * 1000, 1)",
            "warning": 0.10,
            "critical": 0.20,
            "why": "Sandbox runtimes such as Kata/gVisor can silently consume schedulable CPU if overhead is ignored.",
        },
        {
            "metric": "agent_pod_overhead_memory_pressure_ratio",
            "type": "gauge",
            "labels": ["node", "runtimeclass"],
            "query": "sum by(node,runtimeclass)(agent_pod_overhead_memory_bytes) / clamp_min(kube_node_status_allocatable_memory_bytes, 1)",
            "warning": 0.10,
            "critical": 0.20,
            "why": "Memory overhead pressure makes bin-packing look safe while actual pod cgroups are close to eviction.",
        },
        {
            "metric": "agent_scheduler_storage_topology_reject_total",
            "type": "counter",
            "labels": ["storageclass", "zone", "reason"],
            "query": "increase(agent_scheduler_storage_topology_reject_total[10m])",
            "warning": 5,
            "critical": 20,
            "why": "Repeated topology rejection means PVC/PV/CSI capacity is fighting the scheduler.",
        },
    ]

    findings: list[dict[str, Any]] = []
    for sample in samples or []:
        node = str(sample.get("node", "unknown"))
        cni_pressure = _ratio(sample.get("cni_ip_allocated"), sample.get("cni_ip_capacity"))
        if cni_pressure:
            sev = _severity(cni_pressure, warning=0.85, critical=0.95)
            if sev != "ok":
                findings.append(
                    {
                        "metric": "agent_cni_ip_pressure_ratio",
                        "severity": sev,
                        "node": node,
                        "value": round(cni_pressure, 4),
                        "recommendation": "cordon low-IP nodes for new Agent pods or expand CNI/IPAM pool",
                    }
                )
        csi_attach_p95 = float(sample.get("csi_attach_p95_seconds", 0.0) or 0.0)
        sev = _severity(csi_attach_p95, warning=30.0, critical=60.0)
        if csi_attach_p95 and sev != "ok":
            findings.append(
                {
                    "metric": "agent_csi_attach_latency_seconds_p95",
                    "severity": sev,
                    "node": node,
                    "value": round(csi_attach_p95, 3),
                    "recommendation": "prefer local/topology-aware scheduling and inspect CSI attach queue",
                }
            )
        cpu_overhead = _ratio(sample.get("pod_overhead_cpu_millicores"), sample.get("node_allocatable_cpu_millicores"))
        mem_overhead = _ratio(sample.get("pod_overhead_memory_bytes"), sample.get("node_allocatable_memory_bytes"))
        for metric, value in (
            ("agent_pod_overhead_cpu_pressure_ratio", cpu_overhead),
            ("agent_pod_overhead_memory_pressure_ratio", mem_overhead),
        ):
            if value:
                sev = _severity(value, warning=0.10, critical=0.20)
                if sev != "ok":
                    findings.append(
                        {
                            "metric": metric,
                            "severity": sev,
                            "node": node,
                            "value": round(value, 4),
                            "recommendation": "account RuntimeClass overhead in scheduling and separate sandbox-heavy workloads",
                        }
                    )
    return {
        "schema": "cloud_native_prometheus_scorecard.v1",
        "metrics": metric_contracts,
        "findings": findings,
        "summary": {
            "metric_count": len(metric_contracts),
            "sample_count": len(samples or []),
            "finding_count": len(findings),
            "critical_count": sum(1 for item in findings if item["severity"] == "critical"),
            "warning_count": sum(1 for item in findings if item["severity"] == "warning"),
        },
        "release_gate": {
            "block_if": [
                "critical agent_cni_ip_pressure_ratio on target node pool",
                "critical agent_csi_attach_latency_seconds_p95 during StatefulSet rollout",
                "critical pod_overhead pressure for sandbox RuntimeClass",
            ],
            "warn_if": [
                "storage topology rejects increase during rollout",
                "pod overhead pressure rises while scheduler allocatable looks healthy",
            ],
        },
    }
