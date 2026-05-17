"""Explicit LoRA/SFT launcher for backup local models.

This entrypoint stays separate from `backup_model_train` on purpose:

- the action prepares and audits a training job;
- this module performs the long-running GPU work only when an operator launches it.

That separation keeps training reproducible without letting an agent silently start
hours-long model jobs during ordinary workflow execution.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.chains.model_training import detect_training_environment
from agent.training.jobs import (
    load_training_job_manifest,
    transition_training_job,
    write_training_job_manifest,
)


def _load_spec(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("training spec must be a JSON object")
    required = ("base_model", "adapter_name", "dataset", "hyperparameters", "output_dir")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f"training spec missing keys: {', '.join(missing)}")
    return raw


def _render_messages(messages: list[dict[str, Any]], tokenizer: Any) -> str:
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    except Exception:
        chunks: list[str] = []
        for row in messages:
            role = str(row.get("role", "user") or "user").strip()
            content = str(row.get("content", "") or "").strip()
            if content:
                chunks.append(f"{role}: {content}")
        return "\n".join(chunks)


def render_training_row(row: dict[str, Any], tokenizer: Any) -> str:
    messages = row.get("messages")
    if isinstance(messages, list):
        return _render_messages([item for item in messages if isinstance(item, dict)], tokenizer)
    instruction = str(row.get("instruction", "") or "").strip()
    inp = str(row.get("input", "") or "").strip()
    output = str(row.get("output", "") or "").strip()
    prompt = instruction if not inp else f"{instruction}\n\n输入：\n{inp}"
    return _render_messages(
        [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": output},
        ],
        tokenizer,
    )


def _load_stack() -> dict[str, Any]:
    try:
        import torch
        from datasets import load_dataset
        from peft import LoraConfig
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from trl import SFTConfig, SFTTrainer
    except ImportError as exc:
        raise RuntimeError(f"training dependency missing: {exc}") from exc
    return {
        "torch": torch,
        "load_dataset": load_dataset,
        "LoraConfig": LoraConfig,
        "AutoModelForCausalLM": AutoModelForCausalLM,
        "AutoTokenizer": AutoTokenizer,
        "SFTConfig": SFTConfig,
        "SFTTrainer": SFTTrainer,
    }


def _prepare_text_dataset(path: Path, tokenizer: Any, load_dataset: Any) -> Any:
    dataset = load_dataset("json", data_files=str(path), split="train")
    return dataset.map(
        lambda row: {"text": render_training_row(dict(row), tokenizer)},
        remove_columns=list(dataset.column_names),
    )


def _latest_eval_metrics(trainer: Any) -> dict[str, Any]:
    history = getattr(getattr(trainer, "state", None), "log_history", []) or []
    for row in reversed(history):
        if isinstance(row, dict) and any(str(key).startswith("eval_") for key in row):
            return {str(key): value for key, value in row.items() if str(key).startswith("eval_")}
    return {}


def _safe_read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def finalize_training_artifacts(spec_path: Path, summary: dict[str, Any]) -> None:
    run_dir = spec_path.resolve().parent
    adapter_dir = Path(str(summary["output_dir"])).resolve()
    training_result_path = adapter_dir / "training_result.json"

    version_path = run_dir / "model_version_manifest.json"
    version = _safe_read_json(version_path)
    manifest_path = run_dir / "run_manifest.json"
    manifest = _safe_read_json(manifest_path)
    completed_at = str(
        version.get("trained_at")
        or ((manifest.get("training") or {}).get("completed_at") if isinstance(manifest.get("training"), dict) else "")
        or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    if version:
        version["rollout_stage"] = "trained"
        version["training_status"] = "completed"
        version["trained_at"] = completed_at
        version["adapter_dir"] = str(adapter_dir)
        version["training_result"] = str(training_result_path)
        version["metrics"] = {
            "train": dict(summary.get("metrics") or {}),
            "eval": dict(summary.get("eval_metrics") or {}),
        }
        version_path.write_text(json.dumps(version, ensure_ascii=False, indent=2), encoding="utf-8")

    if manifest:
        files = manifest.setdefault("files", {})
        if isinstance(files, dict):
            files["training_result"] = str(training_result_path)
            files["adapter_dir"] = str(adapter_dir)
        artifacts = manifest.setdefault("artifacts", [])
        if isinstance(artifacts, list):
            for item in (str(adapter_dir), str(training_result_path)):
                if item not in artifacts:
                    artifacts.append(item)
        manifest["training"] = {
            "status": "completed",
            "completed_at": completed_at,
            "metrics": dict(summary.get("metrics") or {}),
            "eval_metrics": dict(summary.get("eval_metrics") or {}),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    report_path = run_dir / "report.md"
    if report_path.exists():
        current_lines = report_path.read_text(encoding="utf-8", errors="replace").rstrip().splitlines()
        if "## Training Result" in current_lines:
            current_lines = current_lines[: current_lines.index("## Training Result")]
        current_lines = [
            "Status: `completed`" if line.startswith("Status: `") else line
            for line in current_lines
        ]
        current = "\n".join(current_lines)
        report_path.write_text(
            "\n".join(
                [
                    current,
                    "",
                    "## Training Result",
                    "",
                    f"- Status: `completed`",
                    f"- Completed at: `{completed_at}`",
                    f"- Adapter dir: `{adapter_dir}`",
                    f"- Train loss: `{(summary.get('metrics') or {}).get('train_loss', 'n/a')}`",
                    f"- Eval loss: `{(summary.get('eval_metrics') or {}).get('eval_loss', 'n/a')}`",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    job_manifest_path = run_dir / "training_job_manifest.json"
    if job_manifest_path.exists():
        job_manifest = load_training_job_manifest(job_manifest_path)
        job_manifest = transition_training_job(
            job_manifest,
            "completed",
            detail="training_completed",
            artifacts=[str(adapter_dir), str(training_result_path)],
        )
        write_training_job_manifest(job_manifest_path, job_manifest)


def run_training(spec_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    spec = _load_spec(spec_path.resolve())
    env = detect_training_environment()
    if not env["ready"]:
        job_manifest_path = spec_path.resolve().parent / "training_job_manifest.json"
        if job_manifest_path.exists():
            job_manifest = load_training_job_manifest(job_manifest_path)
            job_manifest = transition_training_job(
                job_manifest,
                "failed",
                detail="training_environment_not_ready",
                error="blocked_environment",
            )
            write_training_job_manifest(job_manifest_path, job_manifest)
        return {
            "status": "blocked_environment",
            "spec": str(spec_path),
            "environment": env,
        }

    stack = _load_stack()
    dataset_cfg = spec["dataset"]
    hyper = spec["hyperparameters"]
    base_model = str(spec["base_model"])
    output_dir = Path(str(spec["output_dir"])).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    tokenizer = stack["AutoTokenizer"].from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token
    train_dataset = _prepare_text_dataset(Path(str(dataset_cfg["train_file"])), tokenizer, stack["load_dataset"])
    eval_file_raw = str(dataset_cfg.get("eval_file", "") or "").strip()
    eval_file = Path(eval_file_raw) if eval_file_raw else None
    eval_dataset = (
        _prepare_text_dataset(eval_file, tokenizer, stack["load_dataset"])
        if eval_file is not None and eval_file.exists() and eval_file.is_file()
        else None
    )

    if dry_run:
        return {
            "status": "dry_run_ready",
            "spec": str(spec_path),
            "base_model": base_model,
            "train_examples": len(train_dataset),
            "eval_examples": len(eval_dataset) if eval_dataset is not None else 0,
            "output_dir": str(output_dir),
        }

    job_manifest_path = spec_path.resolve().parent / "training_job_manifest.json"
    if job_manifest_path.exists():
        job_manifest = load_training_job_manifest(job_manifest_path)
        job_manifest = transition_training_job(
            job_manifest,
            "running",
            detail="local_trl_training_started",
        )
        write_training_job_manifest(job_manifest_path, job_manifest)

    torch = stack["torch"]
    model = stack["AutoModelForCausalLM"].from_pretrained(
        base_model,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        trust_remote_code=True,
    )
    model.config.use_cache = False
    lora_config = stack["LoraConfig"](
        task_type="CAUSAL_LM",
        r=int(hyper.get("lora_r", 16)),
        lora_alpha=int(hyper.get("lora_alpha", 32)),
        lora_dropout=float(hyper.get("lora_dropout", 0.05)),
        bias="none",
        target_modules=str(hyper.get("target_modules", "all-linear") or "all-linear"),
    )
    trainer_args = stack["SFTConfig"](
        output_dir=str(output_dir),
        learning_rate=float(hyper.get("learning_rate", 2e-4)),
        num_train_epochs=float(hyper.get("epochs", 1.0)),
        per_device_train_batch_size=int(hyper.get("per_device_train_batch_size", 1)),
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=int(hyper.get("gradient_accumulation_steps", 8)),
        gradient_checkpointing=True,
        logging_steps=5,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_dataset is not None else "no",
        report_to="none",
        dataset_text_field="text",
        max_length=int(hyper.get("max_seq_length", 2048)),
        packing=False,
        fp16=bool(torch.cuda.is_available()),
    )
    trainer = stack["SFTTrainer"](
        model=model,
        args=trainer_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        processing_class=tokenizer,
        peft_config=lora_config,
    )
    train_result = trainer.train()
    trainer.save_model(str(output_dir))
    tokenizer.save_pretrained(str(output_dir))
    eval_metrics = _latest_eval_metrics(trainer)
    summary = {
        "status": "completed",
        "spec": str(spec_path),
        "base_model": base_model,
        "train_examples": len(train_dataset),
        "eval_examples": len(eval_dataset) if eval_dataset is not None else 0,
        "output_dir": str(output_dir),
        "metrics": dict(getattr(train_result, "metrics", {}) or {}),
        "eval_metrics": eval_metrics,
    }
    (output_dir / "training_result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    finalize_training_artifacts(spec_path, summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Backup local model trainer entrypoint")
    parser.add_argument("--config", required=True)
    parser.add_argument("--dry-run", action="store_true", help="只校验 spec、数据格式与环境，不启动训练")
    args = parser.parse_args(argv)
    result = run_training(Path(args.config), dry_run=bool(args.dry_run))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"dry_run_ready", "completed"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
