"""Model runtime status and health probing for OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from agent.llm.providers import LLMProvider, resolve_llm_provider


@dataclass(frozen=True)
class ModelRuntimeStatus:
    schema: str
    provider: str
    label: str
    model: str
    base_url: str
    api_key_env: str
    api_key_required: bool
    api_key_present: bool
    local_endpoint: bool
    serving_hint: str
    probe: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_local_endpoint(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"} or host.startswith("192.168.") or host.startswith("10.")


def _health_url(base_url: str) -> str:
    if not base_url:
        return ""
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    root = parsed._replace(path=path or "", params="", query="", fragment="").geturl().rstrip("/")
    return f"{root}/health"


def _models_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/models" if base_url else ""


def _serving_hint(provider: LLMProvider) -> str:
    base_url = provider.base_url or ""
    if provider.name == "main_deepseek" and _is_local_endpoint(base_url):
        return "local_openai_compatible"
    if provider.base_url:
        return "remote_openai_compatible"
    return "openai_sdk_default"


def _http_json(url: str, *, api_key: str, timeout: float) -> tuple[int, dict[str, Any]]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read(256_000).decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"raw": body[:1000]}
        return int(resp.status), payload if isinstance(payload, dict) else {"data": payload}


def _probe(provider: LLMProvider, *, timeout: float) -> dict[str, Any]:
    base_url = provider.base_url or ""
    if not base_url:
        return {"ok": False, "checked": False, "error": "provider has no base_url"}
    api_key = os.environ.get(provider.api_key_env, "").strip()
    if not api_key and not provider.api_key_required:
        api_key = "local-deepseek"
    started = time.perf_counter()
    out: dict[str, Any] = {
        "ok": False,
        "checked": True,
        "health_url": _health_url(base_url),
        "models_url": _models_url(base_url),
    }
    try:
        health_status, health = _http_json(out["health_url"], api_key=api_key, timeout=timeout)
        out["health_status"] = health_status
        out["health"] = health
        out["ok"] = 200 <= health_status < 300 and bool(health.get("ok", True))
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        out["health_error"] = f"{type(exc).__name__}: {exc}"[:300]
    try:
        models_status, models = _http_json(out["models_url"], api_key=api_key, timeout=timeout)
        out["models_status"] = models_status
        data = models.get("data") if isinstance(models.get("data"), list) else []
        out["models"] = [
            str(row.get("id", "")) for row in data if isinstance(row, dict) and str(row.get("id", "")).strip()
        ][:20]
        out["ok"] = bool(out["ok"] or (200 <= models_status < 300 and out["models"]))
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        out["models_error"] = f"{type(exc).__name__}: {exc}"[:300]
    out["latency_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
    if not out["ok"] and "health_error" not in out and "models_error" not in out:
        out["error"] = "runtime probe did not confirm health or model availability"
    return out


def model_runtime_status(
    provider_name: str | None = "main_deepseek",
    model: str | None = None,
    *,
    probe: bool = True,
    timeout: float = 2.0,
) -> dict[str, Any]:
    provider = resolve_llm_provider(provider_name, model)
    base_url = provider.base_url or ""
    api_key_present = bool(os.environ.get(provider.api_key_env, "").strip()) or not provider.api_key_required
    probe_result = _probe(provider, timeout=max(float(timeout), 0.1)) if probe else {"ok": None, "checked": False}
    return ModelRuntimeStatus(
        schema="model_runtime_status.v1",
        provider=provider.name,
        label=provider.label,
        model=provider.model,
        base_url=base_url,
        api_key_env=provider.api_key_env,
        api_key_required=provider.api_key_required,
        api_key_present=api_key_present,
        local_endpoint=_is_local_endpoint(base_url),
        serving_hint=_serving_hint(provider),
        probe=probe_result,
    ).to_dict()
