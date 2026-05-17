from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.resources.registry import discover_resources
from agent.scheduler.admission import PoolAdmissionController
from agent.scheduler.routing import build_model_route_plan, estimate_tokens, list_model_pools


def test_estimate_tokens_handles_cjk_and_code() -> None:
    assert estimate_tokens("企业级长上下文RAG") >= 8
    assert estimate_tokens("def hello_world(): return 'ok'") >= 7
    assert estimate_tokens("") == 0


def test_short_request_uses_short_pool() -> None:
    plan = build_model_route_plan("写一个 /healthz 接口返回 ok", max_output_tokens=256)

    assert plan["schema"] == "model_route_plan.v1"
    assert plan["selected_pool"] == "short_pool"
    assert plan["admission"]["admitted"] is True
    assert plan["queue_policy"]["preemptible"] is True


def test_long_context_overflows_to_long_pool() -> None:
    prompt = "系统方案 " * 7000

    plan = build_model_route_plan("基于长上下文RAG生成企业架构方案", prompt=prompt, max_output_tokens=2048)

    assert plan["selected_pool"] == "long_pool"
    assert plan["queue_policy"]["lease_required"] is True
    assert plan["queue_policy"]["isolation"]["dedicated_queue"] is True


def test_agent_json_uses_agent_pool() -> None:
    plan = build_model_route_plan("多Agent工具调用状态机，要求JSON输出", require_json=True)

    assert plan["selected_pool"] == "agent_pool"
    assert plan["business_type"]["type"] == "agent_tooling"
    assert "tool_call_limits" in plan["pool"]["features"]


def test_training_uses_training_batch_pool() -> None:
    plan = build_model_route_plan("根据方案库生成SFT微调训练数据集", business_type="training")

    assert plan["selected_pool"] == "training_batch_pool"
    assert plan["queue_policy"]["preemption_policy"] == "checkpointable_low_priority"


def test_blocks_when_selected_pool_budget_is_exceeded() -> None:
    prompt = "工具调用 " * 40000

    plan = build_model_route_plan(
        "多Agent工具调用状态机",
        prompt=prompt,
        business_type="agent",
        max_output_tokens=2048,
    )

    assert plan["selected_pool"] == "agent_pool"
    assert plan["admission"]["admitted"] is False
    assert "summarize_or_chunk_context_before_model_call" in plan["admission"]["remediation"]


def test_model_pool_catalog_exposes_all_pools() -> None:
    catalog = list_model_pools()
    names = {pool["name"] for pool in catalog["pools"]}

    assert catalog["schema"] == "model_pool_catalog.v1"
    assert {"short_pool", "long_pool", "agent_pool", "training_batch_pool"} <= names


def test_resource_registry_exposes_model_pools(tmp_path: Path) -> None:
    registry = discover_resources(tmp_path, type_filter="model_pool")
    names = {row["name"] for row in registry["resources"]}

    assert registry["summary"]["by_type"]["model_pool"] == 4
    assert "long_pool" in names


def test_resource_registry_exposes_model_admission(tmp_path: Path) -> None:
    registry = discover_resources(tmp_path, type_filter="model_admission")

    assert registry["summary"]["by_type"]["model_admission"] == 1
    assert registry["resources"][0]["metadata"]["schema"] == "model_admission.v1"


def test_admission_controller_acquire_saturate_release() -> None:
    controller = PoolAdmissionController(limit_overrides={"short_pool": 1})

    first = controller.acquire("写一个 /healthz 接口", max_output_tokens=128, lease_ttl_s=10)
    second = controller.acquire("写一个 /readyz 接口", max_output_tokens=128, lease_ttl_s=10)

    assert first["admitted"] is True
    assert first["lease"]["pool"] == "short_pool"
    assert second["admitted"] is False
    assert second["reason"] == "pool_saturated"
    assert second["backpressure"]["http_status"] == 429

    released = controller.release(first["lease"]["lease_id"])
    third = controller.acquire("写一个 /metrics 接口", max_output_tokens=128, lease_ttl_s=10)

    assert released["released"] is True
    assert third["admitted"] is True


def test_admission_controller_idempotency_and_ttl_cleanup() -> None:
    now = {"value": 100.0}
    controller = PoolAdmissionController(clock=lambda: now["value"], limit_overrides={"short_pool": 1})

    first = controller.acquire("短API", max_output_tokens=128, idempotency_key="same", lease_ttl_s=5)
    replay = controller.acquire("短API", max_output_tokens=128, idempotency_key="same", lease_ttl_s=5)
    now["value"] = 106.0
    after_expiry = controller.acquire("短API", max_output_tokens=128, lease_ttl_s=5)

    assert first["admitted"] is True
    assert replay["reason"] == "idempotent_replay"
    assert replay["lease"]["lease_id"] == first["lease"]["lease_id"]
    assert after_expiry["admitted"] is True
    assert after_expiry["lease"]["lease_id"] != first["lease"]["lease_id"]


def test_admission_idempotent_replay_preserves_original_route_plan() -> None:
    controller = PoolAdmissionController(limit_overrides={"short_pool": 2, "long_pool": 2})

    first = controller.acquire("短API", max_output_tokens=128, idempotency_key="retry-key", lease_ttl_s=10)
    replay = controller.acquire(
        "长上下文RAG企业方案",
        prompt="方案 " * 7000,
        max_output_tokens=2048,
        idempotency_key="retry-key",
        lease_ttl_s=10,
    )

    assert first["route_plan"]["selected_pool"] == "short_pool"
    assert replay["reason"] == "idempotent_replay"
    assert replay["lease"]["lease_id"] == first["lease"]["lease_id"]
    assert replay["lease"]["pool"] == "short_pool"
    assert replay["route_plan"]["selected_pool"] == "short_pool"
    assert replay["pool_state"]["pool"] == "short_pool"


def test_model_route_plan_action_dispatches(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    out = run_action(
        ws,
        {
            "type": "action",
            "action": "model_route_plan",
            "args": {"goal": "长上下文RAG方案", "business_type": "long", "max_output_tokens": 2048},
        },
    )

    assert out["ok"] is True
    assert out["plan"]["selected_pool"] == "long_pool"


def test_model_admission_actions_dispatch(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    acquired = run_action(
        ws,
        {
            "type": "action",
            "action": "model_admission_acquire",
            "args": {"goal": "短API", "max_output_tokens": 128, "lease_ttl_s": 10},
        },
    )
    status = run_action(ws, {"type": "action", "action": "model_admission_status", "args": {}})
    released = run_action(
        ws,
        {
            "type": "action",
            "action": "model_admission_release",
            "args": {"lease_id": acquired["admission"]["lease"]["lease_id"]},
        },
    )

    assert acquired["ok"] is True
    assert acquired["admission"]["schema"] == "model_admission.v1"
    assert status["status"]["schema"] == "model_admission_status.v1"
    assert released["release"]["released"] is True
