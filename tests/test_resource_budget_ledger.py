from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy import event as sqlalchemy_event
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
    # Trailing zeroes are harmless, while a 20-digit integer plus 18 decimal
    # places is the largest value representable by NUMERIC(38,18).
    ledger.create_budget(ResourceBudget(
        "budget-2", "tenant-a", "model_tokens", "cc-ai",
        Decimal("99999999999999999999.999999999999999999"),
    ))
    ledger.create_budget(ResourceBudget("budget-zero", "tenant-a", "model_tokens", "cc-ai", Decimal("0E+20")))
    precise_limit = Decimal("1000.000000000000000000")
    ledger.create_budget(ResourceBudget("budget-precise", "tenant-a", "model_tokens", "cc-ai", precise_limit))
    ledger.record(event("reserved", "999.999999995000000000", "p1", "p1", budget_id="budget-precise"))
    with pytest.raises(ValueError, match="exceeded"):
        ledger.record(event("reserved", "0.000000007", "p2", "p2", budget_id="budget-precise"))


def test_metadata_is_copied_and_validated():
    metadata = {"z": "2", "a": "1"}
    created = ResourceBudgetEvent(
        event_id="meta-event", idempotency_key="meta-key", budget_id="budget-1",
        tenant_id="tenant-a", state="reserved", amount="1", metadata=metadata,
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    metadata["z"] = "changed"
    assert dict(created.metadata or {}) == {"a": "1", "z": "2"}
    with pytest.raises(ValueError, match="metadata"):
        ResourceBudgetEvent(
            event_id="bad-meta", idempotency_key="bad-meta-key", budget_id="budget-1",
            tenant_id="tenant-a", state="reserved", amount="1", metadata={1: "x"},
            occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
        )


def test_event_rejects_malformed_state_and_timestamp():
    with pytest.raises(ValueError, match="state"):
        ResourceBudgetEvent(
            event_id="bad-state", idempotency_key="bad-state-key", budget_id="budget-1",
            tenant_id="tenant-a", state=[], amount="1",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="occurred_at"):
        ResourceBudgetEvent(
            event_id="bad-time", idempotency_key="bad-time-key", budget_id="budget-1",
            tenant_id="tenant-a", state="reserved", amount="1", occurred_at=None,  # type: ignore[arg-type]
        )


def test_overrun_cannot_be_attached_to_a_reservation(ledger):
    ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "model_tokens", "cc-ai", Decimal("5")))
    ledger.record(event("reserved", "1", "r1", "e1"))
    with pytest.raises(ValueError, match="standalone"):
        ledger.record(event("overrun", "1", "o1", "e2", parent="e1"))


@pytest.mark.parametrize("state", ["consumed", "released"])
def test_settlement_requires_parent_reservation(ledger, state):
    ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "model_tokens", "cc-ai", Decimal("5")))
    with pytest.raises(ValueError, match="requires a parent"):
        ledger.record(event(state, "1", f"{state}-key", f"{state}-event"))


def test_settlement_parent_must_be_reserved(ledger):
    ledger.create_budget(ResourceBudget("budget-1", "tenant-a", "model_tokens", "cc-ai", Decimal("5")))
    ledger.record(event("overrun", "1", "overrun-key", "overrun-event"))
    with pytest.raises(ValueError, match="parent must be reserved"):
        ledger.record(event(
            "consumed", "1", "consumed-key", "consumed-event", parent="overrun-event"
        ))


def test_database_rejects_invalid_parent_shapes(ledger):
    ledger.create_budget(ResourceBudget("budget-parent-shape", "tenant-a", "model_tokens", "cc-ai", Decimal("5")))
    ledger.record(event("reserved", "1", "parent-shape-parent", "parent-shape-parent-event", budget_id="budget-parent-shape"))
    with pytest.raises(IntegrityError), ledger.engine.begin() as connection:
        connection.execute(ResourceBudgetEventRow.__table__.insert().values(
            event_id="invalid-overrun-parent", idempotency_key="invalid-overrun-parent-key",
            budget_id="budget-parent-shape", tenant_id="tenant-a", state="overrun", amount=Decimal("1"),
            amount_text="1", currency="USD", parent_event_id="parent-shape-parent-event",
            occurred_at=datetime(2026, 9, 6, tzinfo=UTC), fingerprint_sha256="0" * 64,
            recorded_at=datetime(2026, 9, 6, tzinfo=UTC),
        ))
    with pytest.raises(IntegrityError), ledger.engine.begin() as connection:
        connection.execute(ResourceBudgetEventRow.__table__.insert().values(
            event_id="invalid-consumed-parent", idempotency_key="invalid-consumed-parent-key",
            budget_id="budget-parent-shape", tenant_id="tenant-a", state="consumed", amount=Decimal("1"),
            amount_text="1", currency="USD", parent_event_id=None,
            occurred_at=datetime(2026, 9, 6, tzinfo=UTC), fingerprint_sha256="0" * 64,
            recorded_at=datetime(2026, 9, 6, tzinfo=UTC),
        ))


def test_database_rejects_orphan_budget_event(ledger):
    with pytest.raises(IntegrityError), ledger.engine.begin() as connection:
        connection.execute(ResourceBudgetEventRow.__table__.insert().values(
            event_id="orphan", idempotency_key="orphan-key", budget_id="missing",
            tenant_id="tenant-a", state="reserved", amount=Decimal("1"),
            amount_text="1", currency="USD", occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
            fingerprint_sha256="0" * 64, recorded_at=datetime(2026, 9, 6, tzinfo=UTC),
        ))


def test_snapshot_rejects_corrupt_persisted_amount(ledger):
    ledger.create_budget(ResourceBudget("budget-corrupt", "tenant-a", "model_tokens", "cc-ai", Decimal("5")))
    with ledger.engine.begin() as connection:
        connection.execute(ResourceBudgetEventRow.__table__.insert().values(
            event_id="corrupt", idempotency_key="corrupt-key", budget_id="budget-corrupt",
            tenant_id="tenant-a", state="reserved", amount=Decimal("1"), amount_text="NaN",
            currency="USD", occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
            fingerprint_sha256="0" * 64, recorded_at=datetime(2026, 9, 6, tzinfo=UTC),
        ))
    with pytest.raises(ValueError, match="integrity"):
        ledger.snapshot(tenant_id="tenant-a", budget_id="budget-corrupt")


def test_ledger_rejects_future_event_time(ledger):
    ledger.create_budget(ResourceBudget("budget-future", "tenant-a", "model_tokens", "cc-ai", Decimal("5")))
    with pytest.raises(ValueError, match="future"):
        ledger.record(ResourceBudgetEvent(
            event_id="future", idempotency_key="future-key", budget_id="budget-future",
            tenant_id="tenant-a", state="reserved", amount="1",
            occurred_at=datetime.now(UTC) + timedelta(days=1),
        ))


def test_event_rejects_unrepresentable_timezone_offset():
    with pytest.raises(ValueError, match="outside the supported range"):
        ResourceBudgetEvent(
            event_id="overflow", idempotency_key="overflow-key", budget_id="budget-1",
            tenant_id="tenant-a", state="reserved", amount="1",
            occurred_at=datetime.max.replace(tzinfo=timezone(timedelta(hours=-14))),
        )
