"""Small, dependency-light JWT verification helpers.

The platform primarily needs deterministic validation for control-plane APIs:

1. read ``Authorization: Bearer <token>``
2. parse and validate the JWT header algorithm
3. verify the signature
4. verify ``exp`` / ``nbf`` time claims
5. verify trusted ``iss`` and ``aud``
6. expose ``user_id`` / ``tenant_id`` / ``role`` to request context

Only HS256 is implemented here because the project currently has no crypto
dependency. RS256/EdDSA can be added behind the same interface once a public-key
library is introduced.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any


class JWTAuthError(ValueError):
    """Raised when a JWT cannot be trusted."""


@dataclass(slots=True)
class JWTIdentity:
    user_id: str
    tenant_id: str
    role: str
    permissions: tuple[str, ...] = ()
    claims: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["permissions"] = list(self.permissions)
        return out


def extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise JWTAuthError("missing Authorization header")
    parts = authorization.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise JWTAuthError("Authorization must be Bearer <token>")
    return parts[1]


def _b64url_decode(data: str) -> bytes:
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:  # pragma: no cover - exact exception differs by Python version.
        raise JWTAuthError("invalid base64url segment") from exc


def _json_decode_segment(segment: str, *, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(_b64url_decode(segment).decode("utf-8"))
    except Exception as exc:
        raise JWTAuthError(f"invalid JWT {name}") from exc
    if not isinstance(payload, dict):
        raise JWTAuthError(f"JWT {name} must be a JSON object")
    return payload


def decode_unverified_header(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise JWTAuthError("JWT must contain header, payload and signature")
    return _json_decode_segment(parts[0], name="header")


def _sign_hs256(signing_input: bytes, secret: str) -> bytes:
    if not secret:
        raise JWTAuthError("JWT secret is empty")
    return hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()


def _verify_signature(token: str, *, alg: str, secret: str) -> None:
    header_b64, payload_b64, signature_b64 = token.split(".")
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = _b64url_decode(signature_b64)
    if alg == "HS256":
        expected = _sign_hs256(signing_input, secret)
        if not hmac.compare_digest(signature, expected):
            raise JWTAuthError("invalid JWT signature")
        return
    raise JWTAuthError(f"unsupported JWT algorithm: {alg}")


def _audience_matches(claim_aud: Any, expected_audience: str) -> bool:
    if isinstance(claim_aud, str):
        return claim_aud == expected_audience
    if isinstance(claim_aud, list):
        return expected_audience in {str(item) for item in claim_aud}
    return False


def _validate_time_claims(payload: dict[str, Any], *, now: float, leeway_s: int) -> None:
    exp = payload.get("exp")
    if exp is None:
        raise JWTAuthError("missing exp claim")
    try:
        exp_f = float(exp)
    except (TypeError, ValueError) as exc:
        raise JWTAuthError("exp must be numeric") from exc
    if now > exp_f + leeway_s:
        raise JWTAuthError("JWT expired")

    nbf = payload.get("nbf")
    if nbf is not None:
        try:
            nbf_f = float(nbf)
        except (TypeError, ValueError) as exc:
            raise JWTAuthError("nbf must be numeric") from exc
        if now + leeway_s < nbf_f:
            raise JWTAuthError("JWT is not valid yet")


def _identity_from_claims(payload: dict[str, Any]) -> JWTIdentity:
    user_id = str(payload.get("user_id") or payload.get("sub") or "").strip()
    tenant_id = str(payload.get("tenant_id") or payload.get("tid") or "").strip()
    role = str(payload.get("role") or "").strip()
    permissions_raw = payload.get("permissions") or payload.get("scope") or ()
    if isinstance(permissions_raw, str):
        permissions = tuple(item for item in permissions_raw.replace(",", " ").split() if item)
    elif isinstance(permissions_raw, list):
        permissions = tuple(str(item) for item in permissions_raw if str(item).strip())
    else:
        permissions = ()
    if not user_id:
        raise JWTAuthError("missing user_id/sub claim")
    if not tenant_id:
        raise JWTAuthError("missing tenant_id/tid claim")
    if not role:
        raise JWTAuthError("missing role claim")
    return JWTIdentity(
        user_id=user_id,
        tenant_id=tenant_id,
        role=role,
        permissions=permissions,
        claims=payload,
    )


def verify_jwt(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
    allowed_algorithms: tuple[str, ...] = ("HS256",),
    now: float | None = None,
    leeway_s: int = 30,
) -> JWTIdentity:
    """Verify a JWT and return the identity encoded in its payload."""

    parts = token.split(".")
    if len(parts) != 3:
        raise JWTAuthError("JWT must contain header, payload and signature")

    header = _json_decode_segment(parts[0], name="header")
    alg = str(header.get("alg") or "")
    if not alg or alg.lower() == "none":
        raise JWTAuthError("JWT alg none is not allowed")
    if alg not in allowed_algorithms:
        raise JWTAuthError(f"JWT algorithm {alg} is not allowed")

    _verify_signature(token, alg=alg, secret=secret)
    payload = _json_decode_segment(parts[1], name="payload")

    _validate_time_claims(payload, now=float(now if now is not None else time.time()), leeway_s=int(leeway_s))
    if str(payload.get("iss") or "") != issuer:
        raise JWTAuthError("invalid JWT issuer")
    if not _audience_matches(payload.get("aud"), audience):
        raise JWTAuthError("invalid JWT audience")

    return _identity_from_claims(payload)


__all__ = [
    "JWTAuthError",
    "JWTIdentity",
    "decode_unverified_header",
    "extract_bearer_token",
    "verify_jwt",
]
