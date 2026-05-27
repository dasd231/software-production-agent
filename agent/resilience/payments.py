from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

from agent.resilience.schema import PaymentEvent, PaymentState


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def initial_payment_state(order_id: str, idempotency_key: str, *, amount_cents: int = 0) -> PaymentState:
    return PaymentState(order_id=order_id, idempotency_key=idempotency_key, amount_cents=max(0, int(amount_cents)))


def _append_once(outbox: list[dict[str, Any]], message: dict[str, Any]) -> list[dict[str, Any]]:
    key = (message.get("type"), message.get("order_id"), message.get("provider_transaction_id"))
    for item in outbox:
        if (item.get("type"), item.get("order_id"), item.get("provider_transaction_id")) == key:
            return outbox
    return [*outbox, message]


def apply_payment_event(state: PaymentState, event: PaymentEvent) -> PaymentState:
    """Idempotent payment state machine for disconnect/webhook/reconcile cases."""

    if event.event_id in state.processed_event_ids:
        return state

    ledger_entry = {"event": event.to_dict(), "previous_status": state.status, "observed_at": event.observed_at or _now_iso()}
    processed = (*state.processed_event_ids, event.event_id)
    outbox = list(state.outbox)
    status = state.status
    provider_txn = state.provider_transaction_id or event.provider_transaction_id
    amount = state.amount_cents or max(0, int(event.amount_cents))
    requires_reconciliation = state.requires_reconciliation
    last_error = state.last_error

    if event.event_type in {"client_confirmed", "provider_pending"}:
        if status == "initiated":
            status = "pending"
    elif event.event_type == "client_disconnect":
        if status not in {"paid", "failed", "refunded"}:
            status = "pending"
            requires_reconciliation = True
            outbox = _append_once(
                outbox,
                {
                    "type": "payment_reconcile",
                    "order_id": state.order_id,
                    "idempotency_key": state.idempotency_key,
                    "not_before_seconds": 30,
                },
            )
    elif event.event_type in {"webhook_paid", "reconcile_paid"}:
        if status != "paid":
            status = "paid"
            requires_reconciliation = False
            provider_txn = provider_txn or event.provider_transaction_id
            outbox = _append_once(
                outbox,
                {
                    "type": "fulfill_order",
                    "order_id": state.order_id,
                    "provider_transaction_id": provider_txn,
                    "idempotency_key": state.idempotency_key,
                },
            )
    elif event.event_type in {"webhook_failed", "reconcile_failed"}:
        if status not in {"paid", "refunded"}:
            status = "failed"
            requires_reconciliation = False
            last_error = event.error or "provider_failed"
            outbox = _append_once(
                outbox,
                {
                    "type": "release_inventory",
                    "order_id": state.order_id,
                    "idempotency_key": state.idempotency_key,
                },
            )
    elif event.event_type == "refund_required":
        if status == "paid":
            status = "refund_pending"
            outbox = _append_once(
                outbox,
                {
                    "type": "refund_payment",
                    "order_id": state.order_id,
                    "provider_transaction_id": provider_txn,
                    "idempotency_key": state.idempotency_key,
                },
            )
    elif event.event_type == "refund_succeeded":
        status = "refunded"
        requires_reconciliation = False
    else:
        last_error = f"unknown_event:{event.event_type}"
        requires_reconciliation = True

    ledger_entry["next_status"] = status
    return replace(
        state,
        status=status,
        provider_transaction_id=provider_txn,
        amount_cents=amount,
        version=state.version + 1,
        processed_event_ids=processed,
        ledger=[*state.ledger, ledger_entry],
        outbox=outbox,
        requires_reconciliation=requires_reconciliation,
        last_error=last_error,
    )


def build_payment_resilience_plan(*, enabled: bool = True, provider: str = "generic") -> dict[str, Any]:
    if not enabled:
        return {"enabled": False, "reason": "payment surface disabled for this deployment"}
    return {
        "enabled": True,
        "schema": "resilience.payment.v1",
        "provider": provider,
        "state_machine": {
            "states": ["initiated", "pending", "paid", "failed", "refund_pending", "refunded"],
            "terminal_states": ["paid", "failed", "refunded"],
            "disconnect_rule": "client_disconnect never marks payment failed; it schedules reconciliation",
        },
        "idempotency": {
            "key": "order_id + user_id + payment_attempt",
            "ttl_hours": 24,
            "dedupe": ["client request", "provider webhook", "reconcile job", "outbox message"],
        },
        "transaction_boundary": [
            "create payment_attempt row with idempotency_key",
            "commit pending order state before calling provider",
            "store webhook inbox event before state transition",
            "write outbox message in same DB transaction as state transition",
            "async dispatcher performs fulfillment/refund exactly-once by idempotency key",
        ],
        "reconciliation": {
            "trigger": ["client disconnect", "webhook timeout", "unknown provider status"],
            "interval_seconds": 300,
            "max_attempts": 12,
            "final_policy": "manual review rather than silent fail when provider cannot confirm",
        },
        "webhook_security": {
            "signature_required": True,
            "timestamp_skew_seconds": 300,
            "replay_defense": "event_id inbox unique index",
        },
        "failure_contract": {
            "user_message": "payment is being confirmed; do not retry blindly",
            "system_action": "show pending page and poll order status",
            "operator_action": "inspect payment_attempt + inbox + outbox by order_id",
        },
    }

