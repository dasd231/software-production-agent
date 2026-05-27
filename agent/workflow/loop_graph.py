from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from agent.workflow.event_bridge import load_agent_events


@dataclass(slots=True)
class LoopStageNode:
    name: str
    role: str
    source: str
    interview_note: str = ""


@dataclass(slots=True)
class LoopStageEdge:
    source: str
    target: str
    condition: str = ""
    optimization_hook: str = ""


@dataclass(slots=True)
class AgentLoopGraphSpec:
    name: str
    nodes: list[LoopStageNode] = field(default_factory=list)
    edges: list[LoopStageEdge] = field(default_factory=list)
    migration_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
            "migration_notes": list(self.migration_notes),
        }

    def to_mermaid(self) -> str:
        lines = ["flowchart TD"]
        for edge in self.edges:
            label = edge.condition or edge.optimization_hook
            if label:
                safe_label = label.replace('"', "'")
                lines.append(f"    {edge.source} -- \"{safe_label}\" --> {edge.target}")
            else:
                lines.append(f"    {edge.source} --> {edge.target}")
        return "\n".join(lines) + "\n"

    def to_markdown(self) -> str:
        lines = [f"# Agent Loop Semantic Graph: {self.name}", ""]
        lines.append("This is the migration bridge from the stable `agent.core.agent_loop` to an adaptive workflow graph.")
        lines.append("")
        lines.append("## Nodes")
        for node in self.nodes:
            lines.append(f"- `{node.name}`: {node.role} (`{node.source}`). {node.interview_note}".strip())
        lines.append("")
        lines.append("## Edges")
        for edge in self.edges:
            suffix = ""
            if edge.condition:
                suffix += f" condition={edge.condition}"
            if edge.optimization_hook:
                suffix += f" optimization_hook={edge.optimization_hook}"
            lines.append(f"- `{edge.source}` -> `{edge.target}`{suffix}")
        lines.append("")
        lines.append("## Migration notes")
        for note in self.migration_notes:
            lines.append(f"- {note}")
        return "\n".join(lines) + "\n"


@dataclass(slots=True)
class LoopTransitionMetric:
    source: str
    target: str
    count: int


@dataclass(slots=True)
class LoopGraphFinding:
    severity: str
    title: str
    detail: str
    action: str


@dataclass(slots=True)
class AgentLoopGraphAnalysis:
    total_events: int
    run_count: int
    iteration_count: int
    stage_counts: dict[str, int] = field(default_factory=dict)
    action_counts: dict[str, int] = field(default_factory=dict)
    terminal_counts: dict[str, int] = field(default_factory=dict)
    transition_metrics: list[LoopTransitionMetric] = field(default_factory=list)
    findings: list[LoopGraphFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_events": self.total_events,
            "run_count": self.run_count,
            "iteration_count": self.iteration_count,
            "stage_counts": dict(sorted(self.stage_counts.items())),
            "action_counts": dict(sorted(self.action_counts.items())),
            "terminal_counts": dict(sorted(self.terminal_counts.items())),
            "transition_metrics": [asdict(metric) for metric in self.transition_metrics],
            "findings": [asdict(finding) for finding in self.findings],
        }

    def to_markdown(self) -> str:
        lines = ["# Agent Loop Graph Analysis", ""]
        lines.append(f"- total_events: `{self.total_events}`")
        lines.append(f"- run_count: `{self.run_count}`")
        lines.append(f"- iteration_count: `{self.iteration_count}`")
        lines.append("")
        lines.append("## Stage counts")
        if self.stage_counts:
            for key, value in sorted(self.stage_counts.items()):
                lines.append(f"- `{key}`: {value}")
        else:
            lines.append("- No plan stage events found.")
        lines.append("")
        lines.append("## Action counts")
        if self.action_counts:
            for key, value in sorted(self.action_counts.items()):
                lines.append(f"- `{key}`: {value}")
        else:
            lines.append("- No action events found.")
        lines.append("")
        lines.append("## Terminal counts")
        if self.terminal_counts:
            for key, value in sorted(self.terminal_counts.items()):
                lines.append(f"- `{key}`: {value}")
        else:
            lines.append("- No terminal events found.")
        lines.append("")
        lines.append("## Top transitions")
        for metric in self.transition_metrics[:12]:
            lines.append(f"- `{metric.source}` -> `{metric.target}`: {metric.count}")
        lines.append("")
        lines.append("## Findings")
        if not self.findings:
            lines.append("- No major graph-level issue detected.")
        for finding in self.findings:
            lines.append(f"- **{finding.severity}** {finding.title}: {finding.detail} → {finding.action}")
        return "\n".join(lines) + "\n"


