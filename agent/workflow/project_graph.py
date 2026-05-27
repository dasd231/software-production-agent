from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from agent.cloud_native import assess_similarity_collapse, build_diversity_retention_decision
from agent.decision.policy import evaluate_decision_policy, update_policy_state
from agent.decision.trace import build_decision_trace
from agent.workflow.runtime import AdaptiveWorkflowGraph, weighted_choice
from agent.workflow.schema import START, NodeResult, WorkflowPolicy, WorkflowState


@dataclass
class PolicyStateAdapter:
    """Minimal ProjectState-like adapter for workflow-level policy decisions."""

    structure: dict[str, Any] = field(default_factory=dict)
    counters: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    last_result: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    progress: str = "init"
    current_stage: str = ""
    policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "structure": deepcopy(self.structure),
            "counters": deepcopy(self.counters),
            "quality": deepcopy(self.quality),
            "last_result": deepcopy(self.last_result),
            "files": list(self.files),
            "errors": deepcopy(self.errors),
            "progress": self.progress,
            "current_stage": self.current_stage,
            "policy": deepcopy(self.policy),
        }


def default_workflow_policy() -> WorkflowPolicy:
    return WorkflowPolicy(
        route_weights={
            "execution_strategy": {"safe_execute": 0.65, "fast_execute": 0.35},
            "outcome_route": {"finalize": 0.70, "repair": 0.25, "human_gate": 0.05},
            "collapse_route": {
                "rewind_blind_fanout": 0.55,
                "execution_dispatcher": 0.45,
            },
        },
        max_steps=18,
        min_confidence=0.72,
        max_repairs=1,
        exploration_rate=0.0,
        metadata={"policy_family": "software-production-adaptive-workflow"},
    )


def _adapter_from_state(state: WorkflowState) -> PolicyStateAdapter:
    existing = state.get("policy_adapter")
    if isinstance(existing, dict):
        return PolicyStateAdapter(**existing)
    structure = dict(state.get("structure", {}))
    files = [str(x) for x in state.get("files", structure.get("files", []))]
    tests = [str(x) for x in state.get("tests", structure.get("tests", []))]
    structure.setdefault("files", files)
    structure.setdefault("tests", tests)
    return PolicyStateAdapter(
        structure=structure,
        counters=dict(state.get("counters", {})),
        quality=dict(state.get("quality", {})),
        last_result=dict(state.get("last_result", {})),
        files=files,
        errors=list(state.get("errors", [])),
        progress=str(state.get("progress", "init")),
        current_stage=str(state.get("stage", "")),
        policy=dict(state.get("decision_memory", {})),
    )


def inspect_context(state: WorkflowState) -> NodeResult:
    files = [str(x) for x in state.get("files", [])]
    tests = [x for x in files if "test" in x.lower()]
    structure = dict(state.get("structure", {}))
    structure.setdefault("files", files)
    structure.setdefault("tests", tests)
    structure.setdefault("entrypoints", state.get("entrypoints", []))
    structure.setdefault("rag_hints", state.get("rag_hints", []))
    return NodeResult(
        updates={"structure": structure, "tests": tests, "context_ready": True},
        score=0.72 if files else 0.55,
        confidence=0.78 if files else 0.60,
        cost=0.02,
        message="workspace context inspected",
    )


def build_plan_node(state: WorkflowState) -> NodeResult:
    goal = state.goal.lower()
    if state.get("errors"):
        stage = "fixing"
    elif "ship" in goal or "交付" in goal:
        stage = "ship"
    elif state.get("tests"):
        stage = "qa"
    else:
        stage = "coding"
    plan = {
        "stage": stage,
        "tasks": [
            "inspect context",
            "select action through adaptive decision policy",
            "execute using route policy",
            "evaluate reward and update workflow memory",
        ],
    }
    return NodeResult(
        updates={"plan": plan, "stage": stage},
        score=0.74,
        confidence=0.78,
        cost=0.03,
        message=f"planned stage={stage}",
    )


