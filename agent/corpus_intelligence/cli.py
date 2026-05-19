"""CLI entrypoint for CPU-first GitHub corpus flywheel operations."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.corpus_intelligence.flywheel import CorpusFlywheelInput, run_corpus_flywheel_cycle
from agent.corpus_intelligence.training_bundle import CorpusTrainingBundleInput, build_corpus_training_bundle


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in str(value or "").split(",") if item.strip())


def _add_common_corpus_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-root", required=True, help="Corpus output root, e.g. ./corpus_runs/main")
    parser.add_argument("--seed-query", action="append", default=[], help="GitHub seed query; repeatable")
    parser.add_argument("--local-repo", action="append", default=[], help="Local repo path for offline/dev cycles")
    parser.add_argument("--github", action="store_true", help="Enable GitHub network search")
    parser.add_argument("--repo-limit", type=int, default=5)
    parser.add_argument("--max-query-arms", type=int, default=4)
    parser.add_argument("--min-stars", type=int, default=50)
    parser.add_argument("--license", action="append", default=[], help="Allowed SPDX license; repeatable")
    parser.add_argument("--updated-after", default="")
    parser.add_argument("--quality-threshold", type=float, default=6.5)
    parser.add_argument("--interval-seconds", type=int, default=3600)
    parser.add_argument("--cpu-thread-budget", type=int, default=2)
    parser.add_argument("--downstream-metrics-path", default="")
    parser.add_argument("--force", action="store_true")


def _cmd_flywheel(args: argparse.Namespace) -> int:
    result = run_corpus_flywheel_cycle(
        CorpusFlywheelInput(
            output_root=Path(args.output_root),
            seed_queries=tuple(args.seed_query),
            local_repos=tuple(Path(path) for path in args.local_repo),
            enable_github_network=bool(args.github),
            interval_seconds=max(int(args.interval_seconds), 1),
            repo_limit=max(int(args.repo_limit), 1),
            max_query_arms=max(int(args.max_query_arms), 1),
            min_stars=max(int(args.min_stars), 0),
            allowed_licenses=tuple(args.license),
            updated_after=str(args.updated_after),
            quality_threshold=float(args.quality_threshold),
            downstream_metrics_path=Path(args.downstream_metrics_path) if args.downstream_metrics_path else None,
            cpu_thread_budget=max(int(args.cpu_thread_budget), 1),
            force=bool(args.force),
        )
    )
    print(f"status: {result.get('status')}")
    print(f"ran: {result.get('ran')}")
    if result.get("cycle_id"):
        print(f"cycle_id: {result.get('cycle_id')}")
    files = result.get("files") if isinstance(result.get("files"), dict) else {}
    if files.get("flywheel_report"):
        print(f"flywheel_report: {files['flywheel_report']}")
    benchmark = result.get("holdout_benchmark") if isinstance(result.get("holdout_benchmark"), dict) else {}
    benchmark_files = benchmark.get("files") if isinstance(benchmark.get("files"), dict) else {}
    if benchmark_files.get("benchmark"):
        print(f"holdout_benchmark: {benchmark_files['benchmark']}")
    return 0 if bool(result.get("ran")) or result.get("status") == "skipped_cooldown" else 2


def _cmd_training_bundle(args: argparse.Namespace) -> int:
    result = build_corpus_training_bundle(
        CorpusTrainingBundleInput(
            projectization_dir=Path(args.projectization_dir),
            output_dir=Path(args.output_dir),
            include_routes=_csv_tuple(args.include_routes),
            dataset_format=str(args.dataset_format),
            eval_ratio=float(args.eval_ratio),
            min_chars=max(int(args.min_chars), 0),
            max_examples=max(int(args.max_examples), 1),
            model_hint=str(args.model_hint),
            include_protocol_examples=not bool(args.no_protocol_examples),
            protocol_example_limit=max(int(args.protocol_example_limit), 0),
            prepare_dataset=bool(args.prepare_dataset),
        )
    )
    validation = result.manifest.get("validation", {}) if isinstance(result.manifest, dict) else {}
    print(f"validation_ok: {validation.get('ok')}")
    print(f"manifest: {result.files.get('manifest')}")
    print(f"training_inputs: {result.files.get('training_inputs')}")
    if result.training_prepare:
        print(f"training_prepare: {result.training_prepare.get('output_dir')}")
        print(f"total_examples: {result.training_prepare.get('total_examples')}")
    return 0 if bool(validation.get("ok")) else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CPU-first GitHub corpus flywheel CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    flywheel = sub.add_parser("flywheel", help="Run one bounded crawl -> projectize -> holdout benchmark cycle")
    _add_common_corpus_args(flywheel)
    flywheel.set_defaults(func=_cmd_flywheel)

    bundle = sub.add_parser("training-bundle", help="Prepare first-round training inputs from projectized assets")
    bundle.add_argument("--projectization-dir", required=True)
    bundle.add_argument("--output-dir", required=True)
    bundle.add_argument("--include-routes", default="train_now,distill_pool")
    bundle.add_argument("--prepare-dataset", action="store_true")
    bundle.add_argument("--dataset-format", default="messages")
    bundle.add_argument("--eval-ratio", type=float, default=0.15)
    bundle.add_argument("--min-chars", type=int, default=20)
    bundle.add_argument("--max-examples", type=int, default=2000)
    bundle.add_argument("--model-hint", default="deepseek-coder")
    bundle.add_argument("--no-protocol-examples", action="store_true")
    bundle.add_argument("--protocol-example-limit", type=int, default=0)
    bundle.set_defaults(func=_cmd_training_bundle)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
