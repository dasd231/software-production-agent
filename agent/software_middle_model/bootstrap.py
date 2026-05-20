"""Bootstrap a first software middle-model training package.

This module is intentionally conservative.  It can create a few synthetic seed
traces only to smoke-test the training pipeline before real production traces
exist.  The generated dataset is marked as bootstrap data and should not be used
as a final model-quality claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .accelerator import decide_with_middle_model
from .dataset import MiddleModelDatasetExportInput, export_middle_model_trace_dataset
from .schema import MiddleModelInput
from .server_handoff import MiddleModelServerHandoffInput, prepare_middle_model_server_handoff
from .traces import append_middle_model_trace, build_middle_model_trace, load_middle_model_traces


@dataclass(frozen=True)
class MiddleModelBootstrapInput:
    output_root: Path
    trace_path: Path | None = None
    min_traces: int = 8
    base_model: str = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"
    adapter_name: str = "software-middle-model-lora"
    eval_ratio: float = 0.25
    max_seq_length: int = 1024
    cpu_threads: int = 4
    max_gpu_memory_gb: float = 12.0
    generate_seed_traces: bool = True


@dataclass(frozen=True)
class MiddleModelBootstrapResult:
    output_root: str
    ready_for_server: bool
    trace_path: str
    dataset: dict[str, Any] = field(default_factory=dict)
    handoff: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_root": self.output_root,
            "ready_for_server": self.ready_for_server,
            "trace_path": self.trace_path,
            "dataset": self.dataset,
            "handoff": self.handoff,
            "validation": self.validation,
            "next_steps": self.next_steps,
        }


def _seed_scenarios() -> list[dict[str, Any]]:
    return [
        {
            "task": "evidence_selection",
            "features": {"risk": "low", "bootstrap": True, "domain": "research"},
            "candidates": [
                {"id": "cheap_relevant_evidence", "quality_score": 0.94, "rule_cost_ms": 35},
                {"id": "slow_full_scan", "quality_score": 0.71, "rule_cost_ms": 520},
            ],
            "accepted": True,
            "latency_saved_ms": 480,
        },
        {
            "task": "repo_routing",
            "features": {"risk": "low", "bootstrap": True, "domain": "github"},
            "candidates": [
                {"id": "train_now", "quality_score": 0.91, "rule_cost_ms": 45},
                {"id": "manual_review", "quality_score": 0.64, "rule_cost_ms": 360},
            ],
            "accepted": True,
            "latency_saved_ms": 260,
        },
        {
            "task": "model_route_precheck",
            "features": {"risk": "medium", "bootstrap": True, "requires_exactness": False},
            "candidates": [
                {"id": "short_pool", "quality_score": 0.78, "rule_cost_ms": 40},
                {"id": "long_pool", "quality_score": 0.74, "rule_cost_ms": 95},
            ],
            "accepted": True,
            "latency_saved_ms": 80,
        },
        {
            "task": "security_sensitive_rule",
            "features": {"security_sensitive": True, "bootstrap": True},
            "candidates": [
                {"id": "apparent_shortcut", "quality_score": 0.97, "rule_cost_ms": 20},
                {"id": "full_security_rule", "quality_score": 0.86, "rule_cost_ms": 600},
            ],
            "accepted": True,
            "latency_saved_ms": 0,
        },
        {
            "task": "benchmark_triage",
            "features": {"risk": "high", "bootstrap": True},
            "candidates": [
                {"id": "skip_eval", "quality_score": 0.88, "rule_cost_ms": 15},
                {"id": "run_holdout_eval", "quality_score": 0.82, "rule_cost_ms": 700},
            ],
            "accepted": True,
            "latency_saved_ms": 0,
        },
        {
            "task": "context_budgeting",
            "features": {"risk": "low", "bootstrap": True, "domain": "rag"},
            "candidates": [
                {"id": "truncate_web_first", "quality_score": 0.89, "rule_cost_ms": 30},
                {"id": "full_token_audit", "quality_score": 0.7, "rule_cost_ms": 340},
            ],
            "accepted": True,
            "latency_saved_ms": 210,
        },
        {
            "task": "distillation_filter",
            "features": {"risk": "medium", "bootstrap": True, "domain": "teacher_review"},
            "candidates": [
                {"id": "hybrid_verify_top_k", "quality_score": 0.76, "rule_cost_ms": 120},
                {"id": "accept_teacher_output", "quality_score": 0.72, "rule_cost_ms": 20},
            ],
            "accepted": True,
            "latency_saved_ms": 60,
        },
        {
            "task": "projectization_route",
            "features": {"risk": "low", "bootstrap": True, "domain": "corpus"},
            "candidates": [
                {"id": "distill_pool", "quality_score": 0.87, "rule_cost_ms": 55},
                {"id": "reject", "quality_score": 0.43, "rule_cost_ms": 10},
            ],
            "accepted": True,
            "latency_saved_ms": 120,
        },
    ]


def ensure_seed_traces(trace_path: Path, *, min_traces: int) -> dict[str, Any]:
    target = trace_path.resolve()
    existing = load_middle_model_traces(target)
    needed = max(int(min_traces), 0) - len(existing)
    generated = 0
    if needed > 0:
        scenarios = _seed_scenarios()
        for index in range(needed):
            scenario = scenarios[index % len(scenarios)]
            middle_input = MiddleModelInput(
                task=str(scenario["task"]),
                features=dict(scenario["features"]),
                candidates=tuple(dict(item) for item in scenario["candidates"]),
                confidence_threshold=0.78,
                margin_threshold=0.12,
                rule_budget_ms=250,
                model_hint="software-middle-bootstrap-seed",
            )
            decision = decide_with_middle_model(middle_input)
            trace = build_middle_model_trace(
                middle_input,
                decision,
                final_accepted=bool(scenario.get("accepted", True)),
                latency_saved_ms=float(scenario.get("latency_saved_ms", 0.0) or 0.0),
                quality_delta=0.0,
                source_trace_id=f"bootstrap-seed-{len(existing) + generated + 1:04d}",
                outcome={"grade": "bootstrap", "note": "synthetic seed trace for first smoke training only"},
            )
            append_middle_model_trace(target, trace)
            generated += 1
    return {
        "path": str(target),
        "existing_before": len(existing),
        "generated": generated,
        "total_after": len(load_middle_model_traces(target)),
        "bootstrap_only": True,
    }


def bootstrap_middle_model_first_round(inp: MiddleModelBootstrapInput) -> MiddleModelBootstrapResult:
    root = inp.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    trace_path = (inp.trace_path.resolve() if inp.trace_path is not None else root / "middle_model" / "traces.jsonl")
    seed_report = {"path": str(trace_path), "generated": 0, "total_after": len(load_middle_model_traces(trace_path))}
    if inp.generate_seed_traces:
        seed_report = ensure_seed_traces(trace_path, min_traces=max(int(inp.min_traces), 1))
    dataset_result = export_middle_model_trace_dataset(
        MiddleModelDatasetExportInput(
            trace_paths=(trace_path,),
            output_dir=root / "training_runs" / "software-middle-first",
            base_model=inp.base_model,
            eval_ratio=inp.eval_ratio,
            min_traces=max(int(inp.min_traces), 1),
            max_examples=max(int(inp.min_traces), 1) * 8,
            notes="bootstrap_first_round; replace with real accepted traces before claiming model quality",
        )
    )
    handoff_result = prepare_middle_model_server_handoff(
        MiddleModelServerHandoffInput(
            training_dir=Path(dataset_result.output_dir),
            output_dir=root / "model_runs" / "software-middle-first",
            base_model=inp.base_model,
            adapter_name=inp.adapter_name,
            min_train_examples=1,
            max_seq_length=inp.max_seq_length,
            cpu_threads=inp.cpu_threads,
            max_gpu_memory_gb=inp.max_gpu_memory_gb,
        )
    )
    ready = bool(dataset_result.validation.get("ok") and handoff_result.handoff_ready)
    validation = {
        "ok": ready,
        "seed_report": seed_report,
        "dataset_validation": dataset_result.validation,
        "handoff_validation": handoff_result.validation,
        "warnings": [
            "bootstrap seed traces are for smoke training only",
            "collect real accepted/rejected traces before any paper or product-quality claim",
            "server operator must still run GPU preflight and dry-run before launch",
        ],
    }
    return MiddleModelBootstrapResult(
        output_root=str(root),
        ready_for_server=ready,
        trace_path=str(trace_path),
        dataset=dataset_result.to_dict(),
        handoff=handoff_result.to_dict(),
        validation=validation,
        next_steps=[
            f"sync or keep this output root on the GPU server: {root}",
            f"read handoff doc: {Path(handoff_result.files['server_handoff'])}",
            f"run dry-run: python -m agent.training.backup_trainer --config {Path(handoff_result.files['spec'])} --dry-run",
            "if nvidia-smi is idle and preflight passes, run the launch command in launch_command.txt",
        ],
    )
