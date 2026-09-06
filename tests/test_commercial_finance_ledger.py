from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from apps.control_plane.commercial_finance_ledger import (
    CommercialFinanceEvent,
    CommercialFinanceEventRow,
    CommercialFinanceLedger,
)
from apps.control_plane.sql_repository import Base


@pytest.fixture
def ledger():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[CommercialFinanceEventRow.__table__])
    return CommercialFinanceLedger(engine), engine


def event(*, event_id: str, key: str, kind: str, amount: str, tenant: str = "tenant-a"):
    return CommercialFinanceEvent(
        event_id=event_id,
        idempotency_key=key,
        tenant_id=tenant,
        customer_id="customer-1",
        contract_id="contract-1",
        entitlement_id="entitlement-1",
        event_kind=kind,
        amount=Decimal(amount),
        currency="usd",
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
    )


def test_events_are_tenant_scoped_idempotent_and_summarizable(ledger):
    service, engine = ledger
    first = service.record(event(event_id="e1", key="k1", kind="token_cost", amount="1.25"))
    assert service.record(event(event_id="e1", key="k1", kind="token_cost", amount="1.25")) == first
    service.record(event(event_id="e2", key="k2", kind="asset_cost", amount="2.75"))
    service.record(event(event_id="other", key="k1", kind="revenue_share", amount="9", tenant="tenant-b"))
    summary = service.summary(tenant_id="tenant-a", customer_id="customer-1")
    assert summary["event_count"] == 2
    assert summary["totals"]["token_cost"] == "1.25"
    assert summary["totals"]["asset_cost"] == "2.75"
    assert summary["total"] == "4.00"
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(CommercialFinanceEventRow)) == 3


def test_invalid_kind_and_idempotency_drift_fail_closed(ledger):
    service, _engine = ledger
    with pytest.raises(ValueError, match="allowlisted"):
        service.record(event(event_id="bad", key="bad", kind="unknown", amount="1"))
    service.record(event(event_id="e1", key="k1", kind="token_cost", amount="1"))
    with pytest.raises(ValueError, match="conflicts"):
        service.record(event(event_id="e2", key="k1", kind="token_cost", amount="2"))
