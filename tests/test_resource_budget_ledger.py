from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.exc import IntegrityError
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
    @sqlalchemy_event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    Base.metadata.create_all(engine, tables=[ResourceBudgetRow.__table__, ResourceBudgetEventRow.__table__])
    return ResourceBudgetLedger(engine)


def event(state: str, amount: str, key: str, event_id: str, *, budget_id: str = "budget-1", parent: str | None = None):
    return ResourceBudgetEvent(
        event_id=event_id,
        idempotency_key=key,
        budget_id=budget_id,
        tenant_id="tenant-a",
        state=state,
        amount=Decimal(amount),
        currency="usd",
        parent_event_id=parent,
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
    )


def test_budget_reservation_consumption_release_and_overrun(ledger):
    ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "model_tokens", "cc-ai", Decimal("10")))
    ledger.record(event("reserved", "4", "r1", "e1"))
    ledger.record(event("consumed", "3", "c1", "e2", budget_id="budget-1", parent="e1"))
    ledger.record(event("released", "1", "l1", "e3", parent="e1"))
    ledger.record(event("overrun", "2", "o1", "e4"))
    snap = ledger.snapshot(tenant_id="tenant-a", budget_id="budget-1")
    assert snap["reserved"] == "4"
    assert snap["consumed"] == "3"
    assert snap["released"] == "1"
    assert snap["overrun"] == "2"
    assert snap["available"] == "5"
    assert ledger.record(event("overrun", "2", "o1", "e4")) == event("overrun", "2", "o1", "e4")


def test_reservation_cannot_exceed_budget_or_cross_tenant(ledger):
    ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "media", "cc-media", Decimal("5")))
    with pytest.raises(ValueError, match="exceeded"):
        ledger.record(event("reserved", "6", "r1", "e1"))
    with pytest.raises(KeyError, match="exact tenant scope"):
        ledger.snapshot(tenant_id="tenant-b", budget_id="budget-1")


def test_idempotent_retry_returns_persisted_event_identity(ledger):
    ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "model_tokens", "cc-ai", Decimal("5")))
    first = ledger.record(event("reserved", "1", "same-key", "stored"))
    retry = ledger.record(event("reserved", "1", "same-key", "client-retry"))
    assert retry.event_id == first.event_id == "stored"


def test_numeric_precision_is_bounded_before_persistence(ledger):
    with pytest.raises(ValueError, match="NUMERIC"):
        ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "model_tokens", "cc-ai", Decimal("0.1234567890123456789")))


def test_database_rejects_orphan_budget_event(ledger):
    with pytest.raises(IntegrityError):
        with ledger.engine.begin() as connection:
            connection.execute(ResourceBudgetEventRow.__table__.insert().values(
                event_id="orphan", idempotency_key="orphan-key", budget_id="missing",
                tenant_id="tenant-a", state="reserved", amount=Decimal("1"),
                amount_text="1", currency="USD", occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
                fingerprint_sha256="0" * 64, recorded_at=datetime(2026, 9, 6, tzinfo=UTC),
            ))
