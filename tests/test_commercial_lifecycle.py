from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.control_plane.commercial_lifecycle import (
    CommercialLifecycleEventRow,
    CommercialLifecycleKernel,
    CommercialLifecycleService,
)
from apps.control_plane.sql_repository import Base


def _window(start: datetime, minutes: int = 30) -> tuple[str, str, str]:
    end = start + timedelta(minutes=minutes)
    mid = start + timedelta(minutes=1)
    return start.isoformat(), end.isoformat(), mid.isoformat()


def _scope(
    *,
    customer_ref: str = "customer-a",
    deployment_ref: str = "deploy-a",
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
) -> dict[str, str]:
    return {
        "customer_ref": customer_ref,
        "deployment_ref": deployment_ref,
        "tenant_ref": tenant_ref,
        "entity_ref": entity_ref,
        "store_ref": store_ref,
    }


def _accept_event(**changes) -> dict[str, object]:
    start = datetime(2026, 8, 2, 0, 0, tzinfo=UTC)
    window_start, window_end, accepted_at = _window(start)
    event: dict[str, object] = {
        "kind": "commercial_authorization_accepted",
        "idempotency_key": "accept-1",
        "accepted_at": accepted_at,
        "billing_window_start": window_start,
        "billing_window_end": window_end,
        "authorization_ref": "auth-20260802-001",
        "authorization_sha256": "a" * 64,
        "authorization_status": "accepted",
        "authorization_source_kind": "commercial_contract_authorization",
        "metric_limits": [
            {"metric": "requests", "limit": "10", "grace_limit": "8"},
        ],
        **_scope(),
    }
    event.update(changes)
    return event


def _usage_event(
    *,
    amount: str = "1",
    idempotency_key: str = "usage-1",
    customer_ref: str = "customer-a",
    deployment_ref: str = "deploy-a",
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
    metric: str = "requests",
) -> dict[str, object]:
    start = datetime(2026, 8, 2, 0, 0, tzinfo=UTC)
    window_start, window_end, occurred_at = _window(start)
    return {
        "kind": "usage_recorded",
        "idempotency_key": idempotency_key,
        "occurred_at": occurred_at,
        "window_start": window_start,
        "window_end": window_end,
        "metric": metric,
        "amount": amount,
        **_scope(
            customer_ref=customer_ref,
            deployment_ref=deployment_ref,
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
        ),
    }


def _transition_event(
    *,
    target_state: str,
    idempotency_key: str = "transition-1",
    customer_ref: str = "customer-a",
    deployment_ref: str = "deploy-a",
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
    reason: str = "operator_requested",
) -> dict[str, object]:
    return {
        "kind": "lifecycle_transition",
        "idempotency_key": idempotency_key,
        "target_state": target_state,
        "reason": reason,
        "as_of": datetime(2026, 8, 2, 0, 15, tzinfo=UTC).isoformat(),
        **_scope(
            customer_ref=customer_ref,
            deployment_ref=deployment_ref,
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
        ),
    }


def test_accepted_commercial_authorization_creates_exact_scope_entitlement_and_hashes_decision():
    kernel = CommercialLifecycleKernel()

    result = kernel.apply(_accept_event())
    snapshot = kernel.snapshot(**_scope())

    assert result["state"] == "active"
    assert result["reason"] == "commercial_authorization_accepted"
    assert result["limit"] == "10"
    assert result["used"] == "0"
    assert result["remaining"] == "10"
    assert result["as_of"] == "2026-08-02T00:01:00+00:00"
    assert len(result["decision_sha256"]) == 64
    assert len(result["scope_hash"]) == 64
    assert snapshot["scope"] == _scope()
    assert snapshot["state"] == "active"
    assert snapshot["metrics"]["requests"]["limit"] == "10"


def test_authorization_envelope_validation_fails_closed_for_missing_or_wrong_values():
    kernel = CommercialLifecycleKernel()

    with pytest.raises(ValueError, match="authorization_ref is required"):
        kernel.apply(_accept_event(authorization_ref=""))
    with pytest.raises(ValueError, match="lowercase hex digest"):
        kernel.apply(_accept_event(authorization_sha256="A" * 64))
    with pytest.raises(ValueError, match="must be accepted"):
        kernel.apply(_accept_event(authorization_status="rejected"))
    with pytest.raises(ValueError, match="commercial_contract_authorization"):
        kernel.apply(_accept_event(authorization_source_kind="plan_recommendation"))
    with pytest.raises(ValueError, match="accepted commercial authorization event"):
        kernel.apply(_accept_event(plan_recommendation={"package": "premium"}))
    with pytest.raises(ValueError, match="accepted commercial authorization event"):
        kernel.apply(_accept_event(icp={"segment": "mid-market"}))
    with pytest.raises(ValueError, match="accepted commercial authorization event"):
        kernel.apply(_accept_event(seller_tier="gold"))


def test_empty_scope_and_unknown_scope_fail_closed_without_leaking_other_customer_data():
    kernel = CommercialLifecycleKernel()

    with pytest.raises(ValueError, match="customer_ref is required"):
        kernel.apply(_accept_event(customer_ref=""))

    kernel.apply(_accept_event())
    with pytest.raises(LookupError, match="exact scope"):
        kernel.apply(_usage_event(customer_ref="customer-b"))
    with pytest.raises(LookupError, match="exact scope"):
        kernel.snapshot(
            customer_ref="customer-b",
            deployment_ref="deploy-a",
            tenant_ref="tenant-a",
            entity_ref="entity-a",
            store_ref="store-a",
        )


def test_usage_ledger_is_append_only_idempotent_and_rejects_negative_decimal():
    kernel = CommercialLifecycleKernel()
    kernel.apply(_accept_event())

    first = kernel.apply(_usage_event(idempotency_key="usage-append-1", amount="2"))
    replay = kernel.apply(_usage_event(idempotency_key="usage-append-1", amount="2"))
    snapshot = kernel.snapshot(**_scope())

    assert first["state"] == "active"
    assert first["used"] == "2"
    assert replay == {**first, "idempotent": True}
    assert len(snapshot["ledger"]) == 1
    assert snapshot["metrics"]["requests"]["used"] == "2"

    with pytest.raises(ValueError, match="non-negative"):
        kernel.apply(_usage_event(idempotency_key="usage-negative", amount="-1"))


def test_same_idempotency_key_across_scopes_is_isolated_and_same_scope_drift_conflicts():
    kernel = CommercialLifecycleKernel()
    kernel.apply(_accept_event(idempotency_key="accept-a"))
    kernel.apply(
        _accept_event(
            idempotency_key="accept-b",
            customer_ref="customer-b",
            deployment_ref="deploy-b",
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
        )
    )

    first = kernel.apply(_usage_event(idempotency_key="shared-key", amount="1"))
    second = kernel.apply(
        _usage_event(
            idempotency_key="shared-key",
            amount="1",
            customer_ref="customer-b",
            deployment_ref="deploy-b",
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
        )
    )

    assert first["state"] == "active"
    assert second["state"] == "active"

    kernel.apply(_usage_event(idempotency_key="shared-drift", amount="1"))
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        kernel.apply(_usage_event(idempotency_key="shared-drift", amount="2"))


