from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from agent.local_training.feature_extraction import (
    GITHUB_FEATURES,
    MIDDLE_FEATURES,
    extract_github_features,
    extract_github_label,
    extract_middle_features,
    extract_middle_label,
    stable_id,
)
from agent.local_training.quality import build_training_scorecard, evaluate_training_quality
from agent.local_training.schemas import LocalModelArtifact, LocalTrainingExample
from agent.software_middle_model.traces import load_middle_model_traces


def _sigmoid(value: float) -> float:
    if value >= 40:
        return 1.0
    if value <= -40:
        return 0.0
    return 1.0 / (1.0 + math.exp(-value))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _load_json_or_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    if path.suffix.lower() == ".jsonl":
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
        return rows
    try:
        item = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(item, dict):
        nested = None
        if isinstance(item.get("rows"), list):
            nested = item.get("rows")
        elif isinstance(item.get("ranking"), dict) and isinstance(item["ranking"].get("rows"), list):
            nested = item["ranking"].get("rows")
        if isinstance(nested, list):
            return [row for row in nested if isinstance(row, dict)]
        return [item]
    if isinstance(item, list):
        return [row for row in item if isinstance(row, dict)]
    return []


def _predict(weights: dict[str, float], bias: float, x: dict[str, float], features: tuple[str, ...]) -> float:
    return _sigmoid(bias + sum(float(weights.get(f, 0.0)) * float(x.get(f, 0.0)) for f in features))


