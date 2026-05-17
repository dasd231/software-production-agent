from agent.core.agent_loop import _plan_summary


def test_plan_summary_with_priority_guidance() -> None:
    plan = {
        "stage": "investigate",
        "tasks": ["x"],
        "meta": {"recommended_next_actions": ["a", "b", "c", "d"]},
    }
    out = _plan_summary(plan)
    assert out["stage"] == "investigate"
    assert out["priority_guidance"] == ["a", "b", "c"]


def test_plan_summary_without_meta_recommendations() -> None:
    out = _plan_summary({"stage": "coding", "tasks": ["x"], "meta": {}})
    assert out == {"stage": "coding"}


def test_plan_summary_with_context_task_hints() -> None:
    out = _plan_summary(
        {
            "stage": "fixing",
            "tasks": [
                "根据 stderr 修复代码",
                "先参考 rag_hints 的相关片段，再决定最小改动范围",
                "优先按 skill_hints 执行: debugging",
                "优先使用 mcp 工具定位问题: workspace.search, workspace.read",
            ],
            "meta": {},
        }
    )
    assert out["stage"] == "fixing"
    assert out["context_hint_count"] == 3
    assert len(out["context_task_hints"]) == 3
