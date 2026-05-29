"""CPU-only local training utilities for pre-server development."""

from agent.local_training.inference import (
    classify_middle_decision,
    load_local_model,
    predict_probability,
    score_github_repo,
)
from agent.local_training.quality import build_training_quality_plan, build_training_scorecard, evaluate_training_quality
from agent.local_training.sample_data import demo_github_rankings, demo_middle_traces, write_demo_local_training_data
from agent.local_training.sft_export import export_server_finetune_bundle
from agent.local_training.trainer import run_local_training, train_github_evaluator_local, train_middle_model_local

__all__ = [
    "build_training_quality_plan",
    "build_training_scorecard",
    "classify_middle_decision",
    "demo_github_rankings",
    "demo_middle_traces",
    "evaluate_training_quality",
    "export_server_finetune_bundle",
    "load_local_model",
    "predict_probability",
    "run_local_training",
    "score_github_repo",
    "train_github_evaluator_local",
    "train_middle_model_local",
    "write_demo_local_training_data",
]
