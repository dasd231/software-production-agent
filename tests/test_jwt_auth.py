from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

import pytest

from agent.security.jwt_auth import JWTAuthError, extract_bearer_token, verify_jwt

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from agent.platform.api import create_app


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _jwt(payload: dict[str, Any], *, secret: str = "jwt-secret", alg: str = "HS256") -> str:
    header = {"typ": "JWT", "alg": alg}
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(signature)}"


def _payload(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    payload = {
        "sub": "user-001",
        "tenant_id": "tenant-a",
        "role": "admin",
        "permissions": ["platform:read", "platform:write"],
        "iss": "software-production-agent",
        "aud": "software-production-agent-platform",
        "exp": now + 600,
    }
    payload.update(overrides)
    return payload


def test_verify_jwt_returns_request_identity() -> None:
    token = _jwt(_payload())

    identity = verify_jwt(
        token,
        secret="jwt-secret",
        issuer="software-production-agent",
        audience="software-production-agent-platform",
    )

    assert identity.user_id == "user-001"
    assert identity.tenant_id == "tenant-a"
    assert identity.role == "admin"
    assert identity.permissions == ("platform:read", "platform:write")


def test_verify_jwt_rejects_bad_signature_and_expired_token() -> None:
    token = _jwt(_payload(exp=int(time.time()) - 1000))
    with pytest.raises(JWTAuthError, match="expired"):
        verify_jwt(
            token,
            secret="jwt-secret",
            issuer="software-production-agent",
            audience="software-production-agent-platform",
            leeway_s=0,
        )

    tampered = token.rsplit(".", 1)[0] + ".bad-signature"
    with pytest.raises(JWTAuthError, match="signature|base64url"):
        verify_jwt(
            tampered,
            secret="jwt-secret",
            issuer="software-production-agent",
            audience="software-production-agent-platform",
        )


def test_extract_bearer_token_requires_bearer_scheme() -> None:
    assert extract_bearer_token("Bearer abc.def") == "abc.def"
    with pytest.raises(JWTAuthError):
        extract_bearer_token("Basic abc")


def test_platform_api_accepts_jwt_and_attaches_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_PLATFORM_JWT_SECRET", "jwt-secret")
    monkeypatch.delenv("AGENT_PLATFORM_API_TOKEN", raising=False)
    app = create_app(tmp_path)
    client = TestClient(app)
    token = _jwt(_payload())

    denied = client.get("/api/auth/me")
    allowed = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert denied.status_code == 401
    assert allowed.status_code == 200
    body = allowed.json()
    assert body["schema"] == "platform_identity.v1"
    assert body["authenticated"] is True
    assert body["identity"]["auth_type"] == "jwt"
    assert body["identity"]["user_id"] == "user-001"
    assert body["identity"]["tenant_id"] == "tenant-a"
    assert body["identity"]["role"] == "admin"
