from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from agent.platform.api import create_app


def test_platform_api_health_and_resources(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)

    health = client.get("/healthz")
    ready = client.get("/readyz")
    startup = client.get("/startupz")
    metrics = client.get("/metrics")
    resources = client.get("/api/resources?type=model_runtime")
    integrations = client.get("/api/integrations")
    figma_plan = client.post(
        "/api/integrations/embed-plan",
        json={
            "integration_id": "figma",
            "resource_url": "https://www.figma.com/file/abc123/Product-Design",
            "mode": "embed_panel",
            "requested_capabilities": ["frame_selection"],
        },
    )

    assert health.status_code == 200
    assert health.json()["service"] == "software-production-agent-platform"
    assert health.json()["schema"] == "app_health_snapshot.v1"
    assert ready.status_code == 200
    assert ready.json()["health"]["ready"] is True
    assert ready.json()["model_runtime"]["schema"] == "model_runtime_status.v1"
    assert ready.json()["model_admission"]["schema"] == "model_admission_status.v1"
    assert startup.status_code == 200
    assert startup.json()["startup_complete"] is True
    assert metrics.status_code == 200
    assert "agent_platform_up 1" in metrics.text
    assert resources.status_code == 200
    assert resources.json()["schema"] == "resource_registry.v1"
    assert integrations.status_code == 200
    assert integrations.json()["schema"] == "integration_catalog.v1"
    assert figma_plan.status_code == 200
    assert figma_plan.json()["schema"] == "integration_embed_plan.v1"
    assert figma_plan.json()["admission"]["embeddable"] is True


def test_platform_api_bearer_token_protects_control_endpoints(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_PLATFORM_API_TOKEN", "secret-token")
    app = create_app(tmp_path)
    client = TestClient(app)

    denied = client.get("/api/resources")
    allowed = client.get("/api/resources", headers={"Authorization": "Bearer secret-token"})

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_platform_api_enterprise_and_maturity(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)

    pools = client.get("/api/model-pools")
    route = client.post(
        "/api/model-route-plan",
        json={"goal": "长上下文RAG请求，要求JSON输出", "require_json": True, "max_output_tokens": 1200},
    )
    admission_status = client.get("/api/model-admission/status")
    admission = client.post(
        "/api/model-admission/acquire",
        json={"goal": "短API请求", "max_output_tokens": 256, "idempotency_key": "platform-test"},
    )
    enterprise = client.post(
        "/api/enterprise-stack",
        json={"goal": "上市企业私有化平台，vLLM模型服务，100+终端", "scale": "listed", "regulated": True},
    )
    maturity = client.post(
        "/api/industrial-maturity",
        json={"goal": "工业AI CTO成熟度", "scale": "listed", "regulated": True},
    )
    readiness = client.get("/api/enterprise-readiness")

    assert pools.status_code == 200
    assert pools.json()["schema"] == "model_pool_catalog.v1"
    assert route.status_code == 200
    assert route.json()["schema"] == "model_route_plan.v1"
    assert route.json()["selected_pool"] == "agent_pool"
    assert admission_status.status_code == 200
    assert admission_status.json()["schema"] == "model_admission_status.v1"
    assert admission.status_code == 200
    assert admission.json()["schema"] == "model_admission.v1"
    assert admission.json()["admitted"] is True
    renew = client.post(
        "/api/model-admission/renew",
        json={"lease_id": admission.json()["lease"]["lease_id"], "lease_ttl_s": 30},
    )
    assert renew.status_code == 200
    assert renew.json()["schema"] == "model_admission_renewal.v1"
    assert renew.json()["renewed"] is True
    assert renew.json()["lease_id"] == admission.json()["lease"]["lease_id"]
    usage = client.post(
        "/api/model-admission/usage",
        json={
            "lease_id": admission.json()["lease"]["lease_id"],
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "metadata": {"provider": "main_deepseek"},
        },
    )
    assert usage.status_code == 200
    assert usage.json()["schema"] == "model_usage_record.v1"
    assert usage.json()["record"]["total_tokens"] == 140
    release = client.post(
        "/api/model-admission/release",
        json={"lease_id": admission.json()["lease"]["lease_id"]},
    )
    assert release.status_code == 200
    assert release.json()["released"] is True
    assert enterprise.status_code == 200
    assert enterprise.json()["schema"] == "enterprise_stack_plan.v1"
    assert maturity.status_code == 200
    assert maturity.json()["schema"] == "industrial_maturity_plan.v1"
    assert readiness.status_code == 200
    assert readiness.json()["schema"] == "enterprise_readiness_report.v1"


def test_platform_api_model_admission_returns_429_when_pool_saturated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_SHORT_POOL_MAX_CONCURRENCY", "1")
    app = create_app(tmp_path)
    client = TestClient(app)

    first = client.post(
        "/api/model-admission/acquire",
        json={"goal": "短API请求", "max_output_tokens": 128, "lease_ttl_s": 30},
    )
    second = client.post(
        "/api/model-admission/acquire",
        json={"goal": "另一个短API请求", "max_output_tokens": 128, "lease_ttl_s": 30},
    )

    assert first.status_code == 200
    assert first.json()["admitted"] is True
    assert second.status_code == 429
    assert second.json()["reason"] == "pool_saturated"

    release = client.post("/api/model-admission/release", json={"lease_id": first.json()["lease"]["lease_id"]})
    assert release.status_code == 200
    assert release.json()["released"] is True


def test_platform_api_intent_workflow_and_evidence(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)

    compiled = client.post("/api/intent/compile", json={"goal": "构建企业级平台并沉淀方案资产"})
    dry_run = client.post(
        "/api/workflow/dry-run",
        json={"spec": {"schema": "workflow.v1", "version": "demo", "nodes": ["research"], "edges": []}},
    )
    ledger = client.post("/api/evidence-ledger", json={"write": False})

    assert compiled.status_code == 200
    assert compiled.json()["schema"] == "intent_compilation.v1"
    assert dry_run.status_code == 200
    assert dry_run.json()["schema"] == "workflow_dry_run.v1"
    assert ledger.status_code == 200
    assert ledger.json()["schema"] == "evidence_ledger.v1"
