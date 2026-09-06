from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.pool import StaticPool

from apps.control_plane.resource_admission import (
    ResourceAdmissionEventRow,
    ResourceAdmissionService,
)
from apps.control_plane.resource_budget_ledger import (
    ResourceBudget,
    ResourceBudgetEventRow,
    ResourceBudgetLedger,
    ResourceBudgetRow,
)
from apps.control_plane.sql_repository import Base


@pytest.fixture
def admission():
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

    Base.metadata.create_all(
        engine,
        tables=[
            ResourceBudgetRow.__table__,
            ResourceBudgetEventRow.__table__,
            ResourceAdmissionEventRow.__table__,
        ],
    )
    ledger = ResourceBudgetLedger(engine)
    ledger.create_budget(
        ResourceBudget(
            budget_id="budget-1",
            tenant_id="tenant-a",
            resource_type="model_tokens",
            cost_center="cc-ai",
            limit_amount=Decimal("10"),
        )
    )
    return ResourceAdmissionService(engine, ledger=ledger)


def _reserve(service: ResourceAdmissionService, *, key="reserve-1"):
    return service.reserve(
        tenant_id="tenant-a",
        command_id="command-1",
        action_id="listing_publish",
        permit_ref="permit-sha256",
        budget_id="budget-1",
        amount=Decimal("4"),
        currency="USD",
        idempotency_key=key,
        occurred_at=datetime.now(UTC) - timedelta(seconds=1),
    )


def test_reserve_persists_exact_command_action_and_permit_binding(admission):
    result = _reserve(admission)

    assert result["status"] == "reserved"
    assert result["amount"] == "4"
    assert result["remaining_amount"] == "4"
    assert result["command_id"] == "command-1"
    assert result["action_id"] == "listing_publish"
    assert result["permit_ref"] == "permit-sha256"
    assert result["reservation_event_id"]
    assert admission.for_command("command-1")["admission_id"] == result["admission_id"]


def test_consume_is_idempotent_and_settles_ledger(admission):
    reservation = _reserve(admission)
    consumed = admission.consume(
        reservation["admission_id"],
        tenant_id="tenant-a",
        command_id="command-1",
        action_id="listing_publish",
        permit_ref="permit-sha256",
        idempotency_key="consume-1",
    )
    retry = admission.consume(
        reservation["admission_id"],
        tenant_id="tenant-a",
        command_id="command-1",
        action_id="listing_publish",
        permit_ref="permit-sha256",
        idempotency_key="consume-1",
    )

    assert consumed["status"] == retry["status"] == "consumed"
    assert consumed["settled_amount"] == "4"
    assert consumed["remaining_amount"] == "0"
    assert len(consumed["settlement_event_ids"]) == 1
    assert admission.ledger.snapshot(tenant_id="tenant-a", budget_id="budget-1")["available"] == "6"


def test_release_returns_capacity_and_binding_mismatch_is_rejected(admission):
    reservation = _reserve(admission)
    with pytest.raises(ValueError, match="permit_ref binding"):
        admission.release(
            reservation["admission_id"],
            tenant_id="tenant-a",
            permit_ref="different-permit",
        )

    released = admission.release(
        reservation["admission_id"],
        tenant_id="tenant-a",
        idempotency_key="release-1",
    )
    assert released["status"] == "released"
    assert released["remaining_amount"] == "0"
    assert admission.ledger.snapshot(tenant_id="tenant-a", budget_id="budget-1")["available"] == "10"


def test_unknown_hold_keeps_reservation_open_until_reconciliation(admission):
    reservation = _reserve(admission)
    unknown = admission.hold_unknown(
        reservation["admission_id"],
        tenant_id="tenant-a",
        reason="remote response was unavailable",
        idempotency_key="unknown-1",
    )
    retry = admission.hold_unknown(
        reservation["admission_id"],
        tenant_id="tenant-a",
        reason="remote response was unavailable",
        idempotency_key="unknown-1",
    )
    assert unknown["status"] == retry["status"] == "unknown"
    assert unknown["unknown_reason"] == "remote response was unavailable"
    assert unknown["remaining_amount"] == "4"
    # A later authoritative reconciliation can settle the held reservation.
    settled = admission.release(
        reservation["admission_id"],
        tenant_id="tenant-a",
        idempotency_key="release-after-unknown",
    )
    assert settled["status"] == "released"
    assert admission.ledger.snapshot(tenant_id="tenant-a", budget_id="budget-1")["available"] == "10"


def test_tenant_scope_and_future_time_are_fail_closed(admission):
    reservation = _reserve(admission)
    with pytest.raises(KeyError, match="exact tenant scope"):
        admission.get(reservation["admission_id"], tenant_id="tenant-b")
    with pytest.raises(ValueError, match="future"):
        admission.reserve(
            tenant_id="tenant-a",
            command_id="command-future",
            action_id="listing_publish",
            permit_ref="permit-sha256",
            budget_id="budget-1",
            amount="1",
            idempotency_key="future-reserve",
            occurred_at=datetime.now(UTC) + timedelta(minutes=1),
        )


def test_terminal_admission_cannot_be_settled_twice(admission):
    reservation = _reserve(admission)
    admission.consume(reservation["admission_id"], tenant_id="tenant-a")
    with pytest.raises(ValueError, match="terminal resource admission"):
        admission.release(
            reservation["admission_id"],
            tenant_id="tenant-a",
            idempotency_key="release-after-consume",
        )
