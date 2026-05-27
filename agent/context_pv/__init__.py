"""Enterprise long-context PV slicing and storage/compute co-design.

This package is intentionally a control-plane module: it plans semantic
context slices, placement, indexes, WAL/checksum protection, cache/loading
paths and Kubernetes resources without directly mutating a cluster.
"""

from agent.context_pv.k8s import render_context_pv_bundle, manifest_to_jsonl
from agent.context_pv.planner import plan_context_pv
from agent.context_pv.schema import ContextPVPlan, ContextPVPolicy

__all__ = [
    "ContextPVPlan",
    "ContextPVPolicy",
    "manifest_to_jsonl",
    "plan_context_pv",
    "render_context_pv_bundle",
]

