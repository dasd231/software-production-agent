from agent.context.budget import ContextSegment, build_context_budget_plan
from agent.scheduler.routing import build_model_route_plan


def test_context_budget_keeps_core_and_drops_low_priority() -> None:
    segments = [
        ContextSegment(
            source="system",
            role="system",
            text="必须遵守安全约束",
            must_keep=True,
        ),
        ContextSegment(
            source="user_input",
            role="user",
            text="请分析订单模块",
            must_keep=True,
        ),
        ContextSegment(
            source="old_history",
            role="assistant",
            text="很早以前的闲聊 " * 200,
        ),
        ContextSegment(
            source="rag",
            role="user",
            text="订单状态机和幂等键 " * 80,
            score=0.9,
        ),
        ContextSegment(
            source="tools",
            role="system",
            text="tool schema " * 300,
            score=0.2,
        ),
    ]

    plan = build_context_budget_plan(
        segments,
        goal="订单模块分析",
        model_max_context=900,
        max_output_tokens=180,
        safety_margin_tokens=80,
    )

    text = "\n".join(msg["content"] for msg in plan["messages"])
    assert plan["schema"] == "context_budget_plan.v1"
    assert "必须遵守安全约束" in text
    assert "请分析订单模块" in text
    assert "<!-- BEGIN EVIDENCE" in text
    assert plan["used_tokens"] <= plan["input_budget"]
    assert plan["compressed_segments"] or plan["dropped_segments"]


def test_context_budget_uses_route_pool_budget_for_long_context() -> None:
    route = build_model_route_plan(
        "长上下文RAG代码仓库分析",
        prompt="项目代码 " * 5000,
        max_output_tokens=2048,
    )
    segments = [
        {
            "source": "system",
            "role": "system",
            "text": "你是软件生产Agent",
            "must_keep": True,
        },
        {
            "source": "user_input",
            "role": "user",
            "text": "分析整个仓库",
            "must_keep": True,
        },
        {
            "source": "code",
            "role": "user",
            "text": "def service():\n    return 'ok'\n" * 900,
            "score": 0.95,
        },
        {
            "source": "rag",
            "role": "user",
            "text": "架构说明 " * 2000,
            "score": 0.8,
        },
    ]

    plan = build_context_budget_plan(segments, goal="仓库分析", route_plan=route)

    assert plan["route_plan"]["selected_pool"] == "long_pool"
    assert plan["route_plan"]["context_budget"]["strategy"] in {
        "semantic_pv_slice_budget",
        "aggressive_rerank_then_slice",
        "summarize_before_retrieval",
    }
    assert plan["messages"]
    assert plan["used_tokens"] <= plan["input_budget"] or plan["over_budget"] is True


def test_context_budget_escalates_when_even_core_is_too_large() -> None:
    plan = build_context_budget_plan(
        [
            ContextSegment(
                source="system",
                role="system",
                text="安全约束 " * 500,
                must_keep=True,
            ),
            ContextSegment(
                source="user_input",
                role="user",
                text="全文审查 " * 600,
                must_keep=True,
            ),
        ],
        model_max_context=320,
        max_output_tokens=120,
        safety_margin_tokens=80,
    )

    assert plan["over_budget"] is False or "task_split_or_map_reduce_required" in plan["escalation"]
    assert plan["compressed_segments"]
