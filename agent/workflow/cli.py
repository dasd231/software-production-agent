from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from agent.workflow.checkpoint import JsonlWorkflowCheckpointer
from agent.workflow.dataset import write_route_training_dataset_from_agent_events
from agent.workflow.event_bridge import load_workflow_traces_from_agent_events
from agent.workflow.interview import build_interview_readiness_report
from agent.workflow.loop_graph import analyze_agent_loop_events_file, build_agent_loop_graph_spec
from agent.workflow.optimizer import WorkflowOptimizer
from agent.workflow.policy_store import PolicyRecord, PolicyStore
from agent.workflow.project_graph import build_project_workflow, default_workflow_policy
from agent.workflow.replay import replay_logged_policy
from agent.workflow.rollout import build_canary_plan
from agent.workflow.schema import WorkflowStatus
from agent.workflow.spec import describe_compiled_workflow


def _load_events(args: argparse.Namespace):
    if getattr(args, "events", ""):
        return load_workflow_traces_from_agent_events(args.events)
    return JsonlWorkflowCheckpointer(args.trace_dir).list_events()


def _load_stored_policy(policy_store: str, policy_version: str = ""):
    if not policy_store:
        return None
    store = PolicyStore(policy_store)
    if policy_version:
        return store.load(policy_version).policy
    current = store.current()
    return current.policy if current else None


def _candidate_policy_for_replay(args: argparse.Namespace, events):
    stored = _load_stored_policy(getattr(args, "policy_store", ""), getattr(args, "policy_version", ""))
    if stored:
        return stored
    report = WorkflowOptimizer(min_samples_per_route=args.min_samples).analyze(events, default_workflow_policy())
    return report.proposed_policy or default_workflow_policy()


def _save_policy_if_requested(args: argparse.Namespace, events_count: int, findings_count: int, proposed_policy) -> None:
    if not args.policy_store or not proposed_policy:
        return
    store = PolicyStore(args.policy_store)
    parent = store.current().version if store.current() else None
    version = args.policy_version or f"workflow-policy-{len(store.list_versions()) + 1:04d}"
    store.save(
        PolicyRecord(
            version=version,
            parent_version=parent,
            policy=proposed_policy,
            notes="generated from adaptive workflow traces",
            metrics={"event_count": events_count, "finding_count": findings_count},
        ),
        make_current=args.promote,
    )
    print(f"saved policy version: {version}")


def cmd_demo(args: argparse.Namespace) -> int:
    checkpointer = JsonlWorkflowCheckpointer(args.trace_dir)
    policy = default_workflow_policy()
    policy.exploration_rate = float(args.exploration)
    workflow = build_project_workflow(checkpointer=checkpointer, policy=policy)
    run_id = args.run_id or f"workflow-{uuid4().hex[:8]}"
    state = workflow.invoke(
        args.goal,
        run_id=run_id,
        initial_data={
            "files": ["agent/main.py", "agent/core/agent_loop.py", "tests/test_agent_loop.py"],
            "structure": {"package_files": ["pyproject.toml"], "entrypoints": ["agent/main.py"]},
            "fast_path_success_bias": float(args.fast_path_success_bias),
        },
    )
    print(json.dumps({"run_id": state.run_id, "status": state.status.value, "data": state.data}, ensure_ascii=False, indent=2))
    return 0 if state.status in {WorkflowStatus.SUCCEEDED, WorkflowStatus.INTERRUPTED} else 1


def cmd_optimize(args: argparse.Namespace) -> int:
    checkpointer = JsonlWorkflowCheckpointer(args.trace_dir)
    events = checkpointer.list_events()
    policy = default_workflow_policy()
    report = WorkflowOptimizer(min_samples_per_route=args.min_samples).analyze(events, policy)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    _save_policy_if_requested(args, len(events), len(report.findings), report.proposed_policy)
    return 0


