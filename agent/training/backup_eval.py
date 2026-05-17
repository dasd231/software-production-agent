"""Run a deterministic benchmark against a base or LoRA-adapted local model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.evaluation.model_benchmark import compare_evaluations, evaluate_predictions, load_benchmark


_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _system_prompt_for(category: str) -> str:
    if category == "action_protocol":
        system = (_PROMPTS_DIR / "system.txt").read_text(encoding="utf-8")
        action = (_PROMPTS_DIR / "action.txt").read_text(encoding="utf-8")
        return system + "\n\n" + action
    return "你是可审计的软件生产 Agent。严格按用户要求回答；如果要求 JSON，就只输出 JSON。"


def _render_prompt(tokenizer: Any, prompt: str, *, category: str) -> str:
    messages = [
        {
            "role": "system",
            "content": _system_prompt_for(category),
        },
        {"role": "user", "content": prompt},
    ]
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    except Exception:
        return f"system: {messages[0]['content']}\nuser: {prompt}\nassistant:"


def _load_model(base_model: str, adapter_dir: str = "") -> tuple[Any, Any]:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None and tokenizer.eos_token is not None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        trust_remote_code=True,
    )
    if adapter_dir:
        model = PeftModel.from_pretrained(model, adapter_dir)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    return tokenizer, model


def _generate(tokenizer: Any, model: Any, prompt: str, *, category: str, max_new_tokens: int) -> str:
    import torch

    rendered = _render_prompt(tokenizer, prompt, category=category)
    inputs = tokenizer(rendered, return_tensors="pt")
    device = next(model.parameters()).device
    inputs = {key: value.to(device) for key, value in inputs.items()}
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )
    generated = output[0][inputs["input_ids"].shape[1] :]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


def run_benchmark(
    *,
    benchmark_path: Path,
    base_model: str,
    output_dir: Path,
    label: str,
    adapter_dir: str = "",
    subject: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cases = load_benchmark(benchmark_path)
    tokenizer, model = _load_model(base_model, adapter_dir)
    predictions = {
        case.case_id: _generate(
            tokenizer,
            model,
            case.prompt,
            category=case.category,
            max_new_tokens=case.max_new_tokens,
        )
        for case in cases
    }
    report = evaluate_predictions(
        cases,
        predictions,
        label=label,
        benchmark_id=benchmark_path.name,
        subject=subject,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    pred_path = output_dir / "predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as f:
        for case in cases:
            f.write(
                json.dumps(
                    {
                        "case_id": case.case_id,
                        "category": case.category,
                        "prediction": predictions[case.case_id],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    report_path = output_dir / "model_evaluation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown_report(output_dir / "report.md", report)
    return report


def _write_markdown_report(path: Path, report: dict[str, Any]) -> None:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    lines = [
        "# Backup Model Evaluation",
        "",
        f"Label: `{report.get('label', '')}`",
        f"Overall: `{summary.get('overall_score', 0.0)}` ({summary.get('grade', 'n/a')})",
        "",
        "## Scores",
        "",
        "| Stage | Score | Grade |",
        "| --- | ---: | --- |",
    ]
    for row in report.get("reports", []):
        if isinstance(row, dict):
            lines.append(f"| {row.get('stage')} | {row.get('overall_score')} | {row.get('grade')} |")
    lines.extend(["", "## Cases", ""])
    for row in report.get("cases", []):
        if isinstance(row, dict):
            lines.append(f"- `{row.get('case_id')}` {row.get('category')}: {row.get('score')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_evaluation_subject(
    *,
    base_model: str,
    adapter_dir: str = "",
    model_version: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe exactly what the benchmark evaluated."""

    if model_version:
        return {
            "subject_type": "model_version",
            "model_version": model_version.get("model_version", ""),
            "base_model": model_version.get("base_model", "") or base_model,
            "adapter_name": model_version.get("adapter_name", ""),
            "dataset_snapshot_id": model_version.get("dataset_snapshot_id", ""),
            "training_job_spec_id": model_version.get("training_job_spec_id", ""),
        }
    if str(adapter_dir or "").strip():
        return {
            "subject_type": "untracked_adapter",
            "base_model": base_model,
            "adapter_dir": str(adapter_dir),
        }
    return {
        "subject_type": "base_model",
        "base_model": base_model,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a backup local model")
    parser.add_argument("--benchmark", default="./benchmarks/backup_model_eval.v1.json")
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--adapter-dir", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--compare-base", default="")
    parser.add_argument("--model-version-manifest", default="")
    args = parser.parse_args(argv)
    version: dict[str, Any] | None = None
    if args.model_version_manifest:
        raw_version = json.loads(Path(args.model_version_manifest).read_text(encoding="utf-8"))
        version = raw_version if isinstance(raw_version, dict) else None
    subject = build_evaluation_subject(
        base_model=str(args.base_model),
        adapter_dir=str(args.adapter_dir or ""),
        model_version=version,
    )
    report = run_benchmark(
        benchmark_path=Path(args.benchmark),
        base_model=args.base_model,
        adapter_dir=str(args.adapter_dir or ""),
        output_dir=Path(args.output_dir),
        label=str(args.label),
        subject=subject,
    )
    if args.compare_base:
        base = json.loads(Path(args.compare_base).read_text(encoding="utf-8"))
        comparison = compare_evaluations(base, report)
        comparison_path = Path(args.output_dir) / "comparison_vs_base.json"
        comparison_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
