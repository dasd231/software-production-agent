from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent.local_training.inference import classify_middle_decision, load_local_model, score_github_repo
from agent.local_training.sample_data import write_demo_local_training_data
from agent.local_training.sft_export import export_server_finetune_bundle
from agent.local_training.trainer import run_local_training


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CPU-only local training for Software Production Agent small models")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("make-demo-data", help="write tiny local demo datasets")
    demo.add_argument("--output-dir", default="local_training_demo")

    train = sub.add_parser("train", help="train local transparent logistic baselines")
    train.add_argument("--target", default="both", choices=["both", "middle", "middle_model", "github", "github_evaluator", "corpus"])
    train.add_argument("--output-dir", default="local_training_runs")
    train.add_argument("--middle-trace-path", action="append", default=[])
    train.add_argument("--github-ranking-path", action="append", default=[])
    train.add_argument("--epochs", type=int, default=30)

    pred_mid = sub.add_parser("predict-middle", help="predict whether expensive rules must run")
    pred_mid.add_argument("--model", required=True)
    pred_mid.add_argument("--trace", required=True)

    pred_git = sub.add_parser("score-github", help="score one GitHub repo ranking row")
    pred_git.add_argument("--model", required=True)
    pred_git.add_argument("--row", required=True)

    export = sub.add_parser("export-sft", help="export local examples to server-ready SFT JSONL")
    export.add_argument("--training-dir", required=True)
    export.add_argument("--output-dir", required=True)

    args = parser.parse_args(argv)

    if args.command == "make-demo-data":
        result = write_demo_local_training_data(Path(args.output_dir))
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "train":
        manifest = run_local_training(
            target=args.target,
            output_dir=Path(args.output_dir),
            middle_trace_paths=tuple(Path(p) for p in args.middle_trace_path),
            github_ranking_paths=tuple(Path(p) for p in args.github_ranking_path),
            epochs=args.epochs,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    if args.command == "predict-middle":
        model = load_local_model(Path(args.model), target="middle")
        print(json.dumps(classify_middle_decision(model, _load_json(Path(args.trace))), ensure_ascii=False, indent=2))
        return 0

    if args.command == "score-github":
        model = load_local_model(Path(args.model), target="github")
        print(json.dumps(score_github_repo(model, _load_json(Path(args.row))), ensure_ascii=False, indent=2))
        return 0

    if args.command == "export-sft":
        manifest = export_server_finetune_bundle(Path(args.training_dir), Path(args.output_dir))
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