def test_unknown_metric_is_rejected_and_over_quota_returns_read_only_deny():
    kernel = CommercialLifecycleKernel()
    kernel.apply(_accept_event())

    with pytest.raises(ValueError, match="allowlisted"):
        kernel.apply(_usage_event(idempotency_key="usage-unknown", metric="unknown_metric"))

    kernel.apply(_usage_event(idempotency_key="usage-1", amount="8"))
    denied = kernel.apply(_usage_event(idempotency_key="usage-2", amount="3"))
    after_read_only = kernel.apply(_usage_event(idempotency_key="usage-3", amount="1"))

    assert denied["state"] == "read_only"
    assert denied["reason"] == "quota_exceeded"
    assert denied["used"] == "8"
    assert denied["remaining"] == "2"
    assert after_read_only["state"] == "read_only"
    assert after_read_only["reason"] == "entitlement_read_only"
    assert len(kernel.snapshot(**_scope())["ledger"]) == 1


def test_usage_cross_scope_requests_do_not_reach_other_entitlements():
    kernel = CommercialLifecycleKernel()
    kernel.apply(_accept_event())
    kernel.apply(
        _accept_event(
            customer_ref="customer-b",
            deployment_ref="deploy-b",
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
            idempotency_key="accept-2",
        )
    )

    with pytest.raises(LookupError, match="exact scope"):
        kernel.apply(
            _usage_event(
                customer_ref="customer-a",
                deployment_ref="deploy-a",
                tenant_ref="tenant-a",
                entity_ref="entity-a",
                store_ref="store-b",
                idempotency_key="cross-store",
            )
        )
    with pytest.raises(LookupError, match="exact scope"):
        kernel.apply(
            _usage_event(
                customer_ref="customer-b",
                deployment_ref="deploy-b",
                tenant_ref="tenant-a",
                entity_ref="entity-b",
                store_ref="store-b",
                idempotency_key="cross-tenant",
            )
        )
    with pytest.raises(LookupError, match="exact scope"):
        kernel.apply(
            _usage_event(
                customer_ref="customer-b",
                deployment_ref="deploy-b",
                tenant_ref="tenant-b",
                entity_ref="entity-x",
                store_ref="store-b",
                idempotency_key="cross-entity",
            )
        )


def test_read_only_denies_usage_without_changing_ledger_or_totals():
    kernel = CommercialLifecycleKernel()
    kernel.apply(_accept_event())

    kernel.apply(_transition_event(target_state="read_only", idempotency_key="transition-read-only"))
    snapshot_before = kernel.snapshot(**_scope())
    denied = kernel.apply(_usage_event(idempotency_key="usage-read-only", amount="1"))
    snapshot_after = kernel.snapshot(**_scope())

    assert denied["state"] == "read_only"
    assert denied["reason"] == "entitlement_read_only"
    assert snapshot_after["metrics"]["requests"]["used"] == snapshot_before["metrics"]["requests"]["used"]
    assert len(snapshot_after["ledger"]) == len(snapshot_before["ledger"])


def test_state_machine_progresses_active_grace_read_only_and_closed_refuses_revive():
    kernel = CommercialLifecycleKernel()
    kernel.apply(_accept_event())

    active = kernel.apply(_usage_event(idempotency_key="usage-3", amount="7"))
    grace = kernel.apply(_usage_event(idempotency_key="usage-4", amount="1"))
    still_grace = kernel.apply(_usage_event(idempotency_key="usage-5", amount="1"))
    denied = kernel.apply(_usage_event(idempotency_key="usage-6", amount="2"))
    after_read_only = kernel.apply(_usage_event(idempotency_key="usage-7", amount="1"))

    assert active["state"] == "active"
    assert grace["state"] == "grace"
    assert still_grace["state"] == "grace"
    assert denied["state"] == "read_only"
    assert denied["reason"] == "quota_exceeded"
    assert after_read_only["state"] == "read_only"
    assert after_read_only["reason"] == "entitlement_read_only"

    closed = kernel.apply(_transition_event(target_state="closed"))
    assert closed["state"] == "closed"
    assert closed["reason"] == "operator_requested"

    still_closed = kernel.apply(_usage_event(idempotency_key="usage-8", amount="1"))
    assert still_closed["state"] == "closed"
    assert still_closed["reason"] == "entitlement_closed"

    with pytest.raises(ValueError, match="idempotency key conflicts"):
        kernel.apply(_transition_event(target_state="active", idempotency_key="transition-1"))

    revive = kernel.apply(_transition_event(target_state="grace", idempotency_key="transition-2"))
    assert revive["state"] == "closed"
    assert revive["reason"] == "entitlement_closed"


def test_invalid_transition_fails_closed():
    kernel = CommercialLifecycleKernel()
    kernel.apply(_accept_event())

    kernel.apply(_transition_event(target_state="grace", idempotency_key="transition-grace"))
    illegal = kernel.apply(_transition_event(target_state="active", reason="bad_reverse"))

    assert illegal["state"] == "closed"
    assert illegal["reason"] == "invalid_transition"


def test_request_hash_and_decision_hash_are_stable_without_leaking_other_customer_refs():
    kernel = CommercialLifecycleKernel()
    kernel.apply(_accept_event())
    decision = kernel.apply(_usage_event(idempotency_key="usage-8", amount="1"))

    assert len(decision["request_sha256"]) == 64
    assert len(decision["decision_sha256"]) == 64
    dumped = json.dumps(decision, ensure_ascii=False, sort_keys=True)
    assert "customer-b" not in dumped


def _commercial_scope(
    *,
    customer_ref: str = "customer-a",
    deployment_ref: str = "deploy-a",
    tenant_ref: str = "tenant-a",
    entity_ref: str = "entity-a",
    store_ref: str = "store-a",
) -> dict[str, str]:
    return {
        "customer_ref": customer_ref,
        "deployment_ref": deployment_ref,
        "tenant_ref": tenant_ref,
        "entity_ref": entity_ref,
        "store_ref": store_ref,
    }


def _commercial_evidence(evidence_id: str, *, suffix: str) -> dict[str, object]:
    return {
        "evidence_id": evidence_id,
        "evidence_sha256": suffix * 64,
        "evidence_kind": f"{suffix}_evidence",
        "authority": "internal-commercial-ledger",
        "source_kind": "internal_record_only",
        "purposes": ["commercial_audit"],
    }


