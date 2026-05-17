"""Enterprise rollout plan for execution and data-plane growth."""

from __future__ import annotations

from typing import Any


def build_distributed_platform_plan() -> dict[str, Any]:
    return {
        "schema": "distributed_platform_plan.v1",
        "north_star": "control-plane owned evidence, Ray-first execution, data-plane by workload",
        "planes": [
            {
                "name": "control_plane",
                "owns": ["job spec", "manifest", "lineage", "promotion gate", "audit"],
                "must_not_delegate": ["business rules", "release decision", "evidence authority"],
            },
            {
                "name": "execution_plane",
                "primary": "Ray",
                "owns": ["distributed tasks", "actors", "resource labels", "retryable jobs"],
                "first_workloads": ["learning", "evaluation", "promotion", "training dispatch"],
            },
            {
                "name": "batch_data_plane",
                "primary": "Spark",
                "owns": ["lakehouse transforms", "large-scale cleaning", "dedupe", "partitioned datasets"],
                "entry_condition": "JSONL snapshots become too large or too numerous for local Python preparation",
            },
            {
                "name": "streaming_data_plane",
                "primary": "Flink",
                "owns": ["event streams", "stateful monitoring", "online feature updates", "audit aggregation"],
                "entry_condition": "continuous event throughput and stateful real-time decisions become material",
            },
        ],
        "adoption_order": [
            "1. Ray execution contracts and manifests",
            "2. Parquet/object-storage dataset snapshots",
            "3. Spark batch pipelines for large training corpora",
            "4. Flink for genuinely stateful real-time flows",
        ],
        "anti_patterns": [
            "Do not replace the control plane with a scheduler.",
            "Do not introduce Flink before there is a real streaming problem.",
            "Do not let Spark own model-promotion or workflow semantics.",
            "Do not start clusters from ordinary metadata inspection paths.",
        ],
    }
