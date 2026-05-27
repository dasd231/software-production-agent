from __future__ import annotations

from typing import Any


SENSITIVE_KEYS = {
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
}


def redact_log_payload(value: Any, *, replacement: str = "***REDACTED***") -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS or any(sensitive in str(key).lower() for sensitive in ("secret", "token", "password")):
                out[str(key)] = replacement
            else:
                out[str(key)] = redact_log_payload(item, replacement=replacement)
        return out
    if isinstance(value, list):
        return [redact_log_payload(item, replacement=replacement) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_log_payload(item, replacement=replacement) for item in value)
    return value


def build_logging_contract() -> dict[str, Any]:
    return {
        "schema": "logging_contract.v1",
        "format": "structured_json",
        "required_fields": [
            "timestamp",
            "level",
            "service",
            "environment",
            "trace_id",
            "span_id",
            "run_id",
            "tenant_id",
            "agent_id",
            "action",
            "status",
            "latency_ms",
            "error_code",
        ],
        "correlation": {
            "trace_id": "cross-service request trace",
            "run_id": "agent task/run lineage",
            "event_id": "single event id in .agent_events.jsonl",
            "graph_node_id": "optional property graph node id",
        },
        "redaction": {
            "sensitive_keys": sorted(SENSITIVE_KEYS),
            "rule": "redact before writing logs, traces or graph properties",
        },
        "retention": {
            "debug": "7 days",
            "info": "30 days",
            "audit": "180 days",
            "security": "365 days or compliance policy",
        },
        "sampling": {
            "normal_requests": "sample at edge when QPS high",
            "errors": "never sample errors",
            "security_events": "never sample security/audit events",
        },
        "anti_patterns": [
            "do not log raw prompts containing secrets",
            "do not log provider access tokens",
            "do not split one incident across uncorrelated text logs",
        ],
    }