def _commercial_engine():
    engine = create_engine("sqlite+pysqlite://", future=True)
    Base.metadata.create_all(engine)
    return engine


def _seed_commercial_subscription(
    service: CommercialLifecycleService,
    scope: dict[str, str],
    *,
    prefix: str,
    currency: str = "CNY",
) -> None:
    service.record_plan(
        scope=scope,
        plan_ref=f"plan-{prefix}",
        state="approved",
        currency=currency,
        gross_amount=Decimal("100"),
        effective_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        billing_window_start=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        billing_window_end=datetime(2099, 9, 2, 0, 0, tzinfo=UTC),
        metric_limits=[{"metric": "requests", "limit": "100", "grace_limit": "80"}],
        evidence=_commercial_evidence(f"ev-plan-{prefix}", suffix="a"),
        idempotency_key=f"plan-{prefix}",
    )
    service.record_subscription(
        scope=scope,
        subscription_ref=f"sub-{prefix}",
        plan_ref=f"plan-{prefix}",
        state="active",
        currency=currency,
        amount=Decimal("100"),
        effective_at=datetime(2026, 8, 2, 0, 5, tzinfo=UTC),
        expires_at=None,
        settlement_evidence=_commercial_evidence(f"ev-settlement-{prefix}", suffix="b"),
        evidence=_commercial_evidence(f"ev-subscription-{prefix}", suffix="c"),
        idempotency_key=f"sub-{prefix}",
    )


def _record_commercial_invoice(
    service: CommercialLifecycleService,
    scope: dict[str, str],
    *,
    prefix: str,
    invoice_ref: str,
    gross_amount: str = "100",
    currency: str = "CNY",
    issued_at: datetime = datetime(2026, 8, 2, 0, 10, tzinfo=UTC),
    due_at: datetime = datetime(2099, 8, 12, 0, 10, tzinfo=UTC),
    state: str = "issued",
    idempotency_key: str | None = None,
) -> None:
    service.record_invoice(
        scope=scope,
        invoice_ref=invoice_ref,
        subscription_ref=f"sub-{prefix}",
        state=state,
        currency=currency,
        net_amount=Decimal(gross_amount),
        tax_amount=Decimal("0"),
        gross_amount=Decimal(gross_amount),
        issued_at=issued_at,
        due_at=due_at,
        evidence=_commercial_evidence(
            f"ev-invoice-{idempotency_key or invoice_ref}",
            suffix="d",
        ),
        idempotency_key=idempotency_key or invoice_ref,
    )


def _record_commercial_payment(
    service: CommercialLifecycleService,
    scope: dict[str, str],
    *,
    invoice_ref: str,
    payment_ref: str,
    amount: str,
    state: str,
    currency: str = "CNY",
    idempotency_key: str | None = None,
) -> None:
    service.record_payment_attempt(
        scope=scope,
        payment_attempt_ref=payment_ref,
        invoice_ref=invoice_ref,
        state=state,
        currency=currency,
        amount=Decimal(amount),
        occurred_at=datetime(2026, 8, 2, 0, 12, tzinfo=UTC),
        evidence=_commercial_evidence(
            f"ev-payment-{idempotency_key or payment_ref}",
            suffix="e",
        ),
        idempotency_key=idempotency_key or payment_ref,
    )


def _record_commercial_refund(
    service: CommercialLifecycleService,
    scope: dict[str, str],
    *,
    invoice_ref: str,
    payment_ref: str,
    refund_ref: str,
    amount: str,
    state: str,
    currency: str = "CNY",
    idempotency_key: str | None = None,
) -> None:
    service.record_refund(
        scope=scope,
        refund_ref=refund_ref,
        invoice_ref=invoice_ref,
        payment_attempt_ref=payment_ref,
        state=state,
        currency=currency,
        amount=Decimal(amount),
        occurred_at=datetime(2026, 8, 2, 0, 13, tzinfo=UTC),
        evidence=_commercial_evidence(
            f"ev-refund-{idempotency_key or refund_ref}",
            suffix="f",
        ),
        idempotency_key=idempotency_key or refund_ref,
    )


def _assert_entitlement(
    snapshot: dict[str, object],
    *,
    state: str,
    reason: str,
    invoice_total: str,
    payment_total: str,
    refund_total: str,
    outstanding_total: str,
) -> None:
    entitlement = snapshot["entitlement"]
    assert isinstance(entitlement, dict)
    assert entitlement["state"] == state
    assert entitlement["reason"] == reason
    payload = entitlement["payload"]
    assert isinstance(payload, dict)
    assert payload["invoice_total"] == invoice_total
    assert payload["payment_total"] == payment_total
    assert payload["refund_total"] == refund_total
    assert payload["outstanding_total"] == outstanding_total


def test_scope_write_lock_precedes_payment_capacity_and_append(monkeypatch) -> None:
    service = CommercialLifecycleService(_commercial_engine())
    calls: list[str] = []

    def lock(_session, *, scope) -> None:
        assert scope.scope_hash
        calls.append("lock")

    def record(_session, **_kwargs):
        calls.append("record")
        return {"status": "recorded"}

    monkeypatch.setattr(service, "_lock_scope_write", lock)
    monkeypatch.setattr(service, "_record_payment_attempt", record)
    response = service.record_payment_attempt(
        scope=_commercial_scope(),
        payment_attempt_ref="pay-lock-order",
        invoice_ref="inv-lock-order",
        state="settled",
        currency="CNY",
        amount=Decimal("1"),
        occurred_at=datetime(2026, 8, 2, 0, 12, tzinfo=UTC),
        evidence=_commercial_evidence("ev-payment-lock-order", suffix="e"),
        idempotency_key="pay-lock-order",
    )
    assert response == {"status": "recorded"}
    assert calls == ["lock", "record"]


