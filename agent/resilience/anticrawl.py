from __future__ import annotations

from typing import Any


def build_anti_crawl_policy(*, public_surface: str = "web") -> dict[str, Any]:
    return {
        "schema": "resilience.anti_crawl.v1",
        "surface": public_surface,
        "goals": [
            "protect paid/API resources",
            "avoid blocking normal users",
            "make scraping expensive before it becomes outage-level traffic",
        ],
        "rate_limits": [
            {"scope": "ip", "window": "1m", "limit": 120, "burst": 30},
            {"scope": "account", "window": "1m", "limit": 300, "burst": 60},
            {"scope": "tenant", "window": "1m", "limit": 3000, "burst": 500},
            {"scope": "expensive_agent_action", "window": "1h", "limit": 50, "burst": 10},
        ],
        "signals": [
            "request velocity",
            "path entropy",
            "login/session age",
            "user-agent consistency",
            "token spend velocity",
            "failed challenge ratio",
            "same query with many accounts",
        ],
        "progressive_responses": [
            {"score": "0-30", "action": "allow"},
            {"score": "31-60", "action": "soft throttle + cache-only response for expensive endpoints"},
            {"score": "61-80", "action": "challenge or require login"},
            {"score": "81-100", "action": "deny + audit + temporary token revocation"},
        ],
        "content_protection": [
            "signed URLs for export/download",
            "short-lived pre-signed assets",
            "pagination depth limit",
            "field-level redaction for anonymous traffic",
            "robots.txt as courtesy, not as security boundary",
        ],
        "privacy_boundary": {
            "fingerprinting": "prefer coarse risk signals; avoid collecting invasive device identifiers unless policy/legal approves",
            "manual_review": "high-value tenant blocks require review trail",
        },
    }

