"""Production ASGI platform gateway.

This module is intentionally separate from the Flask product UI. Flask stays a
local operator interface; this FastAPI app is the production control-plane API.
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any

from agent.enterprise.maturity import build_industrial_maturity_plan
from agent.enterprise.readiness import build_enterprise_readiness_report
from agent.enterprise.stack import build_enterprise_stack_plan
from agent.evidence.ledger import build_evidence_ledger
from agent.intent.compiler import compile_intent
from agent.integrations.embedding import build_integration_embed_plan, list_integration_catalog
from agent.llm.runtime import model_runtime_status
from agent.operations import evaluate_health_checks
from agent.resources.registry import discover_resources
from agent.scheduler.admission import PoolAdmissionController
from agent.scheduler.routing import build_model_route_plan, list_model_pools
from agent.workflows.dry_run import dry_run_workflow

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only in missing optional dep envs.
    raise RuntimeError("Production platform API requires fastapi: pip install fastapi uvicorn") from exc

from agent.security.jwt_auth import JWTAuthError, extract_bearer_token, verify_jwt


DEFAULT_RUNS_ROOT = Path(os.environ.get("AGENT_RUNS_ROOT", "product_runs"))


class IntentRequest(BaseModel):
    goal: str
    roots: list[str] = Field(default_factory=list)


class WorkflowDryRunRequest(BaseModel):
    spec: dict[str, Any]


class EnterpriseStackRequest(BaseModel):
    goal: str
    scale: str = ""
    regulated: bool = False
    provider: str = "main_deepseek"


class IndustrialMaturityRequest(BaseModel):
    goal: str
    scale: str = "listed"
    regulated: bool = True
    provider: str = "main_deepseek"


class EvidenceLedgerRequest(BaseModel):
    roots: list[str] = Field(default_factory=list)
    write: bool = False
    output_path: str = "evidence_ledger.json"


class ModelRouteRequest(BaseModel):
    goal: str
    prompt: str = ""
    business_type: str = ""
    require_json: bool = False
    max_output_tokens: int | None = Field(default=None, ge=1)


class ModelAdmissionRequest(ModelRouteRequest):
    idempotency_key: str = ""
    lease_ttl_s: float | None = Field(default=None, gt=0)


class ModelLeaseRequest(BaseModel):
    lease_id: str
    lease_ttl_s: float | None = Field(default=None, gt=0)


class IntegrationEmbedRequest(BaseModel):
    integration_id: str
    resource_url: str = ""
    mode: str = "embed_panel"
    workspace_context: str = ""
    requested_capabilities: list[str] = Field(default_factory=list)


def _root(app: FastAPI) -> Path:
    return Path(app.state.runs_root).resolve()


def _paths(raw: list[str]) -> tuple[Path, ...]:
    return tuple(Path(x) for x in raw if str(x).strip())


def _timed_check(name: str, *, critical: bool, timeout_ms: float, fn: Any) -> dict[str, Any]:
    started = time.perf_counter()
    detail = ""
    try:
        ok = bool(fn())
    except Exception as exc:  # pragma: no cover - defensive health reporting.
        ok = False
        detail = f"{type(exc).__name__}: {exc}"[:300]
    return {
        "name": name,
        "ok": ok,
        "critical": critical,
        "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "timeout_ms": timeout_ms,
        "detail": detail,
    }


def _platform_health_snapshot(app: FastAPI, *, include_dependencies: bool) -> dict[str, Any]:
    root = _root(app)
    checks: list[dict[str, Any]] = [
        _timed_check("process", critical=True, timeout_ms=50, fn=lambda: True),
    ]
    if include_dependencies:
        runtime = model_runtime_status("main_deepseek", probe=False)
        admission = app.state.model_admission.snapshot()
        checks.extend(
            [
                _timed_check("workspace_fs", critical=True, timeout_ms=100, fn=lambda: root.exists() and root.is_dir()),
                _timed_check("event_log_writer", critical=True, timeout_ms=100, fn=lambda: root.exists() and os.access(root, os.W_OK)),
                _timed_check("model_router", critical=False, timeout_ms=500, fn=lambda: runtime.get("schema") == "model_runtime_status.v1"),
                _timed_check("model_admission", critical=True, timeout_ms=100, fn=lambda: admission.get("schema") == "model_admission_status.v1"),
                _timed_check("resource_registry", critical=False, timeout_ms=300, fn=lambda: True),
            ]
        )
    snapshot = evaluate_health_checks(checks)
    snapshot["service"] = "software-production-agent-platform"
    snapshot["runs_root"] = str(root)
    return snapshot


def _prometheus_metrics(app: FastAPI) -> str:
    admission = app.state.model_admission.snapshot()
    lines = [
        "# HELP agent_platform_up Platform process liveness.",
        "# TYPE agent_platform_up gauge",
        "agent_platform_up 1",
        "# HELP agent_model_admission_leases Active model-pool leases.",
        "# TYPE agent_model_admission_leases gauge",
        f"agent_model_admission_leases {int(admission.get('leases_total', 0))}",
        "# HELP agent_model_pool_active_leases Active leases by model pool.",
        "# TYPE agent_model_pool_active_leases gauge",
    ]
    for pool in admission.get("pools", []):
        name = str(pool.get("pool", "unknown")).replace('"', "")
        lines.append(f'agent_model_pool_active_leases{{pool="{name}"}} {int(pool.get("active_leases", 0))}')
    return "\n".join(lines) + "\n"


def _jwt_allowed_algorithms() -> tuple[str, ...]:
    raw = os.environ.get("AGENT_PLATFORM_JWT_ALGORITHMS", "HS256")
    algorithms = tuple(part.strip() for part in raw.split(",") if part.strip())
    return algorithms or ("HS256",)


def _auth_dependency(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any] | None:
    """Authenticate protected control-plane APIs.

    Backward compatibility:
    - ``AGENT_PLATFORM_API_TOKEN`` keeps the old opaque Bearer token path.

    Production path:
    - ``AGENT_PLATFORM_JWT_SECRET`` enables signed JWT verification.
    - Verified identity is attached to ``request.state.identity``.
    """

    request.state.identity = None
    expected = os.environ.get("AGENT_PLATFORM_API_TOKEN", "").strip()
    jwt_secret = os.environ.get("AGENT_PLATFORM_JWT_SECRET", "").strip()
    if not expected and not jwt_secret:
        return None

    if expected and authorization == f"Bearer {expected}":
        identity = {
            "auth_type": "static_bearer",
            "user_id": "platform-token",
            "tenant_id": "platform",
            "role": "admin",
            "permissions": ["platform:*"],
        }
        request.state.identity = identity
        return identity

    if jwt_secret:
        try:
            token = extract_bearer_token(authorization)
            identity_obj = verify_jwt(
                token,
                secret=jwt_secret,
                issuer=os.environ.get("AGENT_PLATFORM_JWT_ISSUER", "software-production-agent"),
                audience=os.environ.get("AGENT_PLATFORM_JWT_AUDIENCE", "software-production-agent-platform"),
                allowed_algorithms=_jwt_allowed_algorithms(),
                leeway_s=int(os.environ.get("AGENT_PLATFORM_JWT_LEEWAY_S", "30")),
            )
        except JWTAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        identity = identity_obj.to_dict()
        identity["auth_type"] = "jwt"
        request.state.identity = identity
        return identity

    raise HTTPException(status_code=401, detail="invalid bearer token")


def create_app(runs_root: Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Software Production Agent Platform API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.runs_root = str((runs_root or DEFAULT_RUNS_ROOT).resolve())
    app.state.model_admission = PoolAdmissionController()

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        snapshot = _platform_health_snapshot(app, include_dependencies=False)
        return {"ok": snapshot["live"], **snapshot}

    @app.get("/readyz")
    def readyz(response: Response) -> dict[str, Any]:
        root = _root(app)
        snapshot = _platform_health_snapshot(app, include_dependencies=True)
        if not bool(snapshot.get("ready")):
            response.status_code = 503
        return {
            "ok": snapshot["ready"],
            "health": snapshot,
            "runs_root": str(root),
            "model_runtime": model_runtime_status("main_deepseek", probe=False),
            "model_admission": app.state.model_admission.snapshot(),
        }

    @app.get("/startupz")
    def startupz(response: Response) -> dict[str, Any]:
        snapshot = _platform_health_snapshot(app, include_dependencies=True)
        if not bool(snapshot.get("startup_complete")):
            response.status_code = 503
        return {"ok": snapshot["startup_complete"], **snapshot}

    @app.get("/metrics")
    def metrics() -> Response:
        return Response(content=_prometheus_metrics(app), media_type="text/plain; version=0.0.4")

    @app.get("/api/resources")
    def api_resources(
        type: str = Query(default=""),
        _: None = Depends(_auth_dependency),
    ) -> dict[str, Any]:
        return discover_resources(_root(app), type_filter=type)

    @app.get("/api/auth/me")
    def api_auth_me(request: Request, _: dict[str, Any] | None = Depends(_auth_dependency)) -> dict[str, Any]:
        return {
            "schema": "platform_identity.v1",
            "authenticated": bool(getattr(request.state, "identity", None)),
            "identity": getattr(request.state, "identity", None),
        }

    @app.get("/api/integrations")
    def api_integrations(
        category: str = Query(default=""),
        _: None = Depends(_auth_dependency),
    ) -> dict[str, Any]:
        return list_integration_catalog(category)

    @app.post("/api/integrations/embed-plan")
    def api_integration_embed_plan(
        payload: IntegrationEmbedRequest,
        response: Response,
        _: None = Depends(_auth_dependency),
    ) -> dict[str, Any]:
        plan = build_integration_embed_plan(
            payload.integration_id,
            resource_url=payload.resource_url,
            mode=payload.mode,
            workspace_context=payload.workspace_context,
            requested_capabilities=tuple(payload.requested_capabilities),
        )
        if not bool(plan.get("admission", {}).get("embeddable")):
            response.status_code = 400
        return plan

    @app.get("/api/model-runtime")
    def api_model_runtime(
        provider: str = Query(default="main_deepseek"),
        model: str = Query(default=""),
        probe: bool = Query(default=True),
        timeout: float = Query(default=2.0),
        _: None = Depends(_auth_dependency),
    ) -> dict[str, Any]:
        return model_runtime_status(provider, model or None, probe=probe, timeout=max(float(timeout), 0.1))

    @app.get("/api/model-pools")
    def api_model_pools(_: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return list_model_pools()

    @app.post("/api/model-route-plan")
    def api_model_route_plan(payload: ModelRouteRequest, _: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return build_model_route_plan(
            payload.goal,
            payload.prompt,
            max_output_tokens=payload.max_output_tokens,
            business_type=payload.business_type,
            require_json=payload.require_json,
        )

    @app.get("/api/model-admission/status")
    def api_model_admission_status(_: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return app.state.model_admission.snapshot()

    @app.post("/api/model-admission/acquire")
    def api_model_admission_acquire(
        payload: ModelAdmissionRequest,
        response: Response,
        _: None = Depends(_auth_dependency),
    ) -> dict[str, Any]:
        admission = app.state.model_admission.acquire(
            payload.goal,
            payload.prompt,
            max_output_tokens=payload.max_output_tokens,
            business_type=payload.business_type,
            require_json=payload.require_json,
            idempotency_key=payload.idempotency_key,
            lease_ttl_s=payload.lease_ttl_s,
            metadata={"source": "platform_api"},
        )
        if not bool(admission.get("admitted")):
            response.status_code = int(admission.get("backpressure", {}).get("http_status", 429))
        return admission

    @app.post("/api/model-admission/release")
    def api_model_admission_release(payload: ModelLeaseRequest, _: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return app.state.model_admission.release(payload.lease_id)

    @app.post("/api/model-admission/renew")
    def api_model_admission_renew(payload: ModelLeaseRequest, _: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return app.state.model_admission.renew(payload.lease_id, lease_ttl_s=payload.lease_ttl_s)

    @app.post("/api/intent/compile")
    def api_intent_compile(payload: IntentRequest, _: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return compile_intent(payload.goal, _root(app), roots=_paths(payload.roots))

    @app.post("/api/workflow/dry-run")
    def api_workflow_dry_run(payload: WorkflowDryRunRequest, _: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return dry_run_workflow(payload.spec, _root(app))

    @app.post("/api/enterprise-stack")
    def api_enterprise_stack(payload: EnterpriseStackRequest, _: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return build_enterprise_stack_plan(
            payload.goal,
            _root(app),
            scale=payload.scale,
            regulated=payload.regulated,
            provider=payload.provider,
        )

    @app.post("/api/industrial-maturity")
    def api_industrial_maturity(
        payload: IndustrialMaturityRequest,
        _: None = Depends(_auth_dependency),
    ) -> dict[str, Any]:
        return build_industrial_maturity_plan(
            payload.goal,
            _root(app),
            scale=payload.scale,
            regulated=payload.regulated,
            provider=payload.provider,
        )

    @app.get("/api/enterprise-readiness")
    def api_enterprise_readiness(_: None = Depends(_auth_dependency)) -> dict[str, Any]:
        return build_enterprise_readiness_report(_root(app))

    @app.post("/api/evidence-ledger")
    def api_evidence_ledger(payload: EvidenceLedgerRequest, _: None = Depends(_auth_dependency)) -> dict[str, Any]:
        root = _root(app)
        output = (root / payload.output_path).resolve() if payload.write else None
        if output and not output.is_relative_to(root):
            raise HTTPException(status_code=400, detail="output_path must stay inside runs_root")
        return build_evidence_ledger(root, roots=_paths(payload.roots), write_path=output)

    return app


app = create_app()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the production ASGI platform API")
    parser.add_argument("--host", default=os.environ.get("AGENT_PLATFORM_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AGENT_PLATFORM_PORT", "8080")))
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--workers", type=int, default=int(os.environ.get("AGENT_PLATFORM_WORKERS", "1")))
    args = parser.parse_args()
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Production platform API requires uvicorn: pip install uvicorn") from exc
    os.environ["AGENT_RUNS_ROOT"] = str(args.runs_root.resolve())
    target: str | FastAPI = "agent.platform.api:app" if int(args.workers) > 1 else create_app(args.runs_root)
    uvicorn.run(
        target,
        host=args.host,
        port=int(args.port),
        workers=max(int(args.workers), 1),
        log_level=os.environ.get("AGENT_PLATFORM_LOG_LEVEL", "info"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
