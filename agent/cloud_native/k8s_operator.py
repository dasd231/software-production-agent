from __future__ import annotations

from typing import Any


def build_etcd_maintenance_crd() -> dict[str, Any]:
    yaml = """apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: etcdmaintenancepolicies.ops.agent.dev
spec:
  group: ops.agent.dev
  scope: Namespaced
  names:
    plural: etcdmaintenancepolicies
    singular: etcdmaintenancepolicy
    kind: EtcdMaintenancePolicy
    shortNames: [emtp]
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              properties:
                snapshotCountTarget:
                  type: integer
                  minimum: 1000
                  default: 10000
                compaction:
                  type: object
                  properties:
                    mode:
                      type: string
                      enum: [periodic, revision]
                      default: periodic
                    retention:
                      type: string
                      default: 10h
                defrag:
                  type: object
                  properties:
                    fragmentationThreshold:
                      type: number
                      default: 0.35
                    oneMemberAtATime:
                      type: boolean
                      default: true
                    avoidLeaderFirst:
                      type: boolean
                      default: true
                safetyGates:
                  type: object
                  properties:
                    requireHealthyQuorum:
                      type: boolean
                      default: true
                    maxLeaderChangesPerHour:
                      type: integer
                      default: 1
            status:
              type: object
              properties:
                phase:
                  type: string
                recommendation:
                  type: string
                lastRunTime:
                  type: string
                  format: date-time
                observedFragmentationRatio:
                  type: number
                observedBackendSizeBytes:
                  type: integer
                observedBackendInUseBytes:
                  type: integer
"""
    return {
        "schema": "etcd_maintenance_crd.v1",
        "kind": "EtcdMaintenancePolicy",
        "apiVersion": "ops.agent.dev/v1alpha1",
        "yaml": yaml,
        "fields": [
            "snapshotCountTarget",
            "compaction.mode",
            "compaction.retention",
            "defrag.fragmentationThreshold",
            "safetyGates.requireHealthyQuorum",
        ],
    }


def build_etcd_operator_reconcile_plan() -> dict[str, Any]:
    return {
        "schema": "etcd_operator_reconcile_plan.v1",
        "controller": "EtcdMaintenancePolicyReconciler",
        "loop": [
            "watch EtcdMaintenancePolicy and Prometheus metric snapshots",
            "observe process/go/raft/mvcc/bbolt metrics",
            "compute fragmentation_ratio and memory_pressure",
            "gate on healthy quorum, leader stability and backend commit latency",
            "recommend or execute compaction first, defrag second",
            "process members one at a time; avoid leader first unless leadership transfer is safe",
            "write status and emit Kubernetes Event + scorecard evidence",
        ],
        "safety_invariants": [
            "never defrag more than one member at a time",
            "never compact beyond slow watcher SLA window",
            "never act during leader-change storm",
            "never act without recent snapshot backup for aggressive maintenance",
        ],
        "status_phases": ["Observing", "Recommended", "Compacting", "Defragging", "Verified", "Blocked"],
    }


def build_agent_scheduler_plugin_skeleton() -> dict[str, Any]:
    go = r'''package agentworkload

import (
    "context"

    v1 "k8s.io/api/core/v1"
    "k8s.io/apimachinery/pkg/runtime"
    framework "k8s.io/kubernetes/pkg/scheduler/framework"
)

const Name = "AgentWorkloadSchedulingPlugin"

type AgentWorkloadSchedulingPlugin struct {
    handle framework.Handle
}

func (p *AgentWorkloadSchedulingPlugin) Name() string { return Name }

// PreFilter computes effective request: containers + init max + PodOverhead + PVC/DRA hints.
func (p *AgentWorkloadSchedulingPlugin) PreFilter(ctx context.Context, cycleState *framework.CycleState, pod *v1.Pod) (*framework.PreFilterResult, *framework.Status) {
    // TODO: store workload class, pod overhead pressure, PVC class and DRA claims in cycleState.
    return nil, framework.NewStatus(framework.Success)
}

// Filter rejects nodes that cannot satisfy runtime, storage, network and device constraints.
func (p *AgentWorkloadSchedulingPlugin) Filter(ctx context.Context, cycleState *framework.CycleState, pod *v1.Pod, nodeInfo *framework.NodeInfo) *framework.Status {
    // TODO: check allocatable after PodOverhead, CSI topology, CNI/IPAM watermark, RuntimeClass handler and DRA device claims.
    return framework.NewStatus(framework.Success)
}

// Score ranks nodes by data locality, balanced packing and low control-plane risk.
func (p *AgentWorkloadSchedulingPlugin) Score(ctx context.Context, cycleState *framework.CycleState, pod *v1.Pod, nodeInfo *framework.NodeInfo) (int64, *framework.Status) {
    // TODO: combine cpu/memory fit, PV locality, CSI attach latency, CNI failure rate and failure-domain spread.
    return framework.MaxNodeScore / 2, framework.NewStatus(framework.Success)
}

func (p *AgentWorkloadSchedulingPlugin) ScoreExtensions() framework.ScoreExtensions { return nil }

// Reserve records assumed state before PreBind commits PV/ResourceClaim decisions.
func (p *AgentWorkloadSchedulingPlugin) Reserve(ctx context.Context, cycleState *framework.CycleState, pod *v1.Pod, nodeName string) *framework.Status {
    // TODO: reserve Agent workload budget and assumed storage/device allocation.
    return framework.NewStatus(framework.Success)
}

func (p *AgentWorkloadSchedulingPlugin) Unreserve(ctx context.Context, cycleState *framework.CycleState, pod *v1.Pod, nodeName string) {
    // TODO: rollback assumed allocations.
}

// PreBind commits binding side effects after the scheduler has selected a node.
func (p *AgentWorkloadSchedulingPlugin) PreBind(ctx context.Context, cycleState *framework.CycleState, pod *v1.Pod, nodeName string) *framework.Status {
    // TODO: annotate selected topology, commit ResourceClaim/PV assumptions if owned by this plugin.
    return framework.NewStatus(framework.Success)
}

func New(ctx context.Context, obj runtime.Object, handle framework.Handle) (framework.Plugin, error) {
    return &AgentWorkloadSchedulingPlugin{handle: handle}, nil
}
'''
    return {
        "schema": "agent_scheduler_plugin_skeleton.v1",
        "plugin_name": "AgentWorkloadSchedulingPlugin",
        "extension_points": ["PreFilter", "Filter", "Score", "Reserve", "Unreserve", "PreBind"],
        "go_files": [
            {
                "path": "cmd/scheduler-plugins/agentworkload/plugin.go",
                "content": go,
            }
        ],
        "scoring_inputs": [
            "pod_overhead_pressure",
            "volume_topology_score",
            "csi_attach_latency",
            "cni_ip_pressure",
            "runtimeclass_overhead",
            "dra_device_fit",
            "stateful_data_locality",
        ],
    }


def build_cloud_native_operator_assets() -> dict[str, Any]:
    return {
        "schema": "cloud_native_operator_assets.v1",
        "etcd_maintenance_crd": build_etcd_maintenance_crd(),
        "etcd_operator_reconcile": build_etcd_operator_reconcile_plan(),
        "agent_scheduler_plugin": build_agent_scheduler_plugin_skeleton(),
    }

