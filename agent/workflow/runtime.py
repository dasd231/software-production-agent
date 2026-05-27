from __future__ import annotations

import random
import time
from dataclasses import dataclass

from agent.skill_runtime import ContractGuard, FormatContract, ReasoningContract, assemble_skill_bundle
from agent.workflow.checkpoint import InMemoryWorkflowCheckpointer, WorkflowCheckpointer
from agent.workflow.schema import (
    END,
    START,
    GraphNode,
    NodeResult,
    Router,
    WorkflowPolicy,
    WorkflowState,
    WorkflowStatus,
    WorkflowTraceEvent,
)


def _default_skill_ids_for_node(node_name: str) -> tuple[str, ...]:
    lower = str(node_name or "").lower()
    skills: list[str] = []
    if any(term in lower for term in ("research", "rag", "context", "retrieval", "evidence")):
        skills.append("skill.semantic_retrieval")
    if any(term in lower for term in ("diff", "patch", "code", "repair", "execute")):
        skills.append("skill.diff_intelligence")
    if any(term in lower for term in ("workflow", "dispatch", "route", "gate")):
        skills.append("skill.workflow_contract")
    return tuple(dict.fromkeys(skills))


@dataclass(slots=True)
class CompiledWorkflowGraph:
    nodes: dict[str, GraphNode]
    edges: dict[str, str]
    routers: dict[str, tuple[str, Router]]
    checkpointer: WorkflowCheckpointer
    policy: WorkflowPolicy

    def invoke(self, goal: str, *, run_id: str, initial_data: dict | None = None) -> WorkflowState:
        state = WorkflowState(run_id=run_id, goal=goal, data=dict(initial_data or {}))
        return self._run(state)

    def patch_state(self, run_id: str, updates: dict) -> WorkflowState:
        state = self.checkpointer.load_state(run_id)
        if state is None:
            raise KeyError(f"unknown workflow run: {run_id}")
        patch = dict(updates)
        if "current_node" in patch:
            state.current_node = str(patch.pop("current_node"))
        if "status" in patch:
            state.status = WorkflowStatus(str(patch.pop("status")))
        state.merge(patch)
        self.checkpointer.save_state(state)
        return state

    def resume(self, run_id: str) -> WorkflowState:
        state = self.checkpointer.load_state(run_id)
        if state is None:
            raise KeyError(f"unknown workflow run: {run_id}")
        if state.status != WorkflowStatus.INTERRUPTED:
            return state
        state.status = WorkflowStatus.RUNNING
        return self._run(state)


    def _skill_guard_for_node(self, state: WorkflowState, node_name: str, result: NodeResult | None = None) -> tuple[dict, dict]:
        required = tuple(self.policy.skill_required_skill_ids.get(node_name, ())) or _default_skill_ids_for_node(node_name)
        explicit_scope = tuple(self.policy.skill_explicit_scope.get(node_name, ()))
        format_contract = FormatContract(
            schema_name="workflow_node_output.v1",
            required_fields=("node", "status", "updates", "message", "evidence"),
            optional_fields=("score", "confidence", "route_key", "route_choice"),
            field_types={"node": "str", "status": "str", "updates": "dict", "message": "str", "evidence": "list"},
            allow_extra_fields=True,
        )
        reasoning_contract = ReasoningContract(
            mode="decision_brief",
            expose_hidden_chain_of_thought=False,
            require_evidence_ids=False,
            max_visible_reasoning_items=4,
        )
        bundle = assemble_skill_bundle(
            f"{state.goal} / workflow node {node_name}",
            task_id=f"{state.run_id}:{state.step_index}:{node_name}",
            format_contract=format_contract,
            reasoning_contract=reasoning_contract,
            explicit_scope=(state.goal, node_name, *explicit_scope),
            required_skill_ids=required,
        )
        output = {
            "node": node_name,
            "status": "preflight" if result is None else "ok",
            "updates": {} if result is None else dict(result.updates),
            "message": "preflight skill acquisition" if result is None else str(result.message),
            "evidence": self._evidence_items(result),
            "score": None if result is None else result.score,
            "confidence": None if result is None else result.confidence,
        }
        report = ContractGuard().validate(bundle, output)
        return bundle.to_dict(), report.to_dict()

    def _evidence_items(self, result: NodeResult | None) -> list[dict]:
        if result is None:
            return []
        raw = result.updates.get("evidence") if isinstance(result.updates, dict) else None
        if isinstance(raw, list):
            out = []
            for idx, item in enumerate(raw):
                if isinstance(item, dict):
                    out.append(dict(item))
                else:
                    out.append({"evidence_id": f"node-evidence-{idx}", "summary": str(item)})
            return out
        return []

    def _run(self, state: WorkflowState) -> WorkflowState:
        state.status = WorkflowStatus.RUNNING
        if state.current_node == START:
            state.current_node = self.edges[START]
        self.checkpointer.save_state(state)

        while state.current_node != END:
            if state.step_index >= self.policy.max_steps:
                state.status = WorkflowStatus.FAILED
                state.error = "max_steps_exceeded"
                self.checkpointer.save_state(state)
                return state

            node_name = state.current_node
            node = self.nodes[node_name]
            state.step_index += 1
            started = time.time()
            result = NodeResult()
            status = "ok"
            error = None
            route_key = None
            route_choice = None

            skill_bundle: dict | None = None
            skill_guard_report: dict | None = None

            try:
                if self.policy.skill_runtime_enabled:
                    skill_bundle, pre_report = self._skill_guard_for_node(state, node_name, None)
                    state.set("last_skill_bundle", skill_bundle)
                    state.set("last_skill_preflight", pre_report)
                    if self.policy.skill_fail_closed and pre_report.get("ok") is False:
                        status = "error"
                        error = "skill_preflight_failed: " + ",".join(
                            str(v.get("code", "UNKNOWN")) for v in pre_report.get("violations", []) if isinstance(v, dict)
                        )
                        state.error = error
                        state.status = WorkflowStatus.FAILED
                        raise RuntimeError(error)

                result = node(state)

                if self.policy.skill_runtime_enabled:
                    skill_bundle, skill_guard_report = self._skill_guard_for_node(state, node_name, result)
                    state.set("last_skill_bundle", skill_bundle)
                    state.set("last_skill_guard_report", skill_guard_report)
                    if self.policy.skill_fail_closed and skill_guard_report.get("ok") is False:
                        status = "error"
                        codes = [
                            str(v.get("code", "UNKNOWN"))
                            for v in skill_guard_report.get("violations", [])
                            if isinstance(v, dict)
                        ]
                        error = "skill_guard_failed: " + ",".join(codes)
                        state.error = error
                        state.status = WorkflowStatus.FAILED
                    else:
                        state.merge(result.updates)
                else:
                    state.merge(result.updates)

                if state.status != WorkflowStatus.FAILED:
                    if result.interrupt:
                        status = "interrupt"
                        state.status = WorkflowStatus.INTERRUPTED
                    else:
                        route_key, route_choice = self._next_node(node_name, state, result)
                        state.current_node = route_choice
            except Exception as exc:  # noqa: BLE001 - runtime captures arbitrary node failure
                status = "error"
                error = error or f"{type(exc).__name__}: {exc}"
                state.error = error
                state.status = WorkflowStatus.FAILED

            ended = time.time()
            self.checkpointer.append_event(
                WorkflowTraceEvent(
                    run_id=state.run_id,
                    step_index=state.step_index,
                    node=node_name,
                    status=status,  # type: ignore[arg-type]
                    started_at=started,
                    ended_at=ended,
                    latency_ms=(ended - started) * 1000,
                    route_key=route_key,
                    route_choice=route_choice if route_key else None,
                    score=result.score,
                    confidence=result.confidence,
                    cost=result.cost,
                    error=error,
                    metadata={
                        "message": result.message,
                        "skill_runtime_enabled": self.policy.skill_runtime_enabled,
                        "skill_bundle": skill_bundle or {},
                        "skill_guard_report": skill_guard_report or {},
                    },
                )
            )
            self.checkpointer.save_state(state)

            if state.status in {WorkflowStatus.FAILED, WorkflowStatus.INTERRUPTED}:
                return state

        state.current_node = END
        state.status = WorkflowStatus.SUCCEEDED
        self.checkpointer.save_state(state)
        return state

    def _next_node(self, node_name: str, state: WorkflowState, result: NodeResult) -> tuple[str | None, str]:
        if node_name in self.routers:
            route_key, router = self.routers[node_name]
            return route_key, router(state, result, self.policy)
        if node_name in self.edges:
            return None, self.edges[node_name]
        return None, END