def build_agent_loop_graph_spec() -> AgentLoopGraphSpec:
    nodes = [
        LoopStageNode("loop_start", "run bootstrap", "run_agent_loop", "Creates run_id, state/session paths and event stream."),
        LoopStageNode("sync_workspace", "workspace hydration", "ProjectState.sync_file_list + build_workspace_index", "Keeps graph state aligned with files."),
        LoopStageNode("plan", "planner stage", "agent.core.planner.plan", "Chooses dynamic stage and task intent."),
        LoopStageNode("context", "context enrichment", "run_context_chain", "Injects skill/RAG/MCP evidence before deciding."),
        LoopStageNode("decision_policy", "policy scoring", "evaluate_decision_policy", "Ranks candidate actions with project decision policy."),
        LoopStageNode("decide", "LLM/scripted action selection", "AgentBrain.decide", "Produces executable protocol action."),
        LoopStageNode("ship_gate", "pre-finish governance", "_ship_gate_error", "Blocks unsafe finish attempts before execution."),
        LoopStageNode("execute", "guarded execution", "executor.run_action_guarded", "Executes through policy limits and governance."),
        LoopStageNode("reward_trace", "reward and trace update", "compute_reward_signal + build_decision_trace", "Turns outcome into learning signal."),
        LoopStageNode("quality_gate", "review/QA/safety checks", "calculate_health_score + should_stop_fixing", "Decides whether to continue, fix, stop, or ship."),
        LoopStageNode("fix", "repair proposal", "AgentBrain.fix", "Generates repair action after executor error."),
        LoopStageNode("finish", "successful terminal", "finish event", "Final successful terminal path."),
        LoopStageNode("stopped", "guarded terminal", "stopped event", "Max-iteration/safety/investigate terminal path."),
    ]
    edges = [
        LoopStageEdge("loop_start", "sync_workspace"),
        LoopStageEdge("sync_workspace", "plan"),
        LoopStageEdge("plan", "context", optimization_hook="context_budget_policy"),
        LoopStageEdge("context", "decision_policy", optimization_hook="evidence_quality_gate"),
        LoopStageEdge("decision_policy", "decide", optimization_hook="candidate_action_policy"),
        LoopStageEdge("decision_policy", "stopped", condition="investigate_required"),
        LoopStageEdge("decide", "ship_gate", condition="action == finish"),
        LoopStageEdge("decide", "execute", condition="action != finish"),
        LoopStageEdge("ship_gate", "sync_workspace", condition="blocked"),
        LoopStageEdge("ship_gate", "execute", condition="approved"),
        LoopStageEdge("execute", "reward_trace"),
        LoopStageEdge("reward_trace", "finish", condition="finish ok"),
        LoopStageEdge("reward_trace", "quality_gate", condition="non-terminal action"),
        LoopStageEdge("quality_gate", "fix", condition="executor error and repair allowed", optimization_hook="repair_policy"),
        LoopStageEdge("quality_gate", "stopped", condition="safety/max_iterations"),
        LoopStageEdge("quality_gate", "sync_workspace", condition="continue"),
        LoopStageEdge("fix", "execute", condition="fix action != finish"),
        LoopStageEdge("fix", "sync_workspace", condition="fix skipped or finish"),
    ]
    return AgentLoopGraphSpec(
        name="agent-loop-semantic-graph",
        nodes=nodes,
        edges=edges,
        migration_notes=[
            "Keep the existing agent_loop as stable execution path; introduce graph semantics through events first.",
            "Promote plan/context/decision/execute/reward into Workflow nodes once telemetry coverage is stable.",
            "Treat conditional edges as policy surfaces: context_budget_policy, candidate_action_policy, repair_policy.",
            "Use logged replay and canary rollout before changing route weights in production.",
        ],
    )


def _event_stage(row: dict[str, Any]) -> str:
    kind = str(row.get("kind", ""))
    mapping = {
        "loop_start": "loop_start",
        "plan": "plan",
        "context_enriched": "context",
        "decision_policy": "decision_policy",
        "decide": "decide",
        "ship_gate_blocked": "ship_gate",
        "execute": "execute",
        "execute_fix": "execute",
        "reward_signal": "reward_trace",
        "decision_trace": "reward_trace",
        "fix": "fix",
        "finish": "finish",
        "stopped": "stopped",
    }
    return mapping.get(kind, kind or "unknown")


def _safe_iteration(row: dict[str, Any]) -> int:
    try:
        return int(row.get("iteration", -1))
    except (TypeError, ValueError):
        return -1