def test_database_commercial_lifecycle_records_append_only_lineage_and_derives_entitlement():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    plan_evidence = _commercial_evidence("ev-plan-1", suffix="a")
    settlement_evidence = _commercial_evidence("ev-settlement-1", suffix="b")
    subscription_evidence = _commercial_evidence("ev-subscription-1", suffix="c")
    invoice_evidence = _commercial_evidence("ev-invoice-1", suffix="d")
    payment_evidence = _commercial_evidence("ev-payment-1", suffix="e")
    refund_evidence = _commercial_evidence("ev-refund-1", suffix="f")
    tax_evidence = _commercial_evidence("ev-tax-1", suffix="1")

    plan = service.record_plan(
        scope=scope,
        plan_ref="plan-1",
        state="approved",
        currency="CNY",
        gross_amount=Decimal("100"),
        effective_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        billing_window_start=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        billing_window_end=datetime(2026, 9, 2, 0, 0, tzinfo=UTC),
        metric_limits=[{"metric": "requests", "limit": "100", "grace_limit": "80"}],
        evidence=plan_evidence,
        idempotency_key="plan-1",
    )
    replay = service.record_plan(
        scope=scope,
        plan_ref="plan-1",
        state="approved",
        currency="CNY",
        gross_amount=Decimal("100"),
        effective_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        billing_window_start=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        billing_window_end=datetime(2026, 9, 2, 0, 0, tzinfo=UTC),
        metric_limits=[{"metric": "requests", "limit": "100", "grace_limit": "80"}],
        evidence=plan_evidence,
        idempotency_key="plan-1",
    )
    subscription = service.record_subscription(
        scope=scope,
        subscription_ref="sub-1",
        plan_ref="plan-1",
        state="active",
        currency="CNY",
        amount=Decimal("100"),
        effective_at=datetime(2026, 8, 2, 0, 5, tzinfo=UTC),
        expires_at=None,
        settlement_evidence=settlement_evidence,
        evidence=subscription_evidence,
        idempotency_key="sub-1",
    )
    invoice = service.record_invoice(
        scope=scope,
        invoice_ref="inv-1",
        subscription_ref="sub-1",
        state="issued",
        currency="CNY",
        net_amount=Decimal("90"),
        tax_amount=Decimal("10"),
        gross_amount=Decimal("100"),
        issued_at=datetime(2026, 8, 2, 0, 10, tzinfo=UTC),
        due_at=datetime(2026, 8, 12, 0, 10, tzinfo=UTC),
        evidence=invoice_evidence,
        idempotency_key="inv-1",
    )
    payment = service.record_payment_attempt(
        scope=scope,
        payment_attempt_ref="pay-1",
        invoice_ref="inv-1",
        state="settled",
        currency="CNY",
        amount=Decimal("100"),
        occurred_at=datetime(2026, 8, 2, 0, 12, tzinfo=UTC),
        evidence=payment_evidence,
        idempotency_key="pay-1",
    )
    refund = service.record_refund(
        scope=scope,
        refund_ref="refund-1",
        invoice_ref="inv-1",
        payment_attempt_ref="pay-1",
        state="paid",
        currency="CNY",
        amount=Decimal("20"),
        occurred_at=datetime(2026, 8, 2, 0, 13, tzinfo=UTC),
        evidence=refund_evidence,
        idempotency_key="refund-1",
    )
    tax = service.record_tax_evidence(
        scope=scope,
        tax_evidence_ref="tax-1",
        invoice_ref="inv-1",
        refund_ref="refund-1",
        state="recorded",
        currency="CNY",
        amount=Decimal("10"),
        observed_at=datetime(2026, 8, 2, 0, 14, tzinfo=UTC),
        evidence=tax_evidence,
        idempotency_key="tax-1",
    )

    snapshot = service.snapshot(**scope)

    assert plan["idempotent"] is False
    assert replay["idempotent"] is True
    assert subscription["state"] == "active"
    assert invoice["state"] == "issued"
    assert payment["state"] == "settled"
    assert refund["state"] == "paid"
    assert tax["state"] == "recorded"
    assert snapshot["entitlement"]["state"] == "grace"
    assert snapshot["entitlement"]["reason"] == "outstanding_balance"
    _assert_entitlement(
        snapshot,
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="100",
        refund_total="20",
        outstanding_total="20",
    )
    assert len(snapshot["events"]) >= 6
    plan_event = next(event for event in snapshot["events"] if event["lifecycle_kind"] == "plan")
    assert plan_event["payload"]["evidence"]["evidence_id"] == "ev-plan-1"
    assert plan_event["response"]["evidence_lineage"][0]["evidence_kind"] == "a_evidence"


def test_database_commercial_lifecycle_refund_cannot_exceed_collected_payment():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope(customer_ref="customer-b", deployment_ref="deploy-b", tenant_ref="tenant-b", entity_ref="entity-b", store_ref="store-b")
    service.record_plan(
        scope=scope,
        plan_ref="plan-2",
        state="approved",
        currency="CNY",
        gross_amount=Decimal("100"),
        effective_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        billing_window_start=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        billing_window_end=datetime(2026, 9, 2, 0, 0, tzinfo=UTC),
        metric_limits=[{"metric": "requests", "limit": "100", "grace_limit": "80"}],
        evidence=_commercial_evidence("ev-plan-2", suffix="2"),
        idempotency_key="plan-2",
    )
    service.record_subscription(
        scope=scope,
        subscription_ref="sub-2",
        plan_ref="plan-2",
        state="active",
        currency="CNY",
        amount=Decimal("100"),
        effective_at=datetime(2026, 8, 2, 0, 5, tzinfo=UTC),
        expires_at=None,
        settlement_evidence=_commercial_evidence("ev-settlement-2", suffix="3"),
        evidence=_commercial_evidence("ev-subscription-2", suffix="4"),
        idempotency_key="sub-2",
    )
    service.record_invoice(
        scope=scope,
        invoice_ref="inv-2",
        subscription_ref="sub-2",
        state="issued",
        currency="CNY",
        net_amount=Decimal("90"),
        tax_amount=Decimal("10"),
        gross_amount=Decimal("100"),
        issued_at=datetime(2026, 8, 2, 0, 10, tzinfo=UTC),
        due_at=datetime(2026, 8, 12, 0, 10, tzinfo=UTC),
        evidence=_commercial_evidence("ev-invoice-2", suffix="5"),
        idempotency_key="inv-2",
    )
    service.record_payment_attempt(
        scope=scope,
        payment_attempt_ref="pay-2",
        invoice_ref="inv-2",
        state="settled",
        currency="CNY",
        amount=Decimal("60"),
        occurred_at=datetime(2026, 8, 2, 0, 12, tzinfo=UTC),
        evidence=_commercial_evidence("ev-payment-2", suffix="6"),
        idempotency_key="pay-2",
    )

    with pytest.raises(ValueError, match="paid refunds must not exceed the exact settled payment"):
        service.record_refund(
            scope=scope,
            refund_ref="refund-too-large",
            invoice_ref="inv-2",
            payment_attempt_ref="pay-2",
            state="paid",
            currency="CNY",
            amount=Decimal("61"),
            occurred_at=datetime(2026, 8, 2, 0, 13, tzinfo=UTC),
            evidence=_commercial_evidence("ev-refund-2", suffix="7"),
            idempotency_key="refund-too-large",
        )


def test_entitlement_without_payment_keeps_full_invoice_outstanding_in_grace():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="zero")
    _record_commercial_invoice(service, scope, prefix="zero", invoice_ref="inv-zero")

    snapshot = service.snapshot(**scope)
    _assert_entitlement(
        snapshot,
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="0",
        refund_total="0",
        outstanding_total="100",
    )


