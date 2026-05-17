from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_platform_dockerfile_uses_asgi_not_flask() -> None:
    text = _read("deploy/production/Dockerfile.platform")

    assert "gunicorn" in text
    assert "uvicorn.workers.UvicornWorker" in text
    assert "agent.platform.api:app" in text
    assert "flask" not in text.lower()
    assert "ollama" not in text.lower()


def test_production_compose_uses_vllm_profile_not_ollama() -> None:
    text = _read("deploy/production/docker-compose.yml")

    assert "vllm/vllm-openai" in text
    assert "model-vllm" in text
    assert "MAIN_DEEPSEEK_BASE_URL" in text
    assert "MODEL_ADMISSION_BACKEND" in text
    assert "MODEL_SHORT_POOL_MAX_CONCURRENCY" in text
    assert ":latest" not in text
    assert "ollama" not in text.lower()


def test_kubernetes_manifests_include_platform_and_model_runtime() -> None:
    platform = _read("deploy/production/k8s/platform-api.yaml")
    model = _read("deploy/production/k8s/model-vllm.yaml")
    pools = _read("deploy/production/k8s/model-pools.yaml")
    hpa = _read("deploy/production/k8s/hpa.yaml")

    assert "kind: Deployment" in platform
    assert "path: /readyz" in platform
    assert "registry.example.com/software-production-agent/platform-api" in platform
    assert "vllm/vllm-openai" in model
    assert "nvidia.com/gpu" in model
    assert ":latest" not in model
    assert "model-vllm-short" in pools
    assert "model-vllm-long" in pools
    assert "--enable-chunked-prefill" in pools
    assert ":latest" not in pools
    assert "HorizontalPodAutoscaler" in hpa
    assert "model-vllm-short" in hpa


def test_enterprise_k8s_baseline_has_pdb_and_network_policy() -> None:
    pdb = _read("deploy/production/k8s/pdb.yaml")
    network = _read("deploy/production/k8s/network-policy.yaml")

    assert "PodDisruptionBudget" in pdb
    assert "NetworkPolicy" in network
    assert "model-vllm" in network