def cmd_optimize_events(args: argparse.Namespace) -> int:
    events = load_workflow_traces_from_agent_events(args.events)
    policy = default_workflow_policy()
    report = WorkflowOptimizer(min_samples_per_route=args.min_samples).analyze(events, policy)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if args.export_workflow_events:
        out_path = Path(args.export_workflow_events)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event.__dict__, ensure_ascii=False, separators=(",", ":")) + "\n")
        print(f"exported workflow traces: {out_path}")
    _save_policy_if_requested(args, len(events), len(report.findings), report.proposed_policy)
    return 0


def cmd_canary_plan(args: argparse.Namespace) -> int:
    events = _load_events(args)
    policy = default_workflow_policy()
    report = WorkflowOptimizer(min_samples_per_route=args.min_samples).analyze(events, policy)
    version = args.candidate_policy_version or args.policy_version or "candidate-policy"
    plan = build_canary_plan(report, candidate_policy_version=version)
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_interview(args: argparse.Namespace) -> int:
    events = _load_events(args)
    report = build_interview_readiness_report(events, base_policy=default_workflow_policy())
    text = report.to_markdown()
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"saved interview report: {out}")
    else:
        print(text)
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    checkpointer = JsonlWorkflowCheckpointer(args.trace_dir)
    workflow = build_project_workflow(checkpointer=checkpointer, policy=default_workflow_policy())
    workflow.patch_state(args.run_id, {"human_approved": True, "human_feedback": args.feedback})
    state = workflow.resume(args.run_id)
    print(json.dumps({"run_id": state.run_id, "status": state.status.value, "data": state.data}, ensure_ascii=False, indent=2))
    return 0 if state.status == WorkflowStatus.SUCCEEDED else 1