def test_succeeded_payment_is_not_settled_cash_and_does_not_activate_entitlement():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="succeeded")
    _record_commercial_invoice(
        service,
        scope,
        prefix="succeeded",
        invoice_ref="inv-succeeded",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-succeeded",
        payment_ref="pay-succeeded",
        amount="100",
        state="succeeded",
    )

    snapshot = service.snapshot(**scope)
    _assert_entitlement(
        snapshot,
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="0",
        refund_total="0",
        outstanding_total="100",
    )


def test_partial_settled_payment_reduces_outstanding_and_preserves_capacity():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="partial")
    _record_commercial_invoice(service, scope, prefix="partial", invoice_ref="inv-partial")
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-partial",
        payment_ref="pay-partial",
        amount="40",
        state="settled",
    )

    _assert_entitlement(
        service.snapshot(**scope),
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="40",
        refund_total="0",
        outstanding_total="60",
    )
    with pytest.raises(ValueError, match="payment attempt amount must not exceed"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-partial",
            payment_ref="pay-over-capacity",
            amount="61",
            state="settled",
        )
    assert len(service.snapshot(**scope)["payment_attempts"]) == 1


def test_settled_payment_activates_and_paid_refund_reopens_exact_outstanding():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="refund-paid")
    _record_commercial_invoice(
        service,
        scope,
        prefix="refund-paid",
        invoice_ref="inv-refund-paid",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-refund-paid",
        payment_ref="pay-refund-paid",
        amount="100",
        state="settled",
    )
    _assert_entitlement(
        service.snapshot(**scope),
        state="active",
        reason="subscription_and_settlement_confirmed",
        invoice_total="100",
        payment_total="100",
        refund_total="0",
        outstanding_total="0",
    )

    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-refund-paid",
        payment_ref="pay-refund-paid",
        refund_ref="refund-paid",
        amount="20",
        state="paid",
    )
    snapshot = service.snapshot(**scope)
    _assert_entitlement(
        snapshot,
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="100",
        refund_total="20",
        outstanding_total="20",
    )
    business_event_times = [
        event["recorded_at"]
        for event in snapshot["events"]
        if event["lifecycle_kind"] != "entitlement"
    ]
    assert business_event_times == sorted(set(business_event_times))


def test_approved_refund_does_not_reopen_outstanding_before_cash_is_paid():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="refund-approved")
    _record_commercial_invoice(
        service,
        scope,
        prefix="refund-approved",
        invoice_ref="inv-refund-approved",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-refund-approved",
        payment_ref="pay-refund-approved",
        amount="100",
        state="settled",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-refund-approved",
        payment_ref="pay-refund-approved",
        refund_ref="refund-approved",
        amount="20",
        state="approved",
    )

    _assert_entitlement(
        service.snapshot(**scope),
        state="active",
        reason="subscription_and_settlement_confirmed",
        invoice_total="100",
        payment_total="100",
        refund_total="0",
        outstanding_total="0",
    )


def test_latest_payment_and_refund_states_are_counted_once():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="latest")
    _record_commercial_invoice(service, scope, prefix="latest", invoice_ref="inv-latest")
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-latest",
        payment_ref="pay-latest",
        amount="100",
        state="succeeded",
        idempotency_key="pay-latest-succeeded",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-latest",
        payment_ref="pay-latest",
        amount="100",
        state="settled",
        idempotency_key="pay-latest-settled",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-latest",
        payment_ref="pay-latest",
        refund_ref="refund-latest",
        amount="20",
        state="approved",
        idempotency_key="refund-latest-approved",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-latest",
        payment_ref="pay-latest",
        refund_ref="refund-latest",
        amount="20",
        state="paid",
        idempotency_key="refund-latest-paid",
    )

    _assert_entitlement(
        service.snapshot(**scope),
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="100",
        refund_total="20",
        outstanding_total="20",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-latest",
        payment_ref="pay-latest",
        refund_ref="refund-latest",
        amount="20",
        state="reversed",
        idempotency_key="refund-latest-reversed",
    )
    _assert_entitlement(
        service.snapshot(**scope),
        state="active",
        reason="subscription_and_settlement_confirmed",
        invoice_total="100",
        payment_total="100",
        refund_total="0",
        outstanding_total="0",
    )


def test_multiple_invoices_conserve_gross_settled_refund_and_outstanding_totals():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="multi")
    _record_commercial_invoice(
        service,
        scope,
        prefix="multi",
        invoice_ref="inv-multi-a",
        gross_amount="60",
    )
    _record_commercial_invoice(
        service,
        scope,
        prefix="multi",
        invoice_ref="inv-multi-b",
        gross_amount="40",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-multi-a",
        payment_ref="pay-multi-a",
        amount="30",
        state="settled",
    )
    _record_commercial_invoice(
        service,
        scope,
        prefix="multi",
        invoice_ref="inv-multi-a",
        gross_amount="60",
        state="partially_paid",
        idempotency_key="inv-multi-a-partially-paid",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-multi-b",
        payment_ref="pay-multi-b",
        amount="40",
        state="settled",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-multi-b",
        payment_ref="pay-multi-b",
        refund_ref="refund-multi-b",
        amount="10",
        state="paid",
    )

    snapshot = service.snapshot(**scope)
    _assert_entitlement(
        snapshot,
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="70",
        refund_total="10",
        outstanding_total="40",
    )
    assert snapshot["entitlement"]["payload"]["invoice_refs"] == [
        "inv-multi-a",
        "inv-multi-b",
    ]


def test_entitlement_only_projects_invoices_for_the_current_subscription() -> None:
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="old")
    _record_commercial_invoice(
        service,
        scope,
        prefix="old",
        invoice_ref="inv-old",
        gross_amount="300",
    )

    _seed_commercial_subscription(service, scope, prefix="current")
    snapshot = service.snapshot(**scope)
    _assert_entitlement(
        snapshot,
        state="active",
        reason="subscription_and_settlement_confirmed",
        invoice_total="0",
        payment_total="0",
        refund_total="0",
        outstanding_total="0",
    )
    assert snapshot["entitlement"]["payload"]["subscription_ref"] == "sub-current"
    assert snapshot["entitlement"]["payload"]["invoice_refs"] == []

    _record_commercial_invoice(
        service,
        scope,
        prefix="current",
        invoice_ref="inv-current",
        gross_amount="50",
    )
    snapshot = service.snapshot(**scope)
    _assert_entitlement(
        snapshot,
        state="grace",
        reason="outstanding_balance",
        invoice_total="50",
        payment_total="0",
        refund_total="0",
        outstanding_total="50",
    )
    assert snapshot["entitlement"]["payload"]["invoice_refs"] == ["inv-current"]


