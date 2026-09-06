from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from apps.control_plane.skill_usage_ledger import (
    SkillUsageEvent,
    _legacy_usage_fingerprint,
)
from apps.control_plane.skill_usage_sql import (
    SkillUsageEntitlementLinkRow,
    SkillUsageEventRow,
    SqlSkillUsageLedger,
)


def _event(
    key: str = "usage-key",
    *,
    event_id: str = "usage-event",
    tenant_id: str = "tenant-a",
    customer_id: str = "customer-a",
    receipt_ref: str | None = "receipt-a",
) -> SkillUsageEvent:
    return SkillUsageEvent(
        event_id=event_id,
        idempotency_key=key,
        tenant_id=tenant_id,
        customer_id=customer_id,
        skill_id="image.generate",
        units=Decimal("2"),
        unit_cost=Decimal("0.25"),
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
        entitlement_receipt_ref=receipt_ref,
    )


def test_explicit_usage_writes_one_immutable_receipt_binding_and_replays() -> None:
    store = SqlSkillUsageLedger.for_url("sqlite://")

    first = store.record(_event())
    retry = store.record(replace(_event(), event_id="transport-retry"))

    assert retry == first
    with Session(store.engine) as session:
        links = session.scalars(select(SkillUsageEntitlementLinkRow)).all()
    assert len(links) == 1
    link = links[0]
    assert link.usage_event_id == first.event_id
    assert link.tenant_id == first.tenant_id
    assert link.customer_id == first.customer_id
    assert link.idempotency_key == first.idempotency_key
    assert link.entitlement_receipt_ref == "receipt-a"
    assert len(link.fingerprint_sha256) == 64


def test_receipt_ref_is_part_of_idempotency_and_scope_cannot_replay_another_tenant() -> None:
    store = SqlSkillUsageLedger.for_url("sqlite://")
    store.record(_event())

    with pytest.raises(ValueError, match="idempotency"):
        store.record(
            replace(
                _event(),
                event_id="drift",
                entitlement_receipt_ref="receipt-b",
            )
        )
    with pytest.raises(ValueError, match="idempotency"):
        store.record(
            replace(
                _event(),
                event_id="customer-drift",
                customer_id="customer-b",
            )
        )

    other_tenant = store.record(
        replace(
            _event(),
            event_id="tenant-b-event",
            tenant_id="tenant-b",
        )
    )
    assert other_tenant.event_id == "tenant-b-event"
    assert other_tenant.tenant_id == "tenant-b"
    with Session(store.engine) as session:
        links = session.scalars(
            select(SkillUsageEntitlementLinkRow).order_by(
                SkillUsageEntitlementLinkRow.tenant_id
            )
        ).all()
    assert [(item.tenant_id, item.usage_event_id) for item in links] == [
        ("tenant-a", "usage-event"),
        ("tenant-b", "tenant-b-event"),
    ]


def test_binding_tamper_is_detected_on_read() -> None:
    store = SqlSkillUsageLedger.for_url("sqlite://")
    stored = store.record(_event())
    with Session(store.engine) as session, session.begin():
        session.execute(
            update(SkillUsageEntitlementLinkRow)
            .where(SkillUsageEntitlementLinkRow.usage_event_id == stored.event_id)
            .values(entitlement_receipt_ref="forged")
        )

    with pytest.raises(ValueError, match="binding conflicts"):
        store.get(stored.event_id)


def test_legacy_usage_remains_unbound_and_compatible() -> None:
    store = SqlSkillUsageLedger.for_url("sqlite://")
    stored = store.record(_event(receipt_ref=None))

    assert stored.entitlement_receipt_ref is None
    with Session(store.engine) as session:
        assert session.scalars(select(SkillUsageEntitlementLinkRow)).all() == []


def test_pre_binding_legacy_digest_can_still_replay_after_migration() -> None:
    store = SqlSkillUsageLedger.for_url("sqlite://")
    event = _event(receipt_ref=None)
    first = store.record(event)
    with Session(store.engine) as session, session.begin():
        session.execute(
            update(SkillUsageEventRow)
            .where(SkillUsageEventRow.event_id == first.event_id)
            .values(fingerprint_sha256=_legacy_usage_fingerprint(event))
        )
    assert store.record(replace(event, event_id="legacy-retry")) == first
