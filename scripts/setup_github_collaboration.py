#!/usr/bin/env python3
"""Create GitHub labels and starter issues for the big-slam collaboration plan.

Requires:
  gh auth login

Usage:
  python scripts/setup_github_collaboration.py --create-labels --create-issues
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Label:
    name: str
    color: str
    description: str


@dataclass(frozen=True)
class StarterIssue:
    title: str
    labels: tuple[str, ...]
    body: str


LABELS = [
    Label("track: employment", "0E8A16", "Work that strengthens resume, interview, demo, or production story."),
    Label("track: competition", "1D76DB", "Work that strengthens reproducible competition submission."),
    Label("track: paper", "5319E7", "Work that strengthens research framing, metrics, experiments, or paper draft."),
    Label("area: infra", "0052CC", "Server jobs, resource guards, scheduling, deployment, and operations."),
    Label("area: agent", "B60205", "Agent mainline, RAG, evidence synthesis, memory, and user loop."),
    Label("area: data", "FBCA04", "GitHub corpus, repo ranking, projectization, and dataset generation."),
    Label("area: model", "D93F0B", "Training, LoRA, distillation, model runtime, and model routing."),
    Label("area: eval", "006B75", "Benchmark, metrics, holdout, leakage checks, and experiment reports."),
    Label("area: docs", "C5DEF5", "Docs, demos, diagrams, release notes, resume/competition/paper materials."),
    Label("area: security", "D4C5F9", "Prompt injection, secrets, data boundaries, and safety controls."),
    Label("priority: p0", "B60205", "Must-have for the next milestone."),
    Label("priority: p1", "D93F0B", "Important but not blocking the whole milestone."),
    Label("priority: p2", "FBCA04", "Useful follow-up or polish."),
    Label("type: feature", "A2EEEF", "New capability."),
    Label("type: bug", "D73A4A", "Incorrect behavior."),
    Label("type: experiment", "5319E7", "Experiment, ablation, or research validation."),
    Label("type: refactor", "C2E0C6", "Structure or maintainability change without intended behavior change."),
    Label("type: documentation", "0075CA", "Documentation-only or documentation-heavy work."),
    Label("status: blocked", "000000", "Blocked by missing input, decision, dependency, or environment."),
    Label("status: ready", "0E8A16", "Ready to pick up."),
    Label("status: in-progress", "FBCA04", "Currently being worked on."),
    Label("status: review", "1D76DB", "Ready for code/doc review."),
]


STARTER_ISSUES = [
    StarterIssue(
        "[A][P0] Server-safe flywheel run scripts and status workflow",
        ("area: infra", "track: employment", "priority: p0", "type: feature", "status: ready"),
        """## Goal\nMake corpus flywheel safe and easy to run on the shared Linux server.\n\n## Deliverables\n- `scripts/run_flywheel_once.sh`\n- `scripts/check_corpus_status.sh`\n- resource guard notes for CPU/GPU/disk\n- docs for tmux/nohup/systemd timer usage\n\n## Acceptance\n- CPU-first by default\n- no automatic heavy GPU work\n- status command returns JSON\n- dry-run or small `repo-limit=3` flow documented\n""",
    ),
    StarterIssue(
        "[B][P0] Evidence-cited project reading report action",
        ("area: agent", "track: employment", "track: competition", "priority: p0", "type: feature", "status: ready"),
        """## Goal\nGiven a local or GitHub project, generate a project understanding report.\n\n## Report should include\n- project purpose\n- architecture\n- key modules\n- risks\n- improvement suggestions\n- evidence citations\n\n## Acceptance\n- can read this repository as a demo target\n- long evidence is budgeted\n- evidence is isolated from executable instructions\n- unsatisfied outputs do not enter long-term memory\n""",
    ),
    StarterIssue(
        "[C][P0] GitHub repo quality scoring and train/distill/benchmark routing",
        ("area: data", "area: eval", "track: paper", "track: competition", "priority: p0", "type: feature", "status: ready"),
        """## Goal\nImprove GitHub corpus projectization into trainable and evaluable assets.\n\n## Deliverables\n- quality scoring rationale\n- route report for `train_now`, `distill_pool`, `benchmark_holdout`, `reject`\n- manifest fields: source, license, route, label reason\n\n## Acceptance\n- `benchmark_holdout` is excluded from training bundle\n- metrics can feed back into search strategy\n- tests cover routing boundaries\n""",
    ),
    StarterIssue(
        "[Docs][P0] README first screen, architecture diagram, and big-slam narrative",
        ("area: docs", "track: employment", "track: competition", "track: paper", "priority: p0", "type: documentation", "status: ready"),
        """## Goal\nMake the repository understandable in 60 seconds.\n\n## Deliverables\n- README first-screen positioning\n- architecture diagram or text diagram\n- links to deployment, evaluation, roadmap, collaboration docs\n- resume/competition/paper value narrative\n""",
    ),
]


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(args))
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check)


def require_gh() -> None:
    if not shutil.which("gh"):
        raise SystemExit("gh CLI is not installed. Install GitHub CLI and run `gh auth login` first.")
    result = run(["gh", "auth", "status"], check=False)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit("gh is installed but not authenticated. Run `gh auth login` first.")


def existing_labels() -> set[str]:
    result = run(["gh", "label", "list", "--limit", "300", "--json", "name"])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return set()
    return {str(item.get("name", "")) for item in data if isinstance(item, dict)}


def create_or_update_labels() -> None:
    seen = existing_labels()
    for label in LABELS:
        if label.name in seen:
            run(["gh", "label", "edit", label.name, "--color", label.color, "--description", label.description], check=False)
        else:
            run(["gh", "label", "create", label.name, "--color", label.color, "--description", label.description], check=False)


def issue_exists(title: str) -> bool:
    result = run(["gh", "issue", "list", "--state", "all", "--search", f"{title} in:title", "--json", "title"], check=False)
    if result.returncode != 0:
        return False
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return any(item.get("title") == title for item in data if isinstance(item, dict))


def create_issues() -> None:
    for issue in STARTER_ISSUES:
        if issue_exists(issue.title):
            print(f"skip existing issue: {issue.title}")
            continue
        args = ["gh", "issue", "create", "--title", issue.title, "--body", issue.body]
        for label in issue.labels:
            args.extend(["--label", label])
        run(args, check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-labels", action="store_true")
    parser.add_argument("--create-issues", action="store_true")
    args = parser.parse_args()
    if not args.create_labels and not args.create_issues:
        parser.error("choose at least one: --create-labels or --create-issues")
    require_gh()
    if args.create_labels:
        create_or_update_labels()
    if args.create_issues:
        create_issues()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