def test_noncollectible_invoice_states_never_create_or_retain_receivables() -> None:
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="invoice-state")
    _record_commercial_invoice(
        service,
        scope,
        prefix="invoice-state",
        invoice_ref="inv-state",
        state="draft",
    )
    _assert_entitlement(
        service.snapshot(**scope),
        state="active",
        reason="subscription_and_settlement_confirmed",
        invoice_total="0",
        payment_total="0",
        refund_total="0",
        outstanding_total="0",
    )
    with pytest.raises(ValueError, match="invoice state is not collectible"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-state",
            payment_ref="pay-draft",
            amount="100",
            state="settled",
        )

    _record_commercial_invoice(
        service,
        scope,
        prefix="invoice-state",
        invoice_ref="inv-state",
        state="issued",
        idempotency_key="inv-state-issued",
    )
    _assert_entitlement(
        service.snapshot(**scope),
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="0",
        refund_total="0",
        outstanding_total="100",
    )

    _record_commercial_invoice(
        service,
        scope,
        prefix="invoice-state",
        invoice_ref="inv-state",
        state="void",
        idempotency_key="inv-state-void",
    )
    _assert_entitlement(
        service.snapshot(**scope),
        state="active",
        reason="subscription_and_settlement_confirmed",
        invoice_total="0",
        payment_total="0",
        refund_total="0",
        outstanding_total="0",
    )
    with pytest.raises(ValueError, match="invoice state is not collectible"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-state",
            payment_ref="pay-void",
            amount="100",
            state="settled",
        )


def test_paid_invoice_state_does_not_substitute_for_settled_cash() -> None:
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="paid-state")
    _record_commercial_invoice(
        service,
        scope,
        prefix="paid-state",
        invoice_ref="inv-paid-state",
        state="paid",
    )
    _assert_entitlement(
        service.snapshot(**scope),
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="0",
        refund_total="0",
        outstanding_total="100",
    )


def test_paid_refund_requires_and_is_capped_by_its_exact_settled_payment() -> None:
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="payment-bound-refund")
    _record_commercial_invoice(
        service,
        scope,
        prefix="payment-bound-refund",
        invoice_ref="inv-payment-bound-refund",
        gross_amount="200",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-payment-bound-refund",
        payment_ref="pay-a",
        amount="100",
        state="settled",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-payment-bound-refund",
        payment_ref="pay-b",
        amount="100",
        state="succeeded",
    )
    with pytest.raises(ValueError, match="paid refund requires an exact settled payment"):
        _record_commercial_refund(
            service,
            scope,
            invoice_ref="inv-payment-bound-refund",
            payment_ref="pay-b",
            refund_ref="refund-unsettled",
            amount="10",
            state="paid",
        )

    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-payment-bound-refund",
        payment_ref="pay-b",
        amount="100",
        state="settled",
        idempotency_key="pay-b-settled",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-payment-bound-refund",
        payment_ref="pay-a",
        refund_ref="refund-pay-a-80",
        amount="80",
        state="paid",
    )
    with pytest.raises(ValueError, match="paid refunds must not exceed the exact settled payment"):
        _record_commercial_refund(
            service,
            scope,
            invoice_ref="inv-payment-bound-refund",
            payment_ref="pay-a",
            refund_ref="refund-pay-a-over-cap",
            amount="30",
            state="paid",
        )
    assert len(service.snapshot(**scope)["refunds"]) == 1


def test_cross_scope_cash_events_do_not_change_other_scope_entitlement():
    service = CommercialLifecycleService(_commercial_engine())
    scope_a = _commercial_scope()
    scope_b = _commercial_scope(
        customer_ref="customer-b",
        deployment_ref="deploy-b",
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
    )
    _seed_commercial_subscription(service, scope_a, prefix="scope-a")
    _seed_commercial_subscription(service, scope_b, prefix="scope-b")
    _record_commercial_invoice(service, scope_a, prefix="scope-a", invoice_ref="inv-scope-a")
    _record_commercial_invoice(
        service,
        scope_b,
        prefix="scope-b",
        invoice_ref="inv-scope-b",
        gross_amount="200",
    )
    _record_commercial_payment(
        service,
        scope_b,
        invoice_ref="inv-scope-b",
        payment_ref="pay-scope-b",
        amount="200",
        state="settled",
    )

    _assert_entitlement(
        service.snapshot(**scope_a),
        state="grace",
        reason="outstanding_balance",
        invoice_total="100",
        payment_total="0",
        refund_total="0",
        outstanding_total="100",
    )
    _assert_entitlement(
        service.snapshot(**scope_b),
        state="active",
        reason="subscription_and_settlement_confirmed",
        invoice_total="200",
        payment_total="200",
        refund_total="0",
        outstanding_total="0",
    )


def test_unpaid_overdue_invoice_sets_read_only_entitlement():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="overdue")
    _record_commercial_invoice(
        service,
        scope,
        prefix="overdue",
        invoice_ref="inv-overdue",
        issued_at=datetime(2019, 1, 1, 0, 0, tzinfo=UTC),
        due_at=datetime(2020, 1, 1, 0, 0, tzinfo=UTC),
    )

    _assert_entitlement(
        service.snapshot(**scope),
        state="read_only",
        reason="invoice_overdue",
        invoice_total="100",
        payment_total="0",
        refund_total="0",
        outstanding_total="100",
    )


def test_currency_drift_fails_before_invoice_payment_or_refund_is_recorded():
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="currency")

    with pytest.raises(ValueError, match="invoice currency must match"):
        _record_commercial_invoice(
            service,
            scope,
            prefix="currency",
            invoice_ref="inv-wrong-currency",
            currency="RUB",
        )
    _record_commercial_invoice(
        service,
        scope,
        prefix="currency",
        invoice_ref="inv-currency",
    )
    with pytest.raises(ValueError, match="invoice currency does not match"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-currency",
            payment_ref="pay-wrong-currency",
            amount="100",
            state="settled",
            currency="RUB",
        )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-currency",
        payment_ref="pay-currency",
        amount="100",
        state="settled",
    )
    with pytest.raises(ValueError, match="invoice currency does not match"):
        _record_commercial_refund(
            service,
            scope,
            invoice_ref="inv-currency",
            payment_ref="pay-currency",
            refund_ref="refund-wrong-currency",
            amount="20",
            state="paid",
            currency="RUB",
        )
    snapshot = service.snapshot(**scope)
    assert len(snapshot["payment_attempts"]) == 1
    assert snapshot["refunds"] == []