def choose_action_node(state: WorkflowState) -> NodeResult:
    adapter = _adapter_from_state(state)
    adapter.current_stage = str(state.get("stage", adapter.current_stage))
    adapter.policy = dict(state.get("decision_memory", adapter.policy))
    decision = evaluate_decision_policy(state.goal, dict(state.get("plan", {})), adapter)
    selected = str(decision.get("selected_action", ""))
    confidence = float(decision.get("selected_bandit_score") or decision.get("selected_score") or 0.5)
    return NodeResult(
        updates={
            "decision_policy": decision,
            "selected_action": selected,
            "policy_adapter": adapter.to_dict(),
        },
        score=float(decision.get("selected_score") or 0.5),
        confidence=max(0.0, min(confidence, 1.0)),
        cost=0.04,
        message=f"selected action={selected}",
    )


def assess_similarity_collapse_node(state: WorkflowState) -> NodeResult:
    rationales = [
        str(item)
        for item in state.get("multi_agent_rationales", state.get("agent_rationales", []))
        if str(item).strip()
    ]
    raw_evidence = state.get("multi_agent_evidence", state.get("agent_evidence", []))
    evidence_sets = [
        [str(x) for x in item]
        for item in raw_evidence
        if isinstance(item, list)
    ] if isinstance(raw_evidence, list) else []
    assessment = assess_similarity_collapse(rationales, evidence_sets)
    alarm = bool(assessment.get("alarm", False)) and not bool(state.get("collapse_alarm_handled", False))
    confidence = 0.35 if alarm else 0.82
    return NodeResult(
        updates={
            "similarity_collapse_assessment": assessment,
            "collapse_alarm": alarm,
        },
        score=confidence,
        confidence=confidence,
        cost=0.03,
        message="similarity collapse assessed" if rationales else "no multi-agent rationales to assess",
    )


def route_similarity_collapse(state: WorkflowState, result: NodeResult, policy: WorkflowPolicy) -> str:
    if bool(state.get("collapse_alarm", False)):
        candidates = dict(
            policy.candidates("collapse_route")
            or {"rewind_blind_fanout": 0.55, "execution_dispatcher": 0.45}
        )
        # Collapse alarm is a safety condition: force the rewind path unless
        # exploration is explicitly enabled by policy.
        if policy.exploration_rate <= 0:
            return "rewind_blind_fanout"
        return weighted_choice(candidates, policy.exploration_rate)
    return "execution_dispatcher"


def rewind_blind_fanout_node(state: WorkflowState) -> NodeResult:
    raw_messages = state.get("multi_agent_messages", [])
    messages: list[dict[str, Any]] = []
    if isinstance(raw_messages, list):
        messages = [dict(item) for item in raw_messages if isinstance(item, dict)]
    if not messages:
        rationales = [
            str(item)
            for item in state.get("multi_agent_rationales", state.get("agent_rationales", []))
            if str(item).strip()
        ]
        evidence_sets = state.get("multi_agent_evidence", state.get("agent_evidence", []))
        for idx, rationale in enumerate(rationales):
            evidence = evidence_sets[idx] if isinstance(evidence_sets, list) and idx < len(evidence_sets) else []
            messages.append(
                {
                    "agent_id": f"agent-{idx + 1}",
                    "rationale": rationale,
                    "evidence": evidence if isinstance(evidence, list) else [],
                }
            )
    decision = build_diversity_retention_decision(messages, retain_k=max(2, min(4, len(messages) or 2)))
    rewinds = int(state.get("collapse_rewinds", 0)) + 1
    return NodeResult(
        updates={
            "collapse_alarm_handled": True,
            "collapse_alarm": False,
            "collapse_rewinds": rewinds,
            "diversity_retention_decision": decision,
            "progress": "rewind_blind_fanout",
        },
        score=0.66,
        confidence=0.68,
        cost=0.06,
        message="collapse alarm handled by diversity-aware blind fanout rewind",
    )


