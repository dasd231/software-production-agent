from __future__ import annotations

from pathlib import Path

from agent.cloud_native import (
    assess_similarity_collapse,
    build_agent_scheduler_plugin_skeleton,
    build_cloud_native_deep_dive_plan,
    build_cloud_native_operator_assets,
    build_cloud_native_prometheus_scorecard,
    build_diversity_retention_decision,
    build_etcd_maintenance_crd,
    build_etcd_memory_optimization_plan,
    build_k8s_resource_scheduling_plan,
    build_multi_agent_similarity_collapse_route,
)
from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded


def test_multi_agent_similarity_route_has_collapse_controls() -> None:
    route = build_multi_agent_similarity_collapse_route()

    assert route["schema"] == "multi_agent_similarity_collapse_route.v1"
    assert any(item["technique"] == "sparse_and_delayed_message_passing" for item in route["route"])
    assert "effective_rank" in route["metrics"]
    assert "collapse_alarm" in " ".join(route["route"][-1]["implementation"])


def test_etcd_memory_plan_distinguishes_compaction_and_defrag() -> None:
    plan = build_etcd_memory_optimization_plan()
    algorithms = {item["name"] for item in plan["algorithms"]}

    assert "epoch_based_mvcc_compaction" in algorithms
    assert "fragmentation_aware_defrag" in algorithms
    assert any("GOMEMLIMIT" in line for item in plan["algorithms"] for line in item["pseudocode"])


def test_k8s_scheduling_plan_covers_storage_runtime_and_overhead() -> None:
    plan = build_k8s_resource_scheduling_plan(kubernetes_version="v1.36")

    assert "QueueSort" in plan["scheduler_framework"]["cycle"]
    assert "pod.spec.overhead" in plan["scheduler_framework"]["resource_formula"]
    assert plan["storage_control_plane"]["pv_controller"]["workers"][0]["name"] == "ClaimWorker"
    assert plan["storage_control_plane"]["flexvolume"]["status"] == "deprecated"
    assert "ADD" in plan["workload_runtime_interfaces"]["cni"]["operations"]
    assert plan["workload_runtime_interfaces"]["cri"]["role"]
    assert "ResourceClaim" in plan["workload_runtime_interfaces"]["dra"]["role"]


def test_cloud_native_deep_dive_action_writes_file_and_respects_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"cloud_native_deep_dive_plan","args":'
        '{"focus":"multi-agent-k8s-control-plane","kubernetes_version":"v1.36",'
        '"output_path":"plans/cloud_native.json"}}'
    )
    direct = run_action(tmp_path, action)

    assert direct["ok"] is True
    assert direct["summary"]["collapse_route_count"] >= 5
    assert direct["summary"]["etcd_algorithm_count"] >= 4
    assert (tmp_path / "plans" / "cloud_native.json").exists()

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
        limits=ExecutionLimits(granted_permissions=frozenset({"cloud:plan", "workspace:write"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"


def test_cloud_native_plan_keeps_primary_sources() -> None:
    plan = build_cloud_native_deep_dive_plan(include_sources=True)
    urls = {source["url"] for source in plan["sources"]}

    assert "https://etcd.io/blog/2025/announcing-etcd-3.6/" in urls
    assert "https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/" in urls
    assert "https://www.cni.dev/docs/spec/" in urls
    assert plan["operator_assets"]["etcd_maintenance_crd"]["kind"] == "EtcdMaintenancePolicy"
    assert plan["prometheus_scorecard"]["summary"]["metric_count"] >= 5


def test_similarity_collapse_alarm_and_diversity_retention() -> None:
    rationales = [
        "Use Kubernetes scheduler score plugin to rank nodes by pod overhead and CSI topology.",
        "Use Kubernetes scheduler score plugin to rank nodes by pod overhead and CSI topology.",
        "Use Kubernetes scheduler score plugin to rank nodes by pod overhead and CSI topology.",
    ]
    evidence = [["k8s-scheduler", "pod-overhead"], ["k8s-scheduler", "pod-overhead"], ["k8s-scheduler"]]

    assessment = assess_similarity_collapse(rationales, evidence)
    decision = build_diversity_retention_decision(
        [
            {"agent_id": "a", "rationale": rationales[0], "evidence": evidence[0]},
            {"agent_id": "b", "rationale": "Check etcd memory first; raft history dominates.", "evidence": ["etcd"]},
            {"agent_id": "c", "rationale": rationales[2], "evidence": evidence[2]},
        ],
        retain_k=2,
    )

    assert assessment["alarm"] is True
    assert assessment["metrics"]["effective_rank_ratio"] < 0.5
    assert decision["retained_count"] == 2
    assert decision["policy"].startswith("retain messages")


def test_cloud_native_operator_assets_include_crd_and_scheduler_plugin() -> None:
    crd = build_etcd_maintenance_crd()
    plugin = build_agent_scheduler_plugin_skeleton()
    assets = build_cloud_native_operator_assets()

    assert "CustomResourceDefinition" in crd["yaml"]
    assert "fragmentationThreshold" in crd["yaml"]
    assert "RuntimeClass" in plugin["go_files"][0]["content"]
    assert "k8s.io/apimachinery/pkg/runtime" in plugin["go_files"][0]["content"]
    assert assets["agent_scheduler_plugin"]["plugin_name"] == "AgentWorkloadSchedulingPlugin"


def test_cloud_native_prometheus_scorecard_flags_cni_csi_and_pod_overhead_pressure() -> None:
    scorecard = build_cloud_native_prometheus_scorecard(
        [
            {
                "node": "node-a",
                "cni_ip_allocated": 96,
                "cni_ip_capacity": 100,
                "csi_attach_p95_seconds": 65,
                "pod_overhead_cpu_millicores": 450,
                "node_allocatable_cpu_millicores": 2000,
                "pod_overhead_memory_bytes": 1024,
                "node_allocatable_memory_bytes": 4096,
            }
        ]
    )

    metrics = {item["metric"] for item in scorecard["metrics"]}
    findings = {item["metric"]: item["severity"] for item in scorecard["findings"]}
    assert "agent_cni_ip_pressure_ratio" in metrics
    assert "agent_csi_attach_latency_seconds_p95" in metrics
    assert "agent_pod_overhead_cpu_pressure_ratio" in metrics
    assert findings["agent_cni_ip_pressure_ratio"] == "critical"
    assert findings["agent_csi_attach_latency_seconds_p95"] == "critical"
    assert findings["agent_pod_overhead_cpu_pressure_ratio"] == "critical"