def test_invoice_payment_and_refund_record_identity_and_money_are_immutable() -> None:
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="identity-a")
    _record_commercial_invoice(
        service,
        scope,
        prefix="identity-a",
        invoice_ref="inv-identity-a",
        gross_amount="200",
    )
    _record_commercial_invoice(
        service,
        scope,
        prefix="identity-a",
        invoice_ref="inv-identity-b",
        gross_amount="200",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-identity-a",
        payment_ref="pay-identity",
        amount="100",
        state="succeeded",
        idempotency_key="pay-identity-succeeded",
    )
    with pytest.raises(ValueError, match="identity and money tuple are immutable"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-identity-b",
            payment_ref="pay-identity",
            amount="100",
            state="settled",
            idempotency_key="pay-identity-rebound",
        )
    with pytest.raises(ValueError, match="identity and money tuple are immutable"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-identity-a",
            payment_ref="pay-identity",
            amount="101",
            state="settled",
            idempotency_key="pay-identity-money-drift",
        )

    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-identity-a",
        payment_ref="pay-identity",
        amount="100",
        state="settled",
        idempotency_key="pay-identity-settled",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-identity-a",
        payment_ref="pay-identity-2",
        amount="100",
        state="settled",
        idempotency_key="pay-identity-2-settled",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-identity-a",
        payment_ref="pay-identity",
        refund_ref="refund-identity",
        amount="80",
        state="approved",
        idempotency_key="refund-identity-approved",
    )
    with pytest.raises(ValueError, match="identity and money tuple are immutable"):
        _record_commercial_refund(
            service,
            scope,
            invoice_ref="inv-identity-a",
            payment_ref="pay-identity-2",
            refund_ref="refund-identity",
            amount="80",
            state="paid",
            idempotency_key="refund-identity-rebound",
        )
    _seed_commercial_subscription(service, scope, prefix="identity-b")
    with pytest.raises(ValueError, match="identity and money tuple are immutable"):
        _record_commercial_invoice(
            service,
            scope,
            prefix="identity-b",
            invoice_ref="inv-identity-a",
            gross_amount="200",
            state="partially_paid",
            idempotency_key="invoice-identity-parent-drift",
        )
    with pytest.raises(ValueError, match="identity and money tuple are immutable"):
        _record_commercial_invoice(
            service,
            scope,
            prefix="identity-a",
            invoice_ref="inv-identity-a",
            gross_amount="201",
            state="partially_paid",
            idempotency_key="invoice-identity-money-drift",
        )


def test_non_idempotent_same_state_replay_and_paid_to_rejected_refund_are_blocked() -> None:
    service = CommercialLifecycleService(_commercial_engine())
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="refund-state")
    _record_commercial_invoice(service, scope, prefix="refund-state", invoice_ref="inv-refund-state")
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-refund-state",
        payment_ref="pay-refund-state",
        amount="100",
        state="settled",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-refund-state",
        payment_ref="pay-refund-state",
        refund_ref="refund-state",
        amount="80",
        state="paid",
        idempotency_key="refund-state-paid",
    )
    with pytest.raises(ValueError, match="state replay requires the original idempotency key"):
        _record_commercial_refund(
            service,
            scope,
            invoice_ref="inv-refund-state",
            payment_ref="pay-refund-state",
            refund_ref="refund-state",
            amount="80",
            state="paid",
            idempotency_key="refund-state-paid-again",
        )
    with pytest.raises(ValueError, match="refund state transition is not allowed"):
        _record_commercial_refund(
            service,
            scope,
            invoice_ref="inv-refund-state",
            payment_ref="pay-refund-state",
            refund_ref="refund-state",
            amount="80",
            state="rejected",
            idempotency_key="refund-state-rejected-after-paid",
        )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-refund-state",
        payment_ref="pay-refund-state",
        refund_ref="refund-state",
        amount="80",
        state="reversed",
        idempotency_key="refund-state-reversed",
    )
    _assert_entitlement(
        service.snapshot(**scope),
        state="active",
        reason="subscription_and_settlement_confirmed",
        invoice_total="100",
        payment_total="100",
        refund_total="0",
        outstanding_total="0",
    )


def test_invoice_payment_and_refund_exact_winners_replay_before_current_state_checks() -> None:
    engine = _commercial_engine()
    service = CommercialLifecycleService(engine)
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="winner")
    _record_commercial_invoice(
        service,
        scope,
        prefix="winner",
        invoice_ref="inv-winner",
        idempotency_key="inv-winner-issued",
    )
    _record_commercial_payment(
        service,
        scope,
        invoice_ref="inv-winner",
        payment_ref="pay-winner",
        amount="100",
        state="settled",
        idempotency_key="pay-winner-settled",
    )
    _record_commercial_refund(
        service,
        scope,
        invoice_ref="inv-winner",
        payment_ref="pay-winner",
        refund_ref="refund-winner",
        amount="20",
        state="paid",
        idempotency_key="refund-winner-paid",
    )
    _record_commercial_invoice(
        service,
        scope,
        prefix="winner",
        invoice_ref="inv-winner",
        state="void",
        idempotency_key="inv-winner-void",
    )

    with engine.connect() as connection:
        before_events = connection.scalar(text("SELECT count(*) FROM commercial_lifecycle_events"))
        before_evidence = connection.scalar(text("SELECT count(*) FROM commercial_lifecycle_evidence"))

    invoice_replay = service.record_invoice(
        scope=scope,
        invoice_ref="inv-winner",
        subscription_ref="sub-winner",
        state="issued",
        currency="CNY",
        net_amount=Decimal("100"),
        tax_amount=Decimal("0"),
        gross_amount=Decimal("100"),
        issued_at=datetime(2026, 8, 2, 0, 10, tzinfo=UTC),
        due_at=datetime(2099, 8, 12, 0, 10, tzinfo=UTC),
        evidence=_commercial_evidence("ev-invoice-inv-winner-issued", suffix="d"),
        idempotency_key="inv-winner-issued",
    )
    payment_replay = service.record_payment_attempt(
        scope=scope,
        payment_attempt_ref="pay-winner",
        invoice_ref="inv-winner",
        state="settled",
        currency="CNY",
        amount=Decimal("100"),
        occurred_at=datetime(2026, 8, 2, 0, 12, tzinfo=UTC),
        evidence=_commercial_evidence("ev-payment-pay-winner-settled", suffix="e"),
        idempotency_key="pay-winner-settled",
    )
    refund_replay = service.record_refund(
        scope=scope,
        refund_ref="refund-winner",
        invoice_ref="inv-winner",
        payment_attempt_ref="pay-winner",
        state="paid",
        currency="CNY",
        amount=Decimal("20"),
        occurred_at=datetime(2026, 8, 2, 0, 13, tzinfo=UTC),
        evidence=_commercial_evidence("ev-refund-refund-winner-paid", suffix="f"),
        idempotency_key="refund-winner-paid",
    )
    assert invoice_replay["idempotent"] is True
    assert payment_replay["idempotent"] is True
    assert refund_replay["idempotent"] is True

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM commercial_lifecycle_events")) == before_events
        assert connection.scalar(text("SELECT count(*) FROM commercial_lifecycle_evidence")) == before_evidence

    with pytest.raises(ValueError, match="idempotency key conflicts"):
        service.record_invoice(
            scope=scope,
            invoice_ref="inv-winner",
            subscription_ref="sub-winner",
            state="issued",
            currency="CNY",
            net_amount=Decimal("101"),
            tax_amount=Decimal("0"),
            gross_amount=Decimal("101"),
            issued_at=datetime(2026, 8, 2, 0, 10, tzinfo=UTC),
            due_at=datetime(2099, 8, 12, 0, 10, tzinfo=UTC),
            evidence=_commercial_evidence("ev-invoice-inv-winner-issued", suffix="d"),
            idempotency_key="inv-winner-issued",
        )
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-winner",
            payment_ref="pay-winner",
            amount="99",
            state="settled",
            idempotency_key="pay-winner-settled",
        )
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        _record_commercial_refund(
            service,
            scope,
            invoice_ref="inv-winner",
            payment_ref="pay-winner",
            refund_ref="refund-winner",
            amount="21",
            state="paid",
            idempotency_key="refund-winner-paid",
        )
    with pytest.raises(ValueError, match="state replay requires the original idempotency key"):
        _record_commercial_invoice(
            service,
            scope,
            prefix="winner",
            invoice_ref="inv-winner",
            state="void",
            idempotency_key="inv-winner-void-again",
        )
    with pytest.raises(ValueError, match="state replay requires the original idempotency key"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-winner",
            payment_ref="pay-winner",
            amount="100",
            state="settled",
            idempotency_key="pay-winner-settled-again",
        )
    with pytest.raises(ValueError, match="state replay requires the original idempotency key"):
        _record_commercial_refund(
            service,
            scope,
            invoice_ref="inv-winner",
            payment_ref="pay-winner",
            refund_ref="refund-winner",
            amount="20",
            state="paid",
            idempotency_key="refund-winner-paid-again",
        )


