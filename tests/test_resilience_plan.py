from __future__ import annotations

from pathlib import Path

from agent.core.executor import ExecutionLimits, parse_action, run_action, run_action_guarded
from agent.resilience import PaymentEvent, apply_payment_event, build_resilience_plan, initial_payment_state


def test_payment_disconnect_reconciles_without_double_fulfillment() -> None:
    state = initial_payment_state("order-1", "idem-1", amount_cents=1999)
    state = apply_payment_event(state, PaymentEvent(event_id="e1", event_type="client_confirmed"))
    state = apply_payment_event(state, PaymentEvent(event_id="e2", event_type="client_disconnect"))

    assert state.status == "pending"
    assert state.requires_reconciliation is True
    assert [item["type"] for item in state.outbox] == ["payment_reconcile"]

    state = apply_payment_event(
        state,
        PaymentEvent(event_id="e3", event_type="webhook_paid", provider_transaction_id="txn-1"),
    )
    state = apply_payment_event(
        state,
        PaymentEvent(event_id="e3", event_type="webhook_paid", provider_transaction_id="txn-1"),
    )

    assert state.status == "paid"
    assert state.requires_reconciliation is False
    assert [item["type"] for item in state.outbox].count("fulfill_order") == 1
    assert state.version == 3  # duplicate webhook is ignored


def test_resilience_plan_covers_payment_attack_anticrawl_and_chaos() -> None:
    plan = build_resilience_plan(surface="agent-saas", payment_enabled=True, threat_level="internet")
    data = plan.to_dict()

    assert data["payment"]["enabled"] is True
    assert "disconnect_rule" in data["payment"]["state_machine"]
    assert data["attack_resistance"]["layers"]
    assert data["anti_crawl"]["rate_limits"]
    assert any(drill["name"] == "payment_client_disconnect" for drill in data["chaos_drills"])
    assert "payment_attempts_total{status,provider}" in data["observability"]["metrics"]


def test_resilience_plan_action_writes_file_and_uses_permissions(tmp_path: Path) -> None:
    action = parse_action(
        '{"type":"action","action":"resilience_plan","args":'
        '{"surface":"agent-saas","payment_enabled":true,"output_path":"plans/resilience.json"}}'
    )
    result = run_action(tmp_path, action)
    assert result["ok"] is True
    assert result["summary"]["payment_enabled"] is True
    assert (tmp_path / "plans" / "resilience.json").exists()

    denied = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read"})),
    )
    assert denied["ok"] is False
    assert denied["error_code"] == "PERMISSION_DENIED"

    allowed = run_action_guarded(
        tmp_path,
        action,
        limits=ExecutionLimits(granted_permissions=frozenset({"workspace:read", "security:plan"})),
    )
    assert allowed["ok"] is True
    assert allowed["preflight"]["supervisor"]["status"] == "allowed"