def _safe_ts(row: dict[str, Any]) -> float:
    try:
        return float(row.get("ts", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _run_id(row: dict[str, Any]) -> str:
    return str(row.get("run_id") or "unknown-run")


def _action_from_row(row: dict[str, Any]) -> str:
    for key in ("action_summary", "result_summary"):
        value = row.get(key)
        if isinstance(value, dict) and value.get("action"):
            return str(value.get("action"))
    result = row.get("result")
    if isinstance(result, dict) and result.get("action"):
        return str(result.get("action"))
    return ""


def analyze_agent_loop_events(rows: Iterable[dict[str, Any]]) -> AgentLoopGraphAnalysis:
    events = sorted(list(rows), key=lambda row: (_run_id(row), _safe_ts(row), _safe_iteration(row), str(row.get("event_id", ""))))
    run_ids = {_run_id(row) for row in events}
    iteration_ids = {(_run_id(row), _safe_iteration(row)) for row in events if _safe_iteration(row) >= 0}
    stage_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    terminal_counts: Counter[str] = Counter()
    transition_counts: Counter[tuple[str, str]] = Counter()
    per_iteration_kinds: dict[tuple[str, int], set[str]] = defaultdict(set)
    previous_stage_by_run: dict[str, str] = {}

    for row in events:
        kind = str(row.get("kind", ""))
        stage = _event_stage(row)
        run_id = _run_id(row)
        iteration = _safe_iteration(row)
        if iteration >= 0:
            per_iteration_kinds[(run_id, iteration)].add(kind)
        if kind == "plan":
            summary = row.get("plan_summary")
            plan_stage = ""
            if isinstance(summary, dict):
                plan_stage = str(summary.get("stage", ""))
            if not plan_stage and isinstance(row.get("plan"), dict):
                plan_stage = str(row["plan"].get("stage", ""))
            if plan_stage:
                stage_counts[plan_stage] += 1
        action = _action_from_row(row)
        if action:
            action_counts[action] += 1
        if kind == "finish":
            terminal_counts["finish"] += 1
        elif kind == "stopped":
            summary = row.get("result_summary")
            summary_reason = summary.get("reason") if isinstance(summary, dict) else ""
            reason = str(row.get("reason") or summary_reason or "stopped")
            terminal_counts[f"stopped:{reason or 'unknown'}"] += 1
        elif kind == "ship_gate_blocked":
            terminal_counts["ship_gate_blocked"] += 1

        prev = previous_stage_by_run.get(run_id)
        if prev and prev != stage:
            transition_counts[(prev, stage)] += 1
        previous_stage_by_run[run_id] = stage

    findings: list[LoopGraphFinding] = []
    for key, kinds in sorted(per_iteration_kinds.items()):
        if "plan" in kinds and "context_enriched" not in kinds:
            findings.append(
                LoopGraphFinding(
                    severity="medium",
                    title="Plan without context enrichment",
                    detail=f"run={key[0]} iteration={key[1]} has plan but no context_enriched event",
                    action="inspect context chain failures or event emission order",
                )
            )
        if "decide" in kinds and "decision_policy" not in kinds:
            findings.append(
                LoopGraphFinding(
                    severity="high",
                    title="Decide without policy event",
                    detail=f"run={key[0]} iteration={key[1]} has decide but no decision_policy event",
                    action="block migration until policy trace coverage is complete",
                )
            )
    if terminal_counts.get("ship_gate_blocked", 0) > 0:
        findings.append(
            LoopGraphFinding(
                severity="medium",
                title="Ship gate is actively blocking finish attempts",
                detail=f"blocked_count={terminal_counts['ship_gate_blocked']}",
                action="surface ship_gate as an explicit conditional edge with human/QA feedback",
            )
        )
    stopped_total = sum(v for k, v in terminal_counts.items() if k.startswith("stopped"))
    if stopped_total > terminal_counts.get("finish", 0):
        findings.append(
            LoopGraphFinding(
                severity="medium",
                title="Stopped runs dominate finished runs",
                detail=f"stopped={stopped_total}, finish={terminal_counts.get('finish', 0)}",
                action="analyze stop reasons before tightening workflow policy",
            )
        )
    if action_counts.get("run_command", 0) > 0 and action_counts.get("production_check", 0) == 0:
        findings.append(
            LoopGraphFinding(
                severity="low",
                title="Execution lacks production_check coverage",
                detail="run_command appears but production_check does not",
                action="route ship/QA stages toward production_check before finish",
            )
        )

    transition_metrics = [
        LoopTransitionMetric(source=src, target=dst, count=count)
        for (src, dst), count in transition_counts.most_common()
    ]
    return AgentLoopGraphAnalysis(
        total_events=len(events),
        run_count=len(run_ids),
        iteration_count=len(iteration_ids),
        stage_counts=dict(stage_counts),
        action_counts=dict(action_counts),
        terminal_counts=dict(terminal_counts),
        transition_metrics=transition_metrics,
        findings=findings[:24],
    )


def analyze_agent_loop_events_file(path: str | Path) -> AgentLoopGraphAnalysis:
    return analyze_agent_loop_events(load_agent_events(path))