def _evaluate_rows(
    rows: list[LocalTrainingExample],
    weights: dict[str, float],
    bias: float,
    features: tuple[str, ...],
    *,
    threshold: float = 0.5,
) -> dict[str, Any]:
    if not rows:
        return {"example_count": 0, "accuracy": 0.0, "log_loss": 0.0, "positive_rate": 0.0}
    correct = 0
    loss = 0.0
    tp = fp = tn = fn = 0
    for row in rows:
        prob = _predict(weights, bias, row.features, features)
        pred = int(prob >= threshold)
        y = int(row.label)
        correct += int(pred == y)
        loss += -(y * math.log(max(prob, 1e-9)) + (1 - y) * math.log(max(1 - prob, 1e-9)))
        if pred == 1 and y == 1:
            tp += 1
        elif pred == 1 and y == 0:
            fp += 1
        elif pred == 0 and y == 0:
            tn += 1
        else:
            fn += 1
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    return {
        "example_count": len(rows),
        "accuracy": round(correct / len(rows), 4),
        "log_loss": round(loss / len(rows), 6),
        "positive_rate": round(sum(row.label for row in rows) / len(rows), 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


def _split_examples(rows: list[LocalTrainingExample]) -> tuple[list[LocalTrainingExample], list[LocalTrainingExample]]:
    if len(rows) < 5:
        return rows, []
    train: list[LocalTrainingExample] = []
    validation: list[LocalTrainingExample] = []
    for idx, row in enumerate(rows):
        if idx % 5 == 4:
            validation.append(row)
        else:
            train.append(row)
    return train, validation


def _train_logistic(
    rows: list[LocalTrainingExample],
    features: tuple[str, ...],
    *,
    epochs: int,
    lr: float = 0.18,
) -> dict[str, Any]:
    weights = {feature: 0.0 for feature in features}
    bias = 0.0
    train_rows, validation_rows = _split_examples(rows)
    if not train_rows:
        return {
            "weights": weights,
            "bias": bias,
            "metrics": {"example_count": 0, "accuracy": 0.0},
            "validation_metrics": {"example_count": 0, "accuracy": 0.0},
        }
    for _ in range(max(int(epochs), 1)):
        for row in train_rows:
            pred = _predict(weights, bias, row.features, features)
            err = float(row.label) - pred
            bias += lr * err
            for feature in features:
                weights[feature] += lr * err * float(row.features.get(feature, 0.0))
    return {
        "weights": {k: round(v, 6) for k, v in weights.items()},
        "bias": round(bias, 6),
        "metrics": _evaluate_rows(train_rows, weights, bias, features),
        "validation_metrics": _evaluate_rows(validation_rows, weights, bias, features),
    }


def _middle_examples(traces: list[dict[str, Any]]) -> list[LocalTrainingExample]:
    examples: list[LocalTrainingExample] = []
    for trace in traces:
        label = extract_middle_label(trace)
        if label is None:
            continue
        y, label_source = label
        example_id = str(trace.get("trace_id") or trace.get("run_id") or stable_id("middle", trace))
        examples.append(
            LocalTrainingExample(
                example_id=example_id,
                target="middle_model_rule_acceleration",
                features=extract_middle_features(trace),
                label=y,
                label_source=label_source,
                source_ref=str(trace.get("source_ref", example_id)),
                metadata={"schema": trace.get("schema", "workflow_trace_like")},
            )
        )
    return examples


def _github_examples(rows: list[dict[str, Any]]) -> list[LocalTrainingExample]:
    examples: list[LocalTrainingExample] = []
    for row in rows:
        y, label_source = extract_github_label(row)
        repo = str(row.get("repo") or row.get("full_name") or row.get("url") or stable_id("repo", row))
        examples.append(
            LocalTrainingExample(
                example_id=stable_id("github", row),
                target="github_corpus_quality_evaluator",
                features=extract_github_features(row),
                label=y,
                label_source=label_source,
                source_ref=repo,
                metadata={"routes": row.get("routes", []), "license": row.get("license", "")},
            )
        )
    return examples


def train_middle_model_local(trace_paths: tuple[Path, ...], output_dir: Path, *, epochs: int = 30) -> dict[str, Any]:
    traces: list[dict[str, Any]] = []
    for path in trace_paths:
        traces.extend(load_middle_model_traces(path))
    examples = _middle_examples(traces)
    model = _train_logistic(examples, MIDDLE_FEATURES, epochs=epochs)
    artifact = LocalModelArtifact(
        schema="local_middle_model_training.v2",
        target="middle_model_rule_acceleration",
        status="trained" if examples else "needs_data",
        feature_names=MIDDLE_FEATURES,
        model_type="transparent_logistic_cpu",
        weights=model["weights"],
        bias=model["bias"],
        metrics=model["metrics"],
        hard_gates=(
            "security_sensitive_actions_always_run_expensive_rules",
            "missing_must_have_need_slot_forbids_shortcut",
            "guard_violation_forbids_shortcut",
        ),
        notes=(
            "label 1 means run expensive deterministic rules; label 0 means shortcut is allowed",
            "use as shadow inference before enabling automatic shortcuts",
        ),
    ).to_dict()
    artifact.update(
        {
            "trace_count": len(traces),
            "training_examples": len(examples),
            "validation_metrics": model["validation_metrics"],
            "decision_label": "1 means run expensive rules; 0 means shortcut is allowed",
            "pitfalls": [
                "shortcut labels are biased if humans only review failures",
                "high-risk actions must keep rule fallback regardless of model confidence",
                "latency_saved_ms can cause over-optimization unless quality_delta is tracked",
            ],
        }
    )
    _write_json(output_dir / "middle_model_local.json", artifact)
    _write_jsonl(output_dir / "middle_model_examples.jsonl", [example.to_dict() for example in examples])
    return artifact


def train_github_evaluator_local(ranking_paths: tuple[Path, ...], output_dir: Path, *, epochs: int = 30) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in ranking_paths:
        rows.extend(_load_json_or_jsonl(path))
    examples = _github_examples(rows)
    model = _train_logistic(examples, GITHUB_FEATURES, epochs=epochs)
    artifact = LocalModelArtifact(
        schema="local_github_evaluator_training.v2",
        target="github_corpus_quality_evaluator",
        status="trained" if examples else "needs_data",
        feature_names=GITHUB_FEATURES,
        model_type="transparent_logistic_cpu",
        weights=model["weights"],
        bias=model["bias"],
        metrics=model["metrics"],
        hard_gates=(
            "license_failure_forces_quarantine",
            "secret_or_malware_scan_failure_forces_quarantine",
            "downstream_utility_required_before_distillation_pool",
        ),
        notes=(
            "label 1 means route repo toward train_now/distill_pool; label 0 means observe/quarantine",
            "popularity is not a hard gate; governance and downstream utility dominate promotion",
        ),
    ).to_dict()
    artifact.update(
        {
            "ranking_rows": len(rows),
            "training_examples": len(examples),
            "validation_metrics": model["validation_metrics"],
            "decision_label": "1 means route repo toward train_now/distill_pool; 0 means observe/quarantine",
            "pitfalls": [
                "stars/freshness can dominate quality if labels are noisy",
                "license/governance must remain a hard gate, not a soft model preference",
                "web-search facets can create popularity bias; keep novelty and holdout coverage",
            ],
        }
    )
    _write_json(output_dir / "github_evaluator_local.json", artifact)
    _write_jsonl(output_dir / "github_evaluator_examples.jsonl", [example.to_dict() for example in examples])
    return artifact


def run_local_training(
    *,
    target: str,
    output_dir: Path,
    middle_trace_paths: tuple[Path, ...] = (),
    github_ranking_paths: tuple[Path, ...] = (),
    epochs: int = 30,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    normalized = target.strip().lower() or "both"
    results: dict[str, Any] = {}
    if normalized in {"middle", "middle_model", "both"}:
        results["middle_model"] = train_middle_model_local(middle_trace_paths, output_dir, epochs=epochs)
    if normalized in {"github", "github_evaluator", "corpus", "both"}:
        results["github_evaluator"] = train_github_evaluator_local(github_ranking_paths, output_dir, epochs=epochs)
    manifest = {
        "schema": "local_training_manifest.v2",
        "target": normalized,
        "output_dir": str(output_dir.resolve()),
        "results": results,
        "quality_evaluation": {},
        "artifacts": {
            "middle_model": str((output_dir / "middle_model_local.json").resolve()),
            "github_evaluator": str((output_dir / "github_evaluator_local.json").resolve()),
            "middle_examples": str((output_dir / "middle_model_examples.jsonl").resolve()),
            "github_examples": str((output_dir / "github_evaluator_examples.jsonl").resolve()),
        },
        "next_steps": [
            "collect more accepted/rejected middle-model shortcut traces",
            "join GitHub ranking rows with downstream retrieval/training quality labels",
            "run shadow inference locally before allowing automatic shortcut decisions",
            "only move to server training after local labels and hard gates are stable",
        ],
    }
    manifest["quality_evaluation"] = evaluate_training_quality(manifest)
    manifest["scorecard"] = build_training_scorecard(manifest)
    _write_json(output_dir / "local_training_manifest.json", manifest)
    _write_json(output_dir / "local_training_scorecard.json", manifest["scorecard"])
    return manifest