def cmd_replay(args: argparse.Namespace) -> int:
    events = _load_events(args)
    candidate_policy = _candidate_policy_for_replay(args, events)
    report = replay_logged_policy(events, candidate_policy=candidate_policy)
    if args.format == "markdown":
        print(report.to_markdown())
    else:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    policy = _load_stored_policy(args.policy_store, args.policy_version) or default_workflow_policy()
    workflow = build_project_workflow(policy=policy)
    spec = describe_compiled_workflow(workflow, name=args.name)
    if args.format == "mermaid":
        print(spec.to_mermaid())
    elif args.format == "markdown":
        print(spec.to_interview_markdown())
    else:
        print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_loop_spec(args: argparse.Namespace) -> int:
    spec = build_agent_loop_graph_spec()
    if args.format == "mermaid":
        print(spec.to_mermaid())
    elif args.format == "markdown":
        print(spec.to_markdown())
    else:
        print(json.dumps(spec.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_loop_analyze(args: argparse.Namespace) -> int:
    report = analyze_agent_loop_events_file(args.events)
    if args.format == "markdown":
        print(report.to_markdown())
    else:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


def cmd_export_route_dataset(args: argparse.Namespace) -> int:
    summary = write_route_training_dataset_from_agent_events(
        args.events,
        args.output,
        min_abs_reward=float(args.min_abs_reward),
    )
    if args.format == "markdown":
        print(summary.to_markdown())
    else:
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adaptive workflow runtime for software-production-agent")
    sub = parser.add_subparsers(required=True)

    demo = sub.add_parser("demo", help="run project workflow demo")
    demo.add_argument("--goal", default="优化 software-production-agent 并安全交付")
    demo.add_argument("--run-id", default="")
    demo.add_argument("--trace-dir", default=".agent_workflow_traces")
    demo.add_argument("--exploration", type=float, default=0.0)
    demo.add_argument("--fast-path-success-bias", type=float, default=0.65)
    demo.set_defaults(func=cmd_demo)

    optimize = sub.add_parser("optimize", help="analyze workflow traces and propose route policy")
    optimize.add_argument("--trace-dir", default=".agent_workflow_traces")
    optimize.add_argument("--min-samples", type=int, default=1)
    optimize.add_argument("--policy-store", default="")
    optimize.add_argument("--policy-version", default="")
    optimize.add_argument("--promote", action="store_true")
    optimize.set_defaults(func=cmd_optimize)

    opt_events = sub.add_parser("optimize-events", help="convert .agent_events.jsonl into workflow traces and optimize")
    opt_events.add_argument("--events", required=True, help="path to .agent_events.jsonl")
    opt_events.add_argument("--min-samples", type=int, default=1)
    opt_events.add_argument("--export-workflow-events", default="")
    opt_events.add_argument("--policy-store", default="")
    opt_events.add_argument("--policy-version", default="")
    opt_events.add_argument("--promote", action="store_true")
    opt_events.set_defaults(func=cmd_optimize_events)

    interview = sub.add_parser("interview", help="build interview readiness report from workflow traces or agent events")
    interview.add_argument("--events", default="", help="optional .agent_events.jsonl path")
    interview.add_argument("--trace-dir", default=".agent_workflow_traces")
    interview.add_argument("--output", default="")
    interview.set_defaults(func=cmd_interview)

    canary = sub.add_parser("canary-plan", help="build safe rollout plan for an optimized workflow policy")
    canary.add_argument("--events", default="", help="optional .agent_events.jsonl path")
    canary.add_argument("--trace-dir", default=".agent_workflow_traces")
    canary.add_argument("--min-samples", type=int, default=1)
    canary.add_argument("--policy-version", default="")
    canary.add_argument("--candidate-policy-version", default="")
    canary.set_defaults(func=cmd_canary_plan)

    approve = sub.add_parser("approve", help="approve interrupted workflow and resume")
    approve.add_argument("run_id")
    approve.add_argument("--trace-dir", default=".agent_workflow_traces")
    approve.add_argument("--feedback", default="approved by human reviewer")
    approve.set_defaults(func=cmd_approve)

    replay = sub.add_parser("replay", help="conservative logged-policy replay for workflow route policies")
    replay.add_argument("--events", default="", help="optional .agent_events.jsonl path")
    replay.add_argument("--trace-dir", default=".agent_workflow_traces")
    replay.add_argument("--min-samples", type=int, default=1)
    replay.add_argument("--policy-store", default="")
    replay.add_argument("--policy-version", default="")
    replay.add_argument("--format", choices=["json", "markdown"], default="json")
    replay.set_defaults(func=cmd_replay)

    explain = sub.add_parser("explain", help="export graph structure as json, markdown, or mermaid")
    explain.add_argument("--name", default="project-adaptive-workflow")
    explain.add_argument("--policy-store", default="")
    explain.add_argument("--policy-version", default="")
    explain.add_argument("--format", choices=["json", "markdown", "mermaid"], default="markdown")
    explain.set_defaults(func=cmd_explain)

    loop_spec = sub.add_parser("loop-spec", help="export semantic graph of the existing agent_loop")
    loop_spec.add_argument("--format", choices=["json", "markdown", "mermaid"], default="markdown")
    loop_spec.set_defaults(func=cmd_loop_spec)

    loop_analyze = sub.add_parser("loop-analyze", help="compile .agent_events.jsonl into agent_loop graph metrics")
    loop_analyze.add_argument("--events", required=True, help="path to .agent_events.jsonl")
    loop_analyze.add_argument("--format", choices=["json", "markdown"], default="markdown")
    loop_analyze.set_defaults(func=cmd_loop_analyze)

    dataset = sub.add_parser("export-route-dataset", help="export route-policy training JSONL from .agent_events.jsonl")
    dataset.add_argument("--events", required=True, help="path to .agent_events.jsonl")
    dataset.add_argument("--output", required=True, help="output JSONL dataset path")
    dataset.add_argument("--min-abs-reward", type=float, default=0.0, help="drop weak reward samples below this magnitude")
    dataset.add_argument("--format", choices=["json", "markdown"], default="markdown")
    dataset.set_defaults(func=cmd_export_route_dataset)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
