from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _compact_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _middle_record(example: dict[str, Any]) -> dict[str, Any]:
    label = int(example.get("label", 0))
    decision = "run_expensive_rules" if label == 1 else "small_model_shortcut"
    feature_payload = {
        "target": "middle_model_rule_acceleration",
        "features": example.get("features", {}),
        "source_ref": example.get("source_ref", ""),
        "label_source": example.get("label_source", ""),
        "task": "判断当前软件生产中间层是否允许跳过费时规则，或者必须运行确定性规则兜底。",
    }
    answer = {
        "decision": decision,
        "label": label,
        "rationale": (
            "高风险、覆盖不足、Guard 违规或低置信时必须运行 expensive deterministic rules；"
            "只有低风险、高置信、覆盖充分时才允许 shortcut。"
        ),
        "hard_gates": [
            "security_sensitive_actions_always_run_expensive_rules",
            "missing_must_have_need_slot_forbids_shortcut",
            "guard_violation_forbids_shortcut",
        ],
    }
    return {
        "messages": [
            {
                "role": "system",
                "content": "你是软件生产 Agent 的中间层路由小模型，只输出可审计 JSON 决策。",
            },
            {"role": "user", "content": _compact_json(feature_payload)},
            {"role": "assistant", "content": _compact_json(answer)},
        ],
        "metadata": {
            "example_id": example.get("example_id", ""),
            "target": "middle_model_rule_acceleration",
            "label": label,
            "decision": decision,
        },
    }


def _github_record(example: dict[str, Any]) -> dict[str, Any]:
    label = int(example.get("label", 0))
    decision = "train_now_or_distill_pool" if label == 1 else "observe_or_quarantine"
    feature_payload = {
        "target": "github_corpus_quality_evaluator",
        "features": example.get("features", {}),
        "source_ref": example.get("source_ref", ""),
        "metadata": example.get("metadata", {}),
        "task": "判断 GitHub 项目是否可进入训练/蒸馏池，还是观察或隔离。",
    }
    answer = {
        "decision": decision,
        "label": label,
        "rationale": (
            "入训不仅看相关性和星标，还要看 license、secret/malware 扫描、测试、CI、"
            "架构深度、治理质量与下游实用性。"
        ),
        "hard_gates": [
            "license_failure_forces_quarantine",
            "secret_or_malware_scan_failure_forces_quarantine",
            "downstream_utility_required_before_distillation_pool",
        ],
    }
    return {
        "messages": [
            {
                "role": "system",
                "content": "你是 GitHub 语料质量评价小模型，只输出可审计 JSON 决策。",
            },
            {"role": "user", "content": _compact_json(feature_payload)},
            {"role": "assistant", "content": _compact_json(answer)},
        ],
        "metadata": {
            "example_id": example.get("example_id", ""),
            "target": "github_corpus_quality_evaluator",
            "label": label,
            "decision": decision,
        },
    }


def export_server_finetune_bundle(training_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Convert local transparent examples into server-ready SFT JSONL files.

    This does not train a large model locally. It creates the bridge from local
    label hygiene to future DeepSeek/Qwen/Code-model LoRA training on a server.
    """

    training_dir = Path(training_dir)
    output_dir = Path(output_dir)
    middle_examples = _read_jsonl(training_dir / "middle_model_examples.jsonl")
    github_examples = _read_jsonl(training_dir / "github_evaluator_examples.jsonl")
    middle_records = [_middle_record(row) for row in middle_examples]
    github_records = [_github_record(row) for row in github_examples]

    middle_path = output_dir / "middle_model_sft.jsonl"
    github_path = output_dir / "github_evaluator_sft.jsonl"
    _write_jsonl(middle_path, middle_records)
    _write_jsonl(github_path, github_records)

    manifest = {
        "schema": "local_finetune_export.v1",
        "source_training_dir": str(training_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "datasets": {
            "middle_model_sft": str(middle_path.resolve()),
            "github_evaluator_sft": str(github_path.resolve()),
        },
        "counts": {
            "middle_examples": len(middle_records),
            "github_examples": len(github_records),
            "total_examples": len(middle_records) + len(github_records),
        },
        "recommended_server_path": {
            "base_model": "DeepSeek/Qwen coder-family open model",
            "method": "LoRA or QLoRA SFT",
            "format": "chat messages JSONL",
            "keep_hard_gates_outside_model": True,
            "eval_before_promotion": [
                "decision_accuracy",
                "false_shortcut_rate",
                "license_gate_escape_rate",
                "calibration_error",
                "latency_saved_vs_quality_delta",
            ],
        },
        "notes": [
            "本地 logistic baseline 用来稳定标签和门禁；服务器 LoRA 只学习表达能力和泛化。",
            "hard gate 仍然由规则系统执行，不能被微调模型覆盖。",
        ],
    }
    _write_json(output_dir / "finetune_export_manifest.json", manifest)
    return manifest


__all__ = ["export_server_finetune_bundle"]
