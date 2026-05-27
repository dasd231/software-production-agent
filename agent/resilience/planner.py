from __future__ import annotations

from typing import Any

from agent.resilience.anticrawl import build_anti_crawl_policy
from agent.resilience.payments import build_payment_resilience_plan
from agent.resilience.schema import ResiliencePlan
from agent.resilience.security import build_attack_resistance_plan


def _observability_plan() -> dict[str, Any]:
    return {
        "schema": "resilience.observability.v1",
        "metrics": [
            "payment_attempts_total{status,provider}",
            "payment_reconcile_lag_seconds{provider}",
            "outbox_dispatch_failures_total{type}",
            "auth_failures_total{reason}",
            "rate_limited_requests_total{scope}",
            "bot_risk_score_bucket{surface}",
            "supervisor_denials_total{reason}",
            "sandbox_dispatch_total{status}",
        ],
        "traces": [
            "checkout_attempt",
            "provider_redirect",
            "webhook_inbox",
            "payment_state_transition",
            "outbox_dispatch",
            "rate_limit_decision",
            "supervisor_filter_chain",
        ],
        "alerts": [
            {"name": "PaymentWebhookLag", "expr": "p95(payment_reconcile_lag_seconds) > 600", "severity": "warning"},
            {"name": "OutboxStuck", "expr": "increase(outbox_dispatch_failures_total[10m]) > 5", "severity": "critical"},
            {"name": "CredentialStuffingSpike", "expr": "increase(auth_failures_total[5m]) > baseline*3", "severity": "critical"},
            {"name": "BotThrottleSpike", "expr": "increase(rate_limited_requests_total[5m]) > baseline*5", "severity": "warning"},
        ],
    }


def _chaos_drills(payment_enabled: bool) -> list[dict[str, Any]]:
    drills: list[dict[str, Any]] = [
        {
            "name": "waf_block_false_positive",
            "fault": "block 5% legitimate traffic at edge simulation",
            "expected": "support can identify rule id, disable safely, and observe recovery",
        },
        {
            "name": "bot_spike",
            "fault": "10x anonymous traffic with repeated expensive queries",
            "expected": "rate limiter shifts to cache-only/challenge before DB or model saturation",
        },
        {
            "name": "sandbox_escape_attempt",
            "fault": "submit action requiring hostPath/privileged execution",
            "expected": "supervisor/admission denies and records audit event",
        },
    ]
    if payment_enabled:
        drills.insert(
            0,
            {
                "name": "payment_client_disconnect",
                "fault": "browser closes after provider charge but before callback",
                "expected": "order remains pending, reconcile job confirms provider status, fulfillment fires once",
            },
        )
        drills.insert(
            1,
            {
                "name": "duplicate_webhook",
                "fault": "provider sends paid webhook three times",
                "expected": "inbox event_id unique index dedupes; outbox fulfill_order emitted once",
            },
        )
    return drills


def build_resilience_plan(
    *,
    surface: str = "software-production-agent",
    payment_enabled: bool = True,
    payment_provider: str = "generic",
    threat_level: str = "internet",
) -> ResiliencePlan:
    return ResiliencePlan(
        schema="resilience.plan.v1",
        surface=surface,
        threat_level=threat_level,
        payment=build_payment_resilience_plan(enabled=payment_enabled, provider=payment_provider),
        attack_resistance=build_attack_resistance_plan(threat_level=threat_level),
        anti_crawl=build_anti_crawl_policy(public_surface=surface),
        observability=_observability_plan(),
        chaos_drills=_chaos_drills(payment_enabled),
        runbook=[
            "When payment status is ambiguous, never grant or fail silently; mark pending and reconcile.",
            "When bot score is high, degrade expensive responses before denying all traffic.",
            "When supervisor denies an action, preserve the audit chain and recommend sandbox/human review.",
            "When an incident ends, export traces and update release gates/tests so the same class regresses visibly.",
        ],
    )