def execution_dispatcher_node(state: WorkflowState) -> NodeResult:
    return NodeResult(
        updates={"execution_dispatcher_ready": True},
        score=0.78,
        confidence=0.78,
        cost=0.005,
        message="dispatching to execution_strategy route",
    )


def route_execution_strategy(state: WorkflowState, result: NodeResult, policy: WorkflowPolicy) -> str:
    selected = str(state.get("selected_action", ""))
    score = float(state.get("decision_policy", {}).get("selected_score", 0.0) or 0.0)
    if selected in {"finish"} and score < policy.min_confidence:
        return "human_gate"
    if selected in {"write_file", "run_command", "production_check"}:
        candidates = dict(policy.candidates("execution_strategy") or {"safe_execute": 0.65, "fast_execute": 0.35})
        if selected == "production_check":
            candidates["safe_execute"] = candidates.get("safe_execute", 0.1) + 0.25
        return weighted_choice(candidates, policy.exploration_rate)
    return "safe_execute"


def _simulate_result(state: WorkflowState, *, strategy: str) -> dict[str, Any]:
    action = str(state.get("selected_action", "workspace_index"))
    has_tests = bool(state.get("tests"))
    ok = True
    if strategy == "fast_execute" and action in {"write_file", "run_command"} and not has_tests:
        ok = float(state.get("fast_path_success_bias", 0.65)) >= 0.5
    return {
        "ok": ok,
        "action": action,
        "strategy": strategy,
        "duration_ms": 120 if strategy == "fast_execute" else 380,
        "progress": "run_ok" if ok else "needs_fix",
    }


def fast_execute_node(state: WorkflowState) -> NodeResult:
    result = _simulate_result(state, strategy="fast_execute")
    confidence = 0.62 if result["ok"] else 0.42
    return NodeResult(
        updates={"last_result": result, "execution_strategy": "fast_execute"},
        score=confidence,
        confidence=confidence,
        cost=0.05,
        message="executed fast path",
    )


def safe_execute_node(state: WorkflowState) -> NodeResult:
    result = _simulate_result(state, strategy="safe_execute")
    confidence = 0.82 if result["ok"] else 0.55
    return NodeResult(
        updates={"last_result": result, "execution_strategy": "safe_execute"},
        score=confidence,
        confidence=confidence,
        cost=0.12,
        message="executed safe path",
    )


def evaluate_outcome_node(state: WorkflowState) -> NodeResult:
    result = dict(state.get("last_result", {}))
    ok = bool(result.get("ok", False))
    reward = {
        "total": 1.0 if ok else -0.7,
        "ok": ok,
        "source": "adaptive_workflow_outcome",
        "components": {"execution_ok": 1.0 if ok else -1.0},
    }
    decision = dict(state.get("decision_policy", {}))
    action_obj = {"action": str(state.get("selected_action", result.get("action", ""))), "args": {}}
    memory = update_policy_state(
        dict(state.get("decision_memory", {})),
        executed_action=str(action_obj["action"]),
        reward_signal=reward,
        decision=decision,
    )
    trace = build_decision_trace(
        iteration=int(state.step_index),
        policy_decision=decision,
        action_obj=action_obj,
        reward_signal=reward,
    )
    confidence = 0.84 if ok else 0.38
    return NodeResult(
        updates={
            "reward_signal": reward,
            "decision_trace": trace,
            "decision_memory": memory,
            "outcome_ok": ok,
        },
        score=confidence,
        confidence=confidence,
        cost=0.02,
        message="outcome evaluated and decision memory updated",
    )


def route_outcome(state: WorkflowState, result: NodeResult, policy: WorkflowPolicy) -> str:
    if bool(state.get("outcome_ok")):
        return "finalize"
    repairs = int(state.get("repairs", 0))
    if repairs < policy.max_repairs:
        return "repair"
    if float(result.confidence or 0.0) < policy.min_confidence:
        return "human_gate"
    return "finalize"