class AdaptiveWorkflowGraph:
    """LangGraph-inspired runtime with optimization hooks.

    This is the project's embedded second-modification layer: it keeps the graph
    model lightweight while exposing route_key/route_choice telemetry for bandit,
    reward and policy optimization.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: dict[str, str] = {}
        self.routers: dict[str, tuple[str, Router]] = {}

    def add_node(self, name: str, node: GraphNode) -> "AdaptiveWorkflowGraph":
        if name in {START, END}:
            raise ValueError(f"reserved node name: {name}")
        self.nodes[name] = node
        return self

    def add_edge(self, source: str, target: str) -> "AdaptiveWorkflowGraph":
        self.edges[source] = target
        return self

    def add_conditional_edges(self, source: str, route_key: str, router: Router) -> "AdaptiveWorkflowGraph":
        self.routers[source] = (route_key, router)
        return self

    def compile(
        self,
        *,
        checkpointer: WorkflowCheckpointer | None = None,
        policy: WorkflowPolicy | None = None,
    ) -> CompiledWorkflowGraph:
        return CompiledWorkflowGraph(
            nodes=dict(self.nodes),
            edges=dict(self.edges),
            routers=dict(self.routers),
            checkpointer=checkpointer or InMemoryWorkflowCheckpointer(),
            policy=policy or WorkflowPolicy(),
        )


def weighted_choice(candidates: dict[str, float], exploration_rate: float = 0.0) -> str:
    if not candidates:
        raise ValueError("weighted_choice requires candidates")
    if exploration_rate <= 0:
        return max(sorted(candidates), key=lambda key: (float(candidates[key]), key))
    if random.random() < exploration_rate:
        return random.choice(list(candidates))
    total = sum(max(0.0, float(v)) for v in candidates.values())
    if total <= 0:
        return sorted(candidates)[0]
    threshold = random.random() * total
    acc = 0.0
    for key, value in sorted(candidates.items()):
        acc += max(0.0, float(value))
        if acc >= threshold:
            return key
    return next(iter(candidates))
