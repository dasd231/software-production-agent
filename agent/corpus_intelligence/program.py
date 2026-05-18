"""Control-plane blueprint for a Linux-resident GitHub corpus program."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_github_corpus_program() -> dict[str, Any]:
    """Describe the user-facing corpus system we are building toward."""

    return {
        "schema": "github_corpus_program.v1",
        "generated_at": _now(),
        "north_star": "Continuously turn GitHub into governed project intelligence for a self-owned repo-reading model.",
        "system_shape": {
            "deployment": "linux_resident_continuous_program",
            "heavy_compute_rule": "crawler and profiler stay CPU-first; GPU work enters only through explicit training gates",
            "main_loop": [
                "discover",
                "rank_and_route",
                "fetch_and_profile",
                "build_project_objects",
                "train_or_distill",
                "evaluate",
                "feed_back",
            ],
        },
        "modules": [
            {
                "id": "discovery",
                "label": "GitHub Discovery",
                "owns": ["seed queries", "web-assisted query expansion", "rate-budgeted crawl schedule"],
                "primary_algorithm": "seed queries + WebSearch facet expansion + MMR-style diversity selection",
            },
            {
                "id": "recommendation_router",
                "label": "Recommendation & Routing",
                "owns": ["candidate scoring", "hard governance gates", "train/distill/benchmark routing"],
                "primary_algorithm": "transparent weighted multi-objective ranker with novelty and downstream utility",
            },
            {
                "id": "projectization",
                "label": "Project Object Builder",
                "owns": ["repo memory", "symbol index", "evidence index", "task synthesis"],
                "primary_algorithm": "linked project-object construction from code, docs, manifests and tests",
            },
            {
                "id": "distillation",
                "label": "Teacher Distillation",
                "owns": ["teacher prompts", "teacher outputs", "review gates", "distillation export"],
                "primary_algorithm": "evidence-grounded SFT, then optional multi-teacher consensus",
            },
            {
                "id": "student_training",
                "label": "Self-owned Student Training",
                "owns": ["recipes", "LoRA/QLoRA jobs", "ablation", "promotion"],
                "primary_algorithm": "adapter-first fine-tuning on open DeepSeek-family bases",
            },
            {
                "id": "evaluation_feedback",
                "label": "Evaluation & Feedback",
                "owns": ["intake metrics", "dataset metrics", "model metrics", "resampling signals"],
                "primary_algorithm": "offline benchmark gates + corpus feedback resampling",
            },
            {
                "id": "ops_guard",
                "label": "Ops & Resource Guard",
                "owns": ["shared-server admission", "job manifests", "safe launch", "audit"],
                "primary_algorithm": "CPU-first ingestion plus conservative GPU preflight",
            },
        ],
        "algorithms": {
            "search": {
                "name": "web_assisted_faceted_discovery",
                "steps": [
                    "operator seed queries",
                    "WebSearch titles/snippets -> facet terms",
                    "dedupe and lexical MMR-style diversification",
                    "query arms retained for later reward-based scheduling",
                ],
            },
            "recommendation": {
                "name": "transparent_multi_objective_ranker",
                "features": [
                    "lexical relevance",
                    "repo quality",
                    "freshness",
                    "governance",
                    "novelty",
                    "downstream utility",
                ],
                "routes": ["train_now", "distill_pool", "benchmark_holdout", "observe", "quarantine"],
            },
            "repo_quality": {
                "name": "weighted_structural_quality",
                "signals": [
                    "architecture coverage",
                    "package manifest",
                    "entrypoints",
                    "tests",
                    "docs",
                    "CI",
                    "license",
                    "popularity",
                    "structure completeness",
                ],
            },
            "distillation": {
                "name": "evidence_grounded_distillation",
                "stages": [
                    "prompt_batch",
                    "teacher_execution_plan",
                    "teacher_execution_run",
                    "teacher_output_review",
                    "distillation_export",
                ],
                "future_extension": "multi_teacher_consensus_with_disagreement_review",
            },
        },
        "student_model_policy": {
            "family": "deepseek_open_family",
            "default_posture": "adapter_first",
            "first_round_base": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
            "coder_lane_example": "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
            "rules": [
                "keep the self-owned model path on open DeepSeek-family bases",
                "prefer LoRA/QLoRA before expensive full fine-tuning",
                "bind every recipe to explicit benchmark suites and lineage",
            ],
        },
        "metric_taxonomy": {
            "discovery": [
                "query_yield",
                "accepted_candidate_rate",
                "novelty_rate",
                "license_allowlist_pass_rate",
                "dedupe_rate",
            ],
            "repo_quality": [
                "repo_quality_score",
                "architecture_coverage",
                "docs_present_rate",
                "tests_present_rate",
                "ci_present_rate",
            ],
            "dataset": [
                "grounded_required_rate",
                "citation_rate",
                "duplicate_rate",
                "task_diversity",
                "min_task_share",
            ],
            "model": [
                "recall_at_5",
                "mrr",
                "citation_precision",
                "answer_f1",
                "faithfulness_score",
                "impact_f1",
                "tokens_per_correct_answer",
            ],
            "ops": [
                "crawl_backlog",
                "queue_latency",
                "gpu_admission_pass_rate",
                "foreign_gpu_process_block_rate",
                "job_failure_rate",
            ],
        },
        "feedback_loop": {
            "inputs": [
                "repo ranking decisions",
                "dataset quality reports",
                "benchmark deltas",
                "promotion failures",
            ],
            "outputs": [
                "query-arm reweighting",
                "facet promotion or suppression",
                "sampling-weight adjustment",
                "new holdout slices",
            ],
        },
        "linux_runtime": {
            "processes": [
                "crawler scheduler",
                "CPU repo profiler workers",
                "project-object builders",
                "dataset/eval workers",
                "GPU-gated training worker",
            ],
            "shared_server_posture": [
                "continuous crawling stays CPU-first",
                "GPU work is sparse, explicit and guarded",
                "all long-running jobs emit manifests and resumable checkpoints",
            ],
        },
        "recommended_next_builds": [
            "run the single-shot corpus scheduler under systemd timer or cron",
            "projectize routed crawl outputs into repo-memory and route-separated task assets",
            "add online query-arm rewards after enough crawl history exists",
            "upgrade benchmark lane from skeleton to paper-grade comparison",
        ],
    }