def repair_node(state: WorkflowState) -> NodeResult:
    repairs = int(state.get("repairs", 0)) + 1
    errors = list(state.get("errors", []))
    errors.append({"source": "adaptive_workflow", "message": "fast path failed; route to repair"})
    return NodeResult(
        updates={"repairs": repairs, "errors": errors, "progress": "repairing"},
        score=0.58,
        confidence=0.62,
        cost=0.08,
        message="repair route selected",
    )


def human_gate_node(state: WorkflowState) -> NodeResult:
    if state.get("human_approved"):
        return NodeResult(
            updates={"human_gate": "approved", "outcome_ok": True},
            score=0.78,
            confidence=0.80,
            cost=0.0,
            message="human approved workflow continuation",
        )
    return NodeResult(
        updates={
            "human_gate": "waiting",
            "interrupt_reason": "workflow confidence below threshold or unsafe finish",
        },
        score=0.25,
        confidence=0.25,
        cost=0.0,
        interrupt=True,
        message="interrupted for human review",
    )


def finalize_node(state: WorkflowState) -> NodeResult:
    final = {
        "goal": state.goal,
        "selected_action": state.get("selected_action"),
        "execution_strategy": state.get("execution_strategy"),
        "outcome_ok": state.get("outcome_ok"),
        "repairs": state.get("repairs", 0),
    }
    return NodeResult(
        updates={"final_summary": final, "progress": "workflow_finished"},
        score=0.9 if state.get("outcome_ok", True) else 0.55,
        confidence=0.88 if state.get("outcome_ok", True) else 0.55,
        cost=0.01,
        message="workflow finalized",
    )


def build_project_workflow(*, checkpointer=None, policy: WorkflowPolicy | None = None):
    graph = AdaptiveWorkflowGraph()
    graph.add_node("inspect_context", inspect_context)
    graph.add_node("build_plan", build_plan_node)
    graph.add_node("choose_action", choose_action_node)
    graph.add_node("assess_similarity_collapse", assess_similarity_collapse_node)
    graph.add_node("rewind_blind_fanout", rewind_blind_fanout_node)
    graph.add_node("execution_dispatcher", execution_dispatcher_node)
    graph.add_node("fast_execute", fast_execute_node)
    graph.add_node("safe_execute", safe_execute_node)
    graph.add_node("evaluate_outcome", evaluate_outcome_node)
    graph.add_node("repair", repair_node)
    graph.add_node("human_gate", human_gate_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "inspect_context")
    graph.add_edge("inspect_context", "build_plan")
    graph.add_edge("build_plan", "choose_action")
    graph.add_edge("choose_action", "assess_similarity_collapse")
    graph.add_conditional_edges("assess_similarity_collapse", "collapse_route", route_similarity_collapse)
    graph.add_edge("rewind_blind_fanout", "choose_action")
    graph.add_conditional_edges("execution_dispatcher", "execution_strategy", route_execution_strategy)
    graph.add_edge("fast_execute", "evaluate_outcome")
    graph.add_edge("safe_execute", "evaluate_outcome")
    graph.add_conditional_edges("evaluate_outcome", "outcome_route", route_outcome)
    graph.add_edge("repair", "choose_action")
    graph.add_edge("human_gate", "finalize")
    graph.add_edge("finalize", "__end__")
    return graph.compile(checkpointer=checkpointer, policy=policy or default_workflow_policy())


def run_project_workflow_demo(goal: str = "优化项目并安全交付") -> WorkflowState:
    workflow = build_project_workflow(policy=default_workflow_policy())
    return workflow.invoke(
        goal,
        run_id="project-workflow-demo",
        initial_data={
            "files": ["agent/main.py", "agent/core/agent_loop.py", "tests/test_agent_loop.py"],
            "structure": {"package_files": ["pyproject.toml"], "entrypoints": ["agent/main.py"]},
        },
    )
