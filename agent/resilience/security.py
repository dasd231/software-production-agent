from __future__ import annotations

from typing import Any


def build_attack_resistance_plan(*, threat_level: str = "internet") -> dict[str, Any]:
    return {
        "schema": "resilience.attack_resistance.v1",
        "threat_level": threat_level,
        "principle": "deny by default at edge, app, runtime and data layers; every decision must be observable",
        "layers": [
            {
                "layer": "edge",
                "controls": ["WAF managed rules", "TLS only", "request size limits", "bot score", "geo/IP reputation"],
            },
            {
                "layer": "identity",
                "controls": ["MFA-ready auth", "short access token", "refresh rotation", "role/tenant claims", "password hashing"],
            },
            {
                "layer": "application",
                "controls": [
                    "schema validation",
                    "CSRF for browser sessions",
                    "SSRF URL allowlist",
                    "prompt-injection evidence isolation",
                    "command allowlist through SupervisorChain",
                ],
            },
            {
                "layer": "runtime",
                "controls": [
                    "K8s SecurityContext non-root",
                    "read-only root filesystem",
                    "drop ALL capabilities",
                    "default deny NetworkPolicy",
                    "sandbox high-risk jobs",
                ],
            },
            {
                "layer": "data",
                "controls": ["Secrets not in image/env dumps", "KMS envelope encryption", "least-privilege DB user", "audit log"],
            },
        ],
        "attack_mapping": [
            {
                "attack": "credential stuffing",
                "detection": ["login failure velocity", "IP/account pair entropy"],
                "response": ["progressive delay", "captcha/challenge", "refresh token revocation"],
            },
            {
                "attack": "prompt injection through retrieved evidence",
                "detection": ["instruction-like text inside evidence blocks"],
                "response": ["evidence sanitization", "system prompt non-execution rule", "citation-required answer"],
            },
            {
                "attack": "SSRF / internal metadata access",
                "detection": ["private IP target", "link-local target", "DNS rebinding"],
                "response": ["URL allowlist", "egress proxy", "NetworkPolicy deny"],
            },
            {
                "attack": "command injection / unsafe automation",
                "detection": ["shell metachar risk", "destructive command tokens", "path escape"],
                "response": ["SupervisorChain denial", "human confirmation", "K8s sandbox"],
            },
            {
                "attack": "K8s escape attempt",
                "detection": ["privileged pod request", "hostPath request", "serviceAccount token access"],
                "response": ["admission denial", "SecurityContext", "automountServiceAccountToken=false"],
            },
        ],
        "release_gates": [
            "all public endpoints have auth/rate-limit classification",
            "all state-changing endpoints have idempotency or transaction boundary",
            "all high-risk agent actions pass supervisor audit",
            "secrets scanned before image build",
            "network egress is documented and deny-by-default for sandboxes",
        ],
    }

