from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from apps.control_plane.commercial_entitlement_authority import (
    CommercialEntitlementAdmissionError,
    CommercialEntitlementAuthority,
    canonical_entitlement_id,
)
from apps.control_plane.commercial_lifecycle import (
    CommercialLifecycleEventRow,
    CommercialLifecycleEvidenceRow,
    CommercialLifecycleService,
    CommercialScope,
)
from apps.control_plane.sql_repository import Base

SCOPE = {
    "tenant_id": "tenant-a",
    "customer_id": "customer-a",
    "deployment_ref": "deployment-a",
    "entity_ref": "entity-a",
    "store_ref": "store-a",
}
_NOW = datetime.now(UTC)
START = _NOW - timedelta(days=30)
END = _NOW - timedelta(days=1)


def _snapshot(*, state: str = "active", plan_state: str = "approved", metric_limits=None):
    scope = {
        "customer_ref": SCOPE["customer_id"],
        "deployment_ref": SCOPE["deployment_ref"],
        "tenant_ref": SCOPE["tenant_id"],
        "entity_ref": SCOPE["entity_ref"],
        "store_ref": SCOPE["store_ref"],
    }
    scope_hash = CommercialScope(
        customer_ref=scope["customer_ref"],
        deployment_ref=scope["deployment_ref"],
        tenant_ref=scope["tenant_ref"],
        entity_ref=scope["entity_ref"],
        store_ref=scope["store_ref"],
    ).scope_hash
    return {
            "scope": scope,
        "scope_hash": scope_hash,
        "plan": {
            "record_ref": "plan-a",
            "state": plan_state,
            "payload": {
                "effective_at": START.isoformat(),
                "billing_window_start": START.isoformat(),
                "billing_window_end": END.isoformat(),
                "metric_limits": metric_limits
                or [{"metric": "requests", "limit": "10", "grace_limit": "8"}],
            },
        },
        "entitlement": {
            "id": "commercial-entitlement-event-a",
            "record_ref": "entitlement",
            "state": state,
            "decision_sha256": "a" * 64,
            "payload": {"subscription_ref": "subscription-a"},
        },
        "subscription": {
            "record_ref": "subscription-a",
            "state": "active",
            "payload": {"effective_at": START.isoformat(), "expires_at": None},
        },
    }


class FakeLifecycle:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.calls: list[dict[str, object]] = []

    def snapshot(self, **kwargs):
        self.calls.append(kwargs)
        return self._snapshot


def _authority(snapshot=None):
    return CommercialEntitlementAuthority(FakeLifecycle(snapshot or _snapshot()))


def _resolve(authority, **changes):
    values = {
        **SCOPE,
        "entitlement_id": canonical_entitlement_id(**SCOPE),
        "occurred_at": START + timedelta(hours=1),
        "metric": "requests",
    }
    values.update(changes)
    return authority.resolve(**values)


def test_resolve_returns_exact_scope_and_auditable_receipt():
    authority = _authority()

    receipt = _resolve(authority)

    assert receipt["entitlement_id"] == canonical_entitlement_id(**SCOPE)
    assert receipt["scope"]["tenant_ref"] == "tenant-a"
    assert receipt["metric_limit"] == "10"
    assert receipt["metric_grace_limit"] == "8"
    assert len(receipt["receipt_sha256"]) == 64


def test_arbitrary_or_cross_tenant_entitlement_id_is_rejected_before_lookup():
    lifecycle = FakeLifecycle(_snapshot())
    authority = CommercialEntitlementAuthority(lifecycle)

    with pytest.raises(CommercialEntitlementAdmissionError, match="exact commercial scope"):
        _resolve(authority, entitlement_id="customer-a-entitlement")
    assert lifecycle.calls == []

    with pytest.raises(CommercialEntitlementAdmissionError, match="exact commercial scope"):
        _resolve(
            authority,
            tenant_id="tenant-b",
            entitlement_id=canonical_entitlement_id(**SCOPE),
        )
    assert lifecycle.calls == []


def test_expired_window_and_restricted_state_fail_closed():
    authority = _authority()

    with pytest.raises(CommercialEntitlementAdmissionError, match="outside.*billing window"):
        _resolve(authority, occurred_at=END)

    with pytest.raises(CommercialEntitlementAdmissionError, match="does not permit usage"):
        _resolve(_authority(_snapshot(state="read_only")))


def test_multiple_metrics_require_an_explicit_allowlisted_metric():
    snapshot = _snapshot(
        metric_limits=[
            {"metric": "requests", "limit": "10", "grace_limit": "8"},
            {"metric": "seats", "limit": "2", "grace_limit": "1"},
        ]
    )
    authority = _authority(snapshot)

    with pytest.raises(CommercialEntitlementAdmissionError, match="metric is required"):
        _resolve(authority, metric=None)
    with pytest.raises(CommercialEntitlementAdmissionError, match="not allowlisted"):
        _resolve(authority, metric="storage_gib")


def test_sql_lifecycle_projection_is_the_authoritative_resolution_source():
    engine = create_engine("sqlite+pysqlite://", future=True)
    Base.metadata.create_all(
        engine,
        tables=[CommercialLifecycleEventRow.__table__, CommercialLifecycleEvidenceRow.__table__],
    )
    service = CommercialLifecycleService(engine)
    scope = {
        "customer_ref": SCOPE["customer_id"],
        "deployment_ref": SCOPE["deployment_ref"],
        "tenant_ref": SCOPE["tenant_id"],
        "entity_ref": SCOPE["entity_ref"],
        "store_ref": SCOPE["store_ref"],
    }

    def evidence(evidence_id: str, suffix: str):
        return {
            "evidence_id": evidence_id,
            "evidence_sha256": suffix * 64,
            "evidence_kind": "commercial_test",
            "authority": "test",
            "source_kind": "internal_record_only",
            "purposes": ["commercial_audit"],
        }

    service.record_plan(
        scope=scope,
        plan_ref="plan-authority",
        state="approved",
        currency="CNY",
        gross_amount="100",
        effective_at=START,
        billing_window_start=START,
        billing_window_end=END + timedelta(days=2),
        metric_limits=[{"metric": "requests", "limit": "10", "grace_limit": "8"}],
        evidence=evidence("plan-evidence", "a"),
        idempotency_key="plan-authority",
    )
    service.record_subscription(
        scope=scope,
        subscription_ref="subscription-authority",
        plan_ref="plan-authority",
        state="active",
        currency="CNY",
        amount="100",
        effective_at=START,
        expires_at=None,
        settlement_evidence=evidence("settlement-evidence", "b"),
        evidence=evidence("subscription-evidence", "c"),
        idempotency_key="subscription-authority",
    )

    authority = CommercialEntitlementAuthority(service)
    receipt = authority.resolve(
        **SCOPE,
        entitlement_id=canonical_entitlement_id(**SCOPE),
        metric="requests",
        occurred_at=START + timedelta(hours=1),
    )
    assert receipt["plan_ref"] == "plan-authority"
    assert receipt["subscription_ref"] == "subscription-authority"
    assert receipt["state"] == "active"
    engine.dispose()
