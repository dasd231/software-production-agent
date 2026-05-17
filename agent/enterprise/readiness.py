"""Enterprise readiness checks for production-grade development."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _exists(rel: str) -> bool:
    return (_project_root() / rel).exists()


def _finding(
    id: str,
    title: str,
    ok: bool,
    *,
    severity: str,
    evidence: list[str],
    remediation: str,
    warn: bool = False,
) -> dict[str, Any]:
    return {
        "id": id,
        "title": title,
        "status": "warn" if warn and ok else "pass" if ok else "fail",
        "severity": severity,
        "evidence": evidence,
        "remediation": remediation,
    }


def _contains(path: str, *needles: str) -> bool:
    text = _read(_project_root() / path).lower()
    return all(needle.lower() in text for needle in needles)


def _not_contains(path: str, *needles: str) -> bool:
    text = _read(_project_root() / path).lower()
    return all(needle.lower() not in text for needle in needles)


def _checks() -> list[dict[str, Any]]:
    dockerfile = "deploy/production/Dockerfile.platform"
    compose = "deploy/production/docker-compose.yml"
    platform_k8s = "deploy/production/k8s/platform-api.yaml"
    model_k8s = "deploy/production/k8s/model-vllm.yaml"
    model_pools_k8s = "deploy/production/k8s/model-pools.yaml"
    return [
        _finding(
            "platform_api_asgi",
            "Production API uses FastAPI/ASGI instead of Flask",
            _contains("agent/platform/api.py", "fastapi", "create_app") and _not_contains("agent/platform/api.py", "from flask"),
            severity="critical",
            evidence=["agent/platform/api.py"],
            remediation="Keep production control-plane APIs in FastAPI/ASGI; Flask is local UI only.",
        ),
        _finding(
            "platform_process_model",
            "Platform container uses Gunicorn/Uvicorn workers",
            _contains(dockerfile, "gunicorn", "uvicorn.workers.uvicornworker", "agent.platform.api:app"),
            severity="critical",
            evidence=[dockerfile],
            remediation="Run platform API with Gunicorn + UvicornWorker and tune workers/timeouts per load test.",
        ),
        _finding(
            "no_flask_or_ollama_in_prod_deploy",
            "Production deployment avoids Flask and Ollama",
            _not_contains(dockerfile, "flask", "ollama") and _not_contains(compose, "ollama"),
            severity="critical",
            evidence=[dockerfile, compose],
            remediation="Keep Flask/Ollama out of production deployment files; use FastAPI and vLLM/SGLang.",
        ),
        _finding(
            "model_serving_vllm",
            "Model runtime is vLLM/OpenAI-compatible",
            _contains(compose, "vllm-openai") and _contains(model_k8s, "vllm-openai", "nvidia.com/gpu"),
            severity="critical",
            evidence=[compose, model_k8s],
            remediation="Use vLLM/SGLang model services behind the OpenAI-compatible model gateway.",
        ),
        _finding(
            "model_router_pools",
            "Model router separates short, long, agent and training pools",
            _contains(
                "agent/scheduler/routing.py",
                "build_model_route_plan",
                "short_pool",
                "long_pool",
                "agent_pool",
                "training_batch_pool",
            )
            and _contains("agent/platform/api.py", "/api/model-route-plan", "/api/model-pools")
            and _contains(model_pools_k8s, "model-vllm-short", "model-vllm-long", "--enable-chunked-prefill"),
            severity="critical",
            evidence=["agent/scheduler/routing.py", "agent/platform/api.py", model_pools_k8s],
            remediation="Keep token estimation and pool admission as a first-class Model Plane gate.",
        ),
        _finding(
            "model_admission_backpressure",
            "Model admission control enforces leases and backpressure",
            _contains(
                "agent/scheduler/admission.py",
                "PoolAdmissionController",
                "lease",
                "pool_saturated",
                "backpressure",
            )
            and _contains("agent/platform/api.py", "/api/model-admission/acquire", "/api/model-admission/status")
            and _contains("agent/resources/registry.py", "model_admission"),
            severity="critical",
            evidence=["agent/scheduler/admission.py", "agent/platform/api.py", "agent/resources/registry.py"],
            remediation="Put every model request through lease admission before forwarding to model runtimes.",
        ),
        _finding(
            "distributed_execution_contract",
            "Distributed execution contract exists without forcing cluster startup",
            _contains(
                "agent/distributed/backends.py",
                "RayClusterBackend",
                "contract_only",
                "control-plane manifests remain authoritative",
            )
            and _contains("agent/training/execution_profiles.py", "ray_cluster_default", "ray_jobs"),
            severity="high",
            evidence=["agent/distributed/backends.py", "agent/training/execution_profiles.py"],
            remediation="Keep distributed backends contract-first and ensure Ray remains an execution substrate, not the control plane.",
        ),
        _finding(
            "third_party_embedding_fabric",
            "Third-party embedded integration fabric exists",
            _contains(
                "agent/integrations/embedding.py",
                "IntegrationManifest",
                "integration_embed_plan.v1",
                "allowed_origins",
                "bridge_contract",
            )
            and _contains("agent/platform/api.py", "/api/integrations", "/api/integrations/embed-plan")
            and _contains("agent/resources/registry.py", "integration")
            and _exists("docs/THIRD_PARTY_EMBEDDING.md"),
            severity="high",
            evidence=[
                "agent/integrations/embedding.py",
                "agent/platform/api.py",
                "agent/resources/registry.py",
                "docs/THIRD_PARTY_EMBEDDING.md",
            ],
            remediation="Keep third-party embeds behind manifest, origin, sandbox, bridge and artifact-mapping gates.",
        ),
        _finding(
            "no_latest_images",
            "Production manifests avoid latest tags",
            _not_contains(compose, ":latest") and _not_contains(model_k8s, ":latest") and _not_contains(dockerfile, ":latest"),
            severity="high",
            evidence=[dockerfile, compose, model_k8s],
            remediation="Pin container images to immutable versions or digests before release.",
        ),
        _finding(
            "k8s_health_and_resources",
            "Kubernetes manifests define probes and resource limits",
            _contains(platform_k8s, "readinessprobe", "livenessprobe", "resources")
            and _contains(model_k8s, "readinessprobe", "livenessprobe", "resources"),
            severity="high",
            evidence=[platform_k8s, model_k8s],
            remediation="Every service must define readiness, liveness, requests and limits.",
        ),
        _finding(
            "autoscaling_and_disruption",
            "HPA and PodDisruptionBudget exist",
            _exists("deploy/production/k8s/hpa.yaml") and _exists("deploy/production/k8s/pdb.yaml"),
            severity="high",
            evidence=["deploy/production/k8s/hpa.yaml", "deploy/production/k8s/pdb.yaml"],
            remediation="Add HPA for platform services and PDB for high availability during node disruption.",
        ),
        _finding(
            "network_policy",
            "Kubernetes NetworkPolicy baseline exists",
            _exists("deploy/production/k8s/network-policy.yaml"),
            severity="high",
            evidence=["deploy/production/k8s/network-policy.yaml"],
            remediation="Add default ingress/egress constraints and explicitly allow platform/model traffic.",
        ),
        _finding(
            "ci_gate",
            "CI workflow exists for tests and deployment lint",
            _exists(".github/workflows/ci.yml"),
            severity="high",
            evidence=[".github/workflows/ci.yml"],
            remediation="Add CI for pytest, compile checks and production deployment static gates.",
        ),
        _finding(
            "go_live_docs",
            "Go-live and maturity documents exist",
            _exists("docs/PRODUCTION_GO_LIVE.md")
            and _exists("docs/INDUSTRIAL_AI_CTO_MATURITY.md")
            and _exists("docs/ENTERPRISE_LANDING.md"),
            severity="medium",
            evidence=["docs/PRODUCTION_GO_LIVE.md", "docs/INDUSTRIAL_AI_CTO_MATURITY.md", "docs/ENTERPRISE_LANDING.md"],
            remediation="Keep docs synced with real deployment gates and ownership.",
        ),
    ]


def build_enterprise_readiness_report(workspace: Path | None = None) -> dict[str, Any]:
    checks = _checks()
    counts: dict[str, int] = {"pass": 0, "warn": 0, "fail": 0}
    for row in checks:
        counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
    total = len(checks)
    score = ((counts.get("pass", 0) + counts.get("warn", 0) * 0.5) / max(total, 1)) * 100.0
    blockers = [row for row in checks if row["status"] == "fail" and row["severity"] in {"critical", "high"}]
    return {
        "schema": "enterprise_readiness_report.v1",
        "workspace": str((workspace or _project_root()).resolve()),
        "project_root": str(_project_root()),
        "summary": {
            "score": round(score, 1),
            "total": total,
            "by_status": counts,
            "release_blocked": bool(blockers),
            "blockers": [row["id"] for row in blockers],
        },
        "checks": checks,
        "next_remediation": [row["remediation"] for row in blockers[:5]],
    }
