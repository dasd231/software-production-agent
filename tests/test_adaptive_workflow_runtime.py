from __future__ import annotations

from agent.workflow.checkpoint import InMemoryWorkflowCheckpointer
from agent.workflow.optimizer import WorkflowOptimizer
from agent.workflow.policy_store import PolicyRecord, PolicyStore
from agent.workflow.project_graph import build_project_workflow, default_workflow_policy
from agent.workflow.schema import WorkflowStatus


def test_project_workflow_runs_and_updates_decision_memory() -> None:
    checkpointer = InMemoryWorkflowCheckpointer()
    workflow = build_project_workflow(checkpointer=checkpointer, policy=default_workflow_policy())
    state = workflow.invoke(
        "优化项目并安全交付",
        run_id="wf-1",
        initial_data={"files": ["agent/main.py", "tests/test_main.py"]},
    )

    assert state.status == WorkflowStatus.SUCCEEDED
    assert state.get("decision_policy")
    assert state.get("decision_memory", {}).get("decision_count", 0) >= 1
    assert state.get("decision_trace", {}).get("reward_after_execution")
    assert checkpointer.list_events("wf-1")
    assert any(event.route_key == "execution_strategy" for event in checkpointer.list_events("wf-1"))
    assert any(event.route_key == "collapse_route" for event in checkpointer.list_events("wf-1"))


def test_project_workflow_routes_similarity_collapse_to_rewind() -> None:
    checkpointer = InMemoryWorkflowCheckpointer()
    workflow = build_project_workflow(checkpointer=checkpointer, policy=default_workflow_policy())
    state = workflow.invoke(
        "多智能体协作后安全交付",
        run_id="wf-collapse",
        initial_data={
            "files": ["agent/main.py", "tests/test_main.py"],
            "multi_agent_rationales": [
                "Use the same Kubernetes scheduler score plugin and CSI topology plan.",
                "Use the same Kubernetes scheduler score plugin and CSI topology plan.",
                "Use the same Kubernetes scheduler score plugin and CSI topology plan.",
            ],
            "multi_agent_evidence": [["k8s", "csi"], ["k8s", "csi"], ["k8s", "csi"]],
        },
    )

    assert state.status == WorkflowStatus.SUCCEEDED
    assert state.get("collapse_rewinds") == 1
    assert state.get("similarity_collapse_assessment", {})["alarm"] is True
    assert state.get("diversity_retention_decision", {})["retained_count"] >= 2
    assert any(
        event.route_key == "collapse_route" and event.route_choice == "rewind_blind_fanout"
        for event in checkpointer.list_events("wf-collapse")
    )


def test_project_workflow_can_interrupt_and_resume() -> None:
    checkpointer = InMemoryWorkflowCheckpointer()
    policy = default_workflow_policy()
    workflow = build_project_workflow(checkpointer=checkpointer, policy=policy)
    state = workflow.invoke(
        "直接交付但信心不足",
        run_id="wf-human",
        initial_data={"files": [], "structure": {}, "fast_path_success_bias": 0.0},
    )

    # Depending on policy route this may finish or interrupt. Force the project-level
    # human gate behavior by patching the state and resuming from human_gate.
    workflow.patch_state(
        "wf-human",
        {"current_node": "human_gate", "status": "interrupted", "human_approved": False},
    )
    interrupted = workflow.resume("wf-human")
    assert interrupted.status == WorkflowStatus.INTERRUPTED

    workflow.patch_state("wf-human", {"human_approved": True})
    resumed = workflow.resume("wf-human")
    assert resumed.status == WorkflowStatus.SUCCEEDED
    assert resumed.get("human_gate") == "approved"


def test_workflow_optimizer_proposes_policy() -> None:
    checkpointer = InMemoryWorkflowCheckpointer()
    policy = default_workflow_policy()
    policy.exploration_rate = 0.5
    workflow = build_project_workflow(checkpointer=checkpointer, policy=policy)
    for i in range(6):
        workflow.invoke(
            f"优化项目第 {i} 轮",
            run_id=f"wf-opt-{i}",
            initial_data={"files": ["agent/main.py", "tests/test_main.py"], "fast_path_success_bias": 0.3},
        )

    report = WorkflowOptimizer(min_samples_per_route=1).analyze(checkpointer.list_events(), policy)
    assert report.route_stats
    assert report.proposed_policy is not None
    assert "execution_strategy" in report.proposed_policy.route_weights


def test_policy_store_versioning(tmp_path) -> None:
    store = PolicyStore(tmp_path)
    policy = default_workflow_policy()
    store.save(PolicyRecord(version="v1", policy=policy, notes="baseline"), make_current=True)

    assert store.current() is not None
    assert store.current().version == "v1"
    assert store.load("v1").policy.max_steps == policy.max_steps
