"""CLI for software middle-model first training handoff."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bootstrap import MiddleModelBootstrapInput, bootstrap_middle_model_first_round
from .dataset import MiddleModelDatasetExportInput, export_middle_model_trace_dataset
from .server_handoff import MiddleModelServerHandoffInput, prepare_middle_model_server_handoff


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Software middle-model dataset and server handoff CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export-dataset", help="Export trace JSONL into train/eval dataset")
    export.add_argument("--trace-path", action="append", required=True, help="Trace JSONL path; repeatable")
    export.add_argument("--output-dir", required=True)
    export.add_argument("--base-model", default="deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B")
    export.add_argument("--dataset-format", default="messages")
    export.add_argument("--eval-ratio", type=float, default=0.15)
    export.add_argument("--min-traces", type=int, default=1)
    export.add_argument("--max-examples", type=int, default=2000)
    export.add_argument("--notes", default="")

    handoff = sub.add_parser("server-handoff", help="Prepare first training package for shared GPU server")
    handoff.add_argument("--training-dir", required=True)
    handoff.add_argument("--output-dir", required=True)
    handoff.add_argument("--base-model", default="deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B")
    handoff.add_argument("--adapter-name", default="software-middle-model-lora")
    handoff.add_argument("--min-train-examples", type=int, default=1)
    handoff.add_argument("--max-seq-length", type=int, default=1024)
    handoff.add_argument("--learning-rate", type=float, default=2e-4)
    handoff.add_argument("--epochs", type=float, default=1.0)
    handoff.add_argument("--cpu-threads", type=int, default=4)
    handoff.add_argument("--max-gpu-memory-gb", type=float, default=12.0)

    bootstrap = sub.add_parser("bootstrap-first-round", help="Create seed traces, dataset, and server handoff in one safe step")
    bootstrap.add_argument("--output-root", required=True)
    bootstrap.add_argument("--trace-path", default="", help="Optional existing trace JSONL path")
    bootstrap.add_argument("--min-traces", type=int, default=8)
    bootstrap.add_argument("--base-model", default="deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B")
    bootstrap.add_argument("--adapter-name", default="software-middle-model-lora")
    bootstrap.add_argument("--eval-ratio", type=float, default=0.25)
    bootstrap.add_argument("--max-seq-length", type=int, default=1024)
    bootstrap.add_argument("--cpu-threads", type=int, default=4)
    bootstrap.add_argument("--max-gpu-memory-gb", type=float, default=12.0)
    bootstrap.add_argument("--no-seed-traces", action="store_true", help="Require existing traces instead of generating bootstrap seeds")

    args = parser.parse_args(argv)
    if args.command == "export-dataset":
        result = export_middle_model_trace_dataset(
            MiddleModelDatasetExportInput(
                trace_paths=tuple(Path(item) for item in args.trace_path),
                output_dir=Path(args.output_dir),
                base_model=str(args.base_model),
                dataset_format=str(args.dataset_format),
                eval_ratio=float(args.eval_ratio),
                min_traces=int(args.min_traces),
                max_examples=int(args.max_examples),
                notes=str(args.notes),
            )
        )
        payload = {"ok": bool(result.validation.get("ok")), **result.to_dict()}
        _print(payload)
        return 0 if payload["ok"] else 2
    if args.command == "server-handoff":
        result = prepare_middle_model_server_handoff(
            MiddleModelServerHandoffInput(
                training_dir=Path(args.training_dir),
                output_dir=Path(args.output_dir),
                base_model=str(args.base_model),
                adapter_name=str(args.adapter_name),
                min_train_examples=int(args.min_train_examples),
                max_seq_length=int(args.max_seq_length),
                learning_rate=float(args.learning_rate),
                epochs=float(args.epochs),
                cpu_threads=int(args.cpu_threads),
                max_gpu_memory_gb=float(args.max_gpu_memory_gb),
            )
        )
        payload = {"ok": bool(result.handoff_ready), **result.to_dict()}
        _print(payload)
        return 0 if payload["ok"] else 2
    if args.command == "bootstrap-first-round":
        trace_path = Path(args.trace_path) if str(args.trace_path or "").strip() else None
        result = bootstrap_middle_model_first_round(
            MiddleModelBootstrapInput(
                output_root=Path(args.output_root),
                trace_path=trace_path,
                min_traces=int(args.min_traces),
                base_model=str(args.base_model),
                adapter_name=str(args.adapter_name),
                eval_ratio=float(args.eval_ratio),
                max_seq_length=int(args.max_seq_length),
                cpu_threads=int(args.cpu_threads),
                max_gpu_memory_gb=float(args.max_gpu_memory_gb),
                generate_seed_traces=not bool(args.no_seed_traces),
            )
        )
        payload = {"ok": bool(result.ready_for_server), **result.to_dict()}
        _print(payload)
        return 0 if payload["ok"] else 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
