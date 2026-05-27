from __future__ import annotations

from agent.workflow.checkpoint import InMemoryWorkflowCheckpointer
from agent.workflow.runtime import AdaptiveWorkflowGraph
from agent.workflow.schema import START, NodeResult, WorkflowPolicy, WorkflowStatus


def test_workflow_runtime_records_skill_bundle_and_guard_report_when_enabled() -> None:
    checkpointer = InMemoryWorkflowCheckpointer()
    graph = AdaptiveWorkflowGraph()

    def node(state):
        return NodeResult(
            updates={"answer": "ok", "evidence": [{"evidence_id": "ev:1", "summary": "checked"}]},
            score=0.8,
            confidence=0.8,
            message="node completed with evidence summary",
        )

    graph.add_node("guarded_node", node)
    graph.add_edge(START, "guarded_node")
    graph.add_edge("guarded_node", "__end__")
    policy = WorkflowPolicy(
        max_steps=4,
        skill_runtime_enabled=True,
        skill_required_skill_ids={"guarded_node": ("skill.reasoning_brief",)},
        skill_explicit_scope={"guarded_node": ("evidence summary", "workflow node")},
    )
    workflow = graph.compile(checkpointer=checkpointer, policy=policy)
    state = workflow.invoke("执行前先获取 SkillBundle", run_id="skill-wf")

    assert state.status == WorkflowStatus.SUCCEEDED
    events = checkpointer.list_events("skill-wf")
    assert events
    metadata = events[0].metadata
    assert metadata["skill_runtime_enabled"] is True
    assert metadata["skill_bundle"]["schema"] == "skill_bundle.v1"
    assert metadata["skill_guard_report"]["ok"] is True
    skill_ids = {item["skill_id"] for item in metadata["skill_bundle"]["selected_skills"]}
    assert "skill.reasoning_brief" in skill_ids


def test_workflow_runtime_fails_closed_on_skill_guard_violation() -> None:
    checkpointer = InMemoryWorkflowCheckpointer()
    graph = AdaptiveWorkflowGraph()

    def bad_node(state):
        return NodeResult(
            updates={"plan": "kubectl apply production && rm -rf old && finetune model"},
            score=0.4,
            confidence=0.4,
            message="chain of thought: I will deploy, delete, then train",
        )

    graph.add_node("bad_node", bad_node)
    graph.add_edge(START, "bad_node")
    graph.add_edge("bad_node", "__end__")
    policy = WorkflowPolicy(
        max_steps=4,
        skill_runtime_enabled=True,
        skill_fail_closed=True,
        skill_explicit_scope={"bad_node": ("local planning only",)},
    )
    workflow = graph.compile(checkpointer=checkpointer, policy=policy)
    state = workflow.invoke("只做本地计划，不部署不训练不删除", run_id="skill-wf-bad")

    assert state.status == WorkflowStatus.FAILED
    assert state.error and "skill_guard_failed" in state.error
    event = checkpointer.list_events("skill-wf-bad")[0]
    assert event.status == "error"
    codes = {v["code"] for v in event.metadata["skill_guard_report"]["violations"]}
    assert "HIDDEN_COT_EXPOSED_OR_REQUESTED" in codes
    assert "UNAUTHORIZED_DEPLOY" in codes
    assert "UNAUTHORIZED_DELETE" in codes
    assert "UNAUTHORIZED_TRAIN" in codes
