from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent.workflow.schema import END, START
from agent.workflow.runtime import CompiledWorkflowGraph


@dataclass(slots=True)
class WorkflowNodeSpec:
    name: str
    role: str
    interview_note: str = ""


@dataclass(slots=True)
class WorkflowEdgeSpec:
    source: str
    target: str
    conditional: bool = False
    route_key: str = ""


@dataclass(slots=True)
class WorkflowSpec:
    name: str
    nodes: list[WorkflowNodeSpec] = field(default_factory=list)
    edges: list[WorkflowEdgeSpec] = field(default_factory=list)
    optimization_hooks: list[str] = field(default_factory=list)
    interview_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [asdict(node) for node in self.nodes],
            "edges": [asdict(edge) for edge in self.edges],
            "optimization_hooks": self.optimization_hooks,
            "interview_summary": self.interview_summary,
        }

    def to_mermaid(self) -> str:
        lines = ["flowchart TD"]
        for edge in self.edges:
            source = "START" if edge.source == START else "END" if edge.source == END else edge.source
            target = "START" if edge.target == START else "END" if edge.target == END else edge.target
            if edge.conditional:
                lines.append(f"    {source} -- {edge.route_key} --> {target}")
            else:
                lines.append(f"    {source} --> {target}")
        return "\n".join(lines) + "\n"

    def to_interview_markdown(self) -> str:
        lines = [f"# Workflow Spec: {self.name}", ""]
        lines.append(self.interview_summary)
        lines.append("")
        lines.append("## Nodes")
        for node in self.nodes:
            lines.append(f"- `{node.name}`: {node.role}. {node.interview_note}".strip())
        lines.append("")
        lines.append("## Edges")
        for edge in self.edges:
            if edge.conditional:
                lines.append(f"- `{edge.source}` -- `{edge.route_key}` --> `{edge.target}`")
            else:
                lines.append(f"- `{edge.source}` --> `{edge.target}`")
        lines.append("")
        lines.append("## Optimization hooks")
        for hook in self.optimization_hooks:
            lines.append(f"- {hook}")
        return "\n".join(lines) + "\n"


def _node_role(name: str) -> tuple[str, str]:
    mapping = {
        "inspect_context": ("context hydration", "Equivalent to a LangGraph node that prepares state before planning."),
        "build_plan": ("planner", "Creates stage-level intent without executing side effects."),
        "choose_action": ("policy node", "Reuses agent.decision and bandit scoring to select the next action."),
        "assess_similarity_collapse": (
            "collapse guard",
            "Measures multi-agent rationale similarity/effective rank before execution.",
        ),
        "rewind_blind_fanout": (
            "diversity recovery",
            "Rewinds dense consensus into diversity-aware message retention before re-planning.",
        ),
        "execution_dispatcher": ("route dispatcher", "Emits execution_strategy telemetry after collapse guard passes."),
        "fast_execute": ("execution branch", "Low-cost route for simple or low-risk tasks."),
        "safe_execute": ("execution branch", "Higher-confidence guarded route for risky actions."),
        "evaluate_outcome": ("evaluator", "Turns execution result into reward and updates decision memory."),
        "repair": ("repair loop", "Conditional recovery path after failed execution."),
        "human_gate": ("interrupt gate", "Human-in-the-loop pause/resume point for low-confidence paths."),
        "finalize": ("terminal summarizer", "Produces final workflow summary."),
    }
    return mapping.get(name, ("workflow node", "Project-specific node."))


def describe_compiled_workflow(graph: CompiledWorkflowGraph, *, name: str = "project-adaptive-workflow") -> WorkflowSpec:
    nodes = []
    for node_name in sorted(graph.nodes):
        role, note = _node_role(node_name)
        nodes.append(WorkflowNodeSpec(name=node_name, role=role, interview_note=note))

    edges: list[WorkflowEdgeSpec] = []
    for source, target in sorted(graph.edges.items()):
        edges.append(WorkflowEdgeSpec(source=source, target=target, conditional=False))
    for source, (route_key, _router) in sorted(graph.routers.items()):
        # We cannot statically know every target without executing router logic. Use policy choices
        # when available; otherwise use a symbolic conditional edge.
        choices = sorted(graph.policy.route_weights.get(route_key, {}))
        if choices:
            for choice in choices:
                edges.append(WorkflowEdgeSpec(source=source, target=choice, conditional=True, route_key=route_key))
        else:
            edges.append(WorkflowEdgeSpec(source=source, target="<dynamic>", conditional=True, route_key=route_key))

    return WorkflowSpec(
        name=name,
        nodes=nodes,
        edges=edges,
        optimization_hooks=[
            "conditional route_key / route_choice are recorded into WorkflowTraceEvent",
            "WorkflowOptimizer aggregates route reward and proposes WorkflowPolicy route_weights",
            "PolicyStore versions candidate policies for promotion and rollback",
                        "CanaryPlan adds guardrails before adaptive policy reaches production traffic",
                        "event_bridge converts existing .agent_events.jsonl into workflow traces",
                        "collapse_route records similarity-collapse alarms and diversity-aware rewind decisions",
                    ],
        interview_summary=(
            "This workflow is LangGraph-inspired but project-native: graph execution is separated "
            "from optimization, and existing agent decision/reward events feed the route policy loop."
        ),
    )
