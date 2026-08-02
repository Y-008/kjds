from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from apps.control_plane.commercial_lifecycle import CommercialLifecycleKernel, CommercialLifecycleService
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

    with pytest.raises(ValueError, match="refund amount must not exceed collected payment"):
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
