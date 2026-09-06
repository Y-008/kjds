from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from apps.control_plane.skill_usage_ledger import SkillUsageEvent
from apps.control_plane.skill_usage_sql import (
    SkillUsageEventRow,
    SqlSkillUsageLedger,
)
from apps.control_plane.sql_repository import Base


def _event(
    key: str,
    *,
    event_id: str = "usage-1",
    tenant_id: str = "tenant-1",
    occurred_at: datetime | None = None,
) -> SkillUsageEvent:
    return SkillUsageEvent(
        event_id=event_id,
        idempotency_key=key,
        tenant_id=tenant_id,
        customer_id="customer-1",
        skill_id="image.generate",
        units=Decimal("2"),
        unit_cost=Decimal("0.25"),
        currency="USD",
        occurred_at=occurred_at or datetime(2026, 9, 6, tzinfo=UTC),
        asset_ref="asset-1",
    )


def _store() -> SqlSkillUsageLedger:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[SkillUsageEventRow.__table__])
    return SqlSkillUsageLedger(engine)


def test_sql_usage_is_durable_and_idempotent():
    store = _store()
    first = store.record(_event("key-1"))

    # A new adapter instance sees the committed event and returns the original
    # winner even when a retry chooses a different transport event id.
    restarted = SqlSkillUsageLedger(store.engine)
    assert restarted.record(_event("key-1", event_id="retry-id")) == first
    assert restarted.get(first.event_id) == first
    assert restarted.total_cost(tenant_id="tenant-1", customer_id="customer-1") == Decimal(
        "0.50"
    )
    assert restarted.invoice_preview(
        tenant_id="tenant-1", customer_id="customer-1"
    ) == {
        "tenant_id": "tenant-1",
        "customer_id": "customer-1",
        "currency": "USD",
        "event_count": 1,
        "total_cost": "0.50",
        "event_ids": ["usage-1"],
    }


def test_sql_usage_conflicts_are_immutable_and_idempotency_is_tenant_scoped():
    store = _store()
    store.record(_event("shared-key"))

    with pytest.raises(ValueError, match="idempotency"):
        store.record(replace(_event("shared-key", event_id="usage-2"), units=Decimal("3")))
    with pytest.raises(ValueError, match="event_id"):
        store.record(_event("different-key", event_id="usage-1"))

    # The same request key is independent in another tenant and cannot reveal
    # or replay the first tenant's event.
    other = store.record(_event("shared-key", event_id="usage-3", tenant_id="tenant-2"))
    assert other.tenant_id == "tenant-2"
    assert [event.event_id for event in store.events_for(tenant_id="tenant-1")] == [
        "usage-1"
    ]
    assert [event.event_id for event in store.events_for(tenant_id="tenant-2")] == [
        "usage-3"
    ]


def test_sql_usage_orders_by_occurrence_and_rejects_mixed_currency():
    store = _store()
    store.record(
        _event(
            "late",
            event_id="usage-late",
            occurred_at=datetime(2026, 9, 7, tzinfo=UTC),
        )
    )
    store.record(
        replace(
            _event("early", event_id="usage-early"),
            occurred_at=datetime(2026, 9, 5, tzinfo=UTC),
        )
    )
    assert [event.event_id for event in store.events_for(tenant_id="tenant-1")] == [
        "usage-early",
        "usage-late",
    ]
    store.record(
        replace(
            _event("cny", event_id="usage-cny"),
            currency="CNY",
            occurred_at=datetime(2026, 9, 8, tzinfo=UTC),
        )
    )
    with pytest.raises(ValueError, match="mixed currencies"):
        store.total_cost(tenant_id="tenant-1", customer_id="customer-1")


def test_sql_usage_for_url_creates_only_its_table():
    store = SqlSkillUsageLedger.for_url("sqlite://")
    assert store.engine.dialect.name == "sqlite"
    assert store.record(_event("for-url")).event_id == "usage-1"


def test_sql_usage_preserves_resource_and_token_dimensions():
    store = _store()
    event = replace(
        _event("token-1"),
        resource_type="token",
        provider_ref="provider-a",
        model_ref="model-a",
        cost_center="media-generation",
        input_units=Decimal("120"),
        output_units=Decimal("80"),
    )
    stored = store.record(event)
    assert stored.resource_type == "token"
    assert stored.model_ref == "model-a"
    assert stored.input_units == Decimal("120")
    assert stored.output_units == Decimal("80")
