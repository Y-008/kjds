from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.resource_budget_ledger import (
    ResourceBudget,
    ResourceBudgetEvent,
    ResourceBudgetEventRow,
    ResourceBudgetLedger,
    ResourceBudgetRow,
)
from apps.control_plane.sql_repository import Base


@pytest.fixture
def ledger():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[ResourceBudgetRow.__table__, ResourceBudgetEventRow.__table__])
    return ResourceBudgetLedger(engine)


def event(state: str, amount: str, key: str, event_id: str, *, budget_id: str = "budget-1"):
    return ResourceBudgetEvent(
        event_id=event_id,
        idempotency_key=key,
        budget_id=budget_id,
        tenant_id="tenant-a",
        state=state,
        amount=Decimal(amount),
        currency="usd",
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
    )


def test_budget_reservation_consumption_release_and_overrun(ledger):
    ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "model_tokens", "cc-ai", Decimal("10")))
    ledger.record(event("reserved", "4", "r1", "e1"))
    ledger.record(event("consumed", "3", "c1", "e2", budget_id="budget-1"))
    ledger.record(event("released", "1", "l1", "e3"))
    ledger.record(event("overrun", "2", "o1", "e4"))
    snap = ledger.snapshot(tenant_id="tenant-a", budget_id="budget-1")
    assert snap["reserved"] == "4"
    assert snap["consumed"] == "3"
    assert snap["released"] == "1"
    assert snap["overrun"] == "2"
    assert snap["available"] == "2"
    assert ledger.record(event("overrun", "2", "o1", "e4")) == event("overrun", "2", "o1", "e4")


def test_reservation_cannot_exceed_budget_or_cross_tenant(ledger):
    ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "media", "cc-media", Decimal("5")))
    with pytest.raises(ValueError, match="exceeded"):
        ledger.record(event("reserved", "6", "r1", "e1"))
    with pytest.raises(KeyError, match="exact tenant scope"):
        ledger.snapshot(tenant_id="tenant-b", budget_id="budget-1")
