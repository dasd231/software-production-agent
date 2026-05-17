from __future__ import annotations

from pathlib import Path

from agent.core.executor import run_action
from agent.enterprise.readiness import build_enterprise_readiness_report


def test_enterprise_readiness_report_passes_current_baseline(tmp_path: Path) -> None:
    report = build_enterprise_readiness_report(tmp_path)

    assert report["schema"] == "enterprise_readiness_report.v1"
    assert report["summary"]["release_blocked"] is False
    assert report["summary"]["score"] == 100.0
    ids = {row["id"] for row in report["checks"]}
    assert "platform_api_asgi" in ids
    assert "model_serving_vllm" in ids
    assert "model_router_pools" in ids
    assert "model_admission_backpressure" in ids
    assert "distributed_execution_contract" in ids
    assert "third_party_embedding_fabric" in ids
    assert "network_policy" in ids
    assert "ci_gate" in ids


def test_enterprise_readiness_action_dispatches(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()

    out = run_action(ws, {"type": "action", "action": "enterprise_readiness_check", "args": {}})

    assert out["ok"] is True
    assert out["report"]["schema"] == "enterprise_readiness_report.v1"
    assert out["report"]["summary"]["release_blocked"] is False
