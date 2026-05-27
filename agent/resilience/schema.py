from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class PaymentEvent:
    event_id: str
    event_type: str
    amount_cents: int = 0
    provider_transaction_id: str = ""
    error: str = ""
    observed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PaymentState:
    order_id: str
    idempotency_key: str
    status: str = "initiated"
    provider_transaction_id: str = ""
    amount_cents: int = 0
    version: int = 0
    processed_event_ids: tuple[str, ...] = ()
    ledger: list[dict[str, Any]] = field(default_factory=list)
    outbox: list[dict[str, Any]] = field(default_factory=list)
    requires_reconciliation: bool = False
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResiliencePlan:
    schema: str
    surface: str
    threat_level: str
    payment: dict[str, Any]
    attack_resistance: dict[str, Any]
    anti_crawl: dict[str, Any]
    observability: dict[str, Any]
    chaos_drills: list[dict[str, Any]]
    runbook: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

