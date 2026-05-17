"""Standard workload catalog for future distributed execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DistributedWorkloadSpec:
    id: str
    label: str
    source_action: str
    description: str
    queue: str
    priority: str
    backend: str
    resources: dict[str, Any]
    retry_policy: dict[str, Any]
    expected_outputs: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "distributed_workload_spec.v1",
            "id": self.id,
            "label": self.label,
            "source_action": self.source_action,
            "description": self.description,
            "queue": self.queue,
            "priority": self.priority,
            "backend": self.backend,
            "resources": dict(self.resources),
            "retry_policy": dict(self.retry_policy),
            "expected_outputs": list(self.expected_outputs),
        }


_WORKLOADS: tuple[DistributedWorkloadSpec, ...] = (
    DistributedWorkloadSpec(
        id="learning_run",
        label="Learning material build",
        source_action="agent.learning.cli",
        description="Repository learning, slicing, cards and local RAG export.",
        queue="learning",
        priority="normal",
        backend="ray_cluster",
        resources={"cpu": 2, "gpu": 0, "memory_gb": 4},
        retry_policy={"max_attempts": 2, "retryable_failures": ["transient_io", "remote_fetch"]},
        expected_outputs=("knowledge_cards.json", "vector_index.jsonl", "training_examples.jsonl"),
    ),
    DistributedWorkloadSpec(
        id="benchmark_evaluation",
        label="Model benchmark evaluation",
        source_action="backup_eval",
        description="Candidate or baseline model evaluation against a frozen benchmark.",
        queue="evaluation",
        priority="high",
        backend="ray_cluster",
        resources={"cpu": 2, "gpu": 1, "memory_gb": 12},
        retry_policy={"max_attempts": 2, "retryable_failures": ["preempted", "node_lost"]},
        expected_outputs=("model_evaluation_report.json",),
    ),
    DistributedWorkloadSpec(
        id="promotion_gate",
        label="Promotion gate",
        source_action="promotion",
        description="Conservative candidate-vs-baseline gating after evaluation.",
        queue="governance",
        priority="high",
        backend="ray_cluster",
        resources={"cpu": 1, "gpu": 0, "memory_gb": 2},
        retry_policy={"max_attempts": 1, "retryable_failures": []},
        expected_outputs=("model_promotion_decision.json", "promotion_report.md"),
    ),
    DistributedWorkloadSpec(
        id="github_crawl_profile",
        label="Repository crawl profile",
        source_action="github_crawl_profile",
        description="Batch crawling and architecture profiling for solution ingestion.",
        queue="ingestion",
        priority="normal",
        backend="ray_cluster",
        resources={"cpu": 2, "gpu": 0, "memory_gb": 4},
        retry_policy={"max_attempts": 3, "retryable_failures": ["transient_io", "remote_fetch", "rate_limited"]},
        expected_outputs=("crawl_report.json", "solutions/"),
    ),
    DistributedWorkloadSpec(
        id="training_dispatch",
        label="Training dispatch",
        source_action="backup_model_train",
        description="Dispatch an already-reviewed training job to a distributed execution substrate.",
        queue="training",
        priority="high",
        backend="ray_cluster",
        resources={"cpu": 4, "gpu": 1, "memory_gb": 16},
        retry_policy={"max_attempts": 2, "retryable_failures": ["preempted", "node_lost", "transient_io"]},
        expected_outputs=("adapter/", "training_result.json", "training_job_manifest.json"),
    ),
    DistributedWorkloadSpec(
        id="agent_workflow",
        label="Agent workflow",
        source_action="workflow_dry_run",
        description="Future distributed execution envelope for approved workflow nodes.",
        queue="workflow",
        priority="normal",
        backend="ray_cluster",
        resources={"cpu": 1, "gpu": 0, "memory_gb": 2},
        retry_policy={"max_attempts": 2, "retryable_failures": ["transient_io"]},
        expected_outputs=("run_manifest.json", ".agent_events.jsonl"),
    ),
)


def list_distributed_workloads() -> list[dict[str, Any]]:
    return [row.to_dict() for row in _WORKLOADS]


def get_distributed_workload(workload_id: str) -> dict[str, Any] | None:
    for row in _WORKLOADS:
        if row.id == workload_id:
            return row.to_dict()
    return None