@pytest.mark.skipif(
    not os.getenv("KJDS_COM002_TEST_POSTGRES_URL"),
    reason="PostgreSQL concurrency contract requires KJDS_COM002_TEST_POSTGRES_URL",
)
def test_postgres_scope_lock_serializes_cash_capacity_and_keeps_other_scopes_independent() -> None:
    admin_url = make_url(os.environ["KJDS_COM002_TEST_POSTGRES_URL"])
    schema = f"com002_{uuid4().hex}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    target_url = admin_url.set(query={"options": f"-csearch_path={schema}"})
    engine = create_engine(target_url, pool_size=8, max_overflow=0)
    event_table = Base.metadata.tables["commercial_lifecycle_events"]
    evidence_table = Base.metadata.tables["commercial_lifecycle_evidence"]
    Base.metadata.create_all(engine, tables=[event_table, evidence_table])
    try:
        service = CommercialLifecycleService(engine)
        scope_a = _commercial_scope()
        scope_b = _commercial_scope(
            customer_ref="customer-b",
            deployment_ref="deploy-b",
            tenant_ref="tenant-b",
            entity_ref="entity-b",
            store_ref="store-b",
        )
        _seed_commercial_subscription(service, scope_a, prefix="pg-a")
        _seed_commercial_subscription(service, scope_b, prefix="pg-b")
        _record_commercial_invoice(service, scope_a, prefix="pg-a", invoice_ref="inv-pg-a")
        _record_commercial_invoice(service, scope_b, prefix="pg-b", invoice_ref="inv-pg-b")

        barrier = Barrier(2)

        def settle(payment_ref: str) -> tuple[str, str]:
            barrier.wait(timeout=10)
            try:
                _record_commercial_payment(
                    service,
                    scope_a,
                    invoice_ref="inv-pg-a",
                    payment_ref=payment_ref,
                    amount="70",
                    state="settled",
                )
            except ValueError:
                return "blocked", payment_ref
            return "recorded", payment_ref

        with ThreadPoolExecutor(max_workers=2) as executor:
            settlement_results = list(executor.map(settle, ("pay-pg-a-1", "pay-pg-a-2")))
        assert sorted(result for result, _ in settlement_results) == ["blocked", "recorded"]
        winner_payment_ref = next(ref for result, ref in settlement_results if result == "recorded")

        barrier = Barrier(2)

        def refund(refund_ref: str) -> str:
            barrier.wait(timeout=10)
            try:
                _record_commercial_refund(
                    service,
                    scope_a,
                    invoice_ref="inv-pg-a",
                    payment_ref=winner_payment_ref,
                    refund_ref=refund_ref,
                    amount="50",
                    state="paid",
                )
            except ValueError:
                return "blocked"
            return "recorded"

        with ThreadPoolExecutor(max_workers=2) as executor:
            refund_results = list(executor.map(refund, ("refund-pg-a-1", "refund-pg-a-2")))
        assert sorted(refund_results) == ["blocked", "recorded"]

        scoped_a = service._scope(**scope_a)
        scoped_b = service._scope(**scope_b)
        with Session(engine) as session_a, session_a.begin():
            service._lock_scope_write(session_a, scope=scoped_a)
            with Session(engine) as session_b, session_b.begin():
                assert session_b.scalar(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(:scope_hash))"),
                    {"scope_hash": scoped_b.scope_hash},
                ) is True

        snapshot = service.snapshot(**scope_a)
        _assert_entitlement(
            snapshot,
            state="grace",
            reason="outstanding_balance",
            invoice_total="100",
            payment_total="70",
            refund_total="50",
            outstanding_total="80",
        )
        business_event_times = [
            event["recorded_at"]
            for event in snapshot["events"]
            if event["lifecycle_kind"] != "entitlement"
        ]
        assert business_event_times == sorted(set(business_event_times))
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin_engine.dispose()


def test_missing_invoice_amount_fails_closed_before_payment_write():
    engine = _commercial_engine()
    service = CommercialLifecycleService(engine)
    scope = _commercial_scope()
    _seed_commercial_subscription(service, scope, prefix="missing-amount")
    _record_commercial_invoice(
        service,
        scope,
        prefix="missing-amount",
        invoice_ref="inv-missing-amount",
    )
    with Session(engine) as session, session.begin():
        invoice = session.scalar(
            select(CommercialLifecycleEventRow).where(
                CommercialLifecycleEventRow.lifecycle_kind == "invoice",
                CommercialLifecycleEventRow.record_ref == "inv-missing-amount",
            )
        )
        assert invoice is not None
        invoice.amount = None

    with pytest.raises(ValueError, match="invoice gross amount must be positive"):
        _record_commercial_payment(
            service,
            scope,
            invoice_ref="inv-missing-amount",
            payment_ref="pay-missing-amount",
            amount="100",
            state="settled",
        )
    assert service.snapshot(**scope)["payment_attempts"] == []
