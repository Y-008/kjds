from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.after_sales_ledger import (
    AfterSalesEventKind,
    AfterSalesLedgerError,
    AfterSalesLedgerService,
)
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base


def _services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine).capture(
        content=b"after-sales-source",
        filename="after-sales.json",
        content_type="application/json",
        source="ozon-after-sales",
        source_ref="return-1",
        grade=EvidenceGrade.A,
        effective_at="2026-07-01T00:00:00+00:00",
        effective_until=None,
        created_by="source-reviewer",
    )
    # Keep the fixture's observation in the historical window used by replay.
    # Production Evidence capture normally records this at ingestion time.
    from apps.control_plane.evidence import EvidenceRecordRow

    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, evidence.id)
        assert row is not None
        row.recorded_at = datetime(2026, 7, 1, tzinfo=UTC)
    scope = {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "scope_grant_authority_sha256": "a" * 64,
        "source_evidence_sha256": evidence.sha256,
        "scope_as_of": "2026-07-01T00:00:00+00:00",
    }
    return engine, AfterSalesLedgerService(engine), evidence, scope


def _record(service, evidence, scope, **overrides):
    values = {
        "order_ref": "order-1",
        "event_kind": AfterSalesEventKind.RETURN_ACCRUAL,
        "amount": Decimal("12"),
        "currency": "CNY",
        "event_time": "2026-07-02T00:00:00+00:00",
        "observed_time": "2026-07-03T00:00:00+00:00",
        "effective_time": "2026-07-02T00:00:00+00:00",
        "evidence_id": evidence.id,
        "created_by": "after-sales-operator",
        "source_system": "ozon",
        "source_record_id": "return-1",
        "source_version": "1",
        "idempotency_key": "after-sales-1",
        "scope_authority": scope,
        "recorded_at": "2026-07-03T00:00:00+00:00",
    }
    values.update(overrides)
    return service.record_event(**values)


def test_after_sales_snapshot_separates_reserves_realized_adjustments_and_reopen():
    _, service, evidence, scope = _services()
    _record(service, evidence, scope, amount=Decimal("12"))
    _record(
        service,
        evidence,
        scope,
        event_kind="chargeback",
        amount=Decimal("8"),
        source_record_id="chargeback-1",
        idempotency_key="after-sales-2",
        claim_status="open",
    )
    _record(
        service,
        evidence,
        scope,
        event_kind="refund",
        amount=Decimal("4"),
        source_record_id="refund-1",
        idempotency_key="after-sales-3",
    )
    _record(
        service,
        evidence,
        scope,
        event_kind="recovery",
        amount=Decimal("3"),
        source_record_id="recovery-1",
        idempotency_key="after-sales-4",
        direction="credit",
    )
    _record(
        service,
        evidence,
        scope,
        event_kind="settlement_reopened",
        amount=Decimal("5"),
        source_record_id="reopen-1",
        idempotency_key="after-sales-5",
    )

    snapshot = service.snapshot(
        scope_authority=scope,
        as_of="2026-08-01T00:00:00+00:00",
        realized_profit=Decimal("100"),
    )

    assert snapshot["status"] == "VALID"
    assert snapshot["realized_profit"] == "100"
    assert snapshot["expected_return_cost"] == "12"
    assert snapshot["chargeback_reserve"] == "8"
    assert snapshot["realized_adjustment"] == "4"
    assert snapshot["recovery_amount"] == "3"
    assert snapshot["reopened_settlement"] == "5"
    assert snapshot["risk_adjusted_profit"] == "74"
    assert snapshot["claim_status"] == "open"
    assert len(snapshot["events"]) == 5


def test_restatement_is_append_only_and_as_of_replays_the_known_version():
    engine, service, evidence, scope = _services()
    original = _record(service, evidence, scope, amount=Decimal("5"))
    revised = _record(
        service,
        evidence,
        scope,
        amount=Decimal("9"),
        source_version="2",
        idempotency_key="after-sales-restate-2",
        logical_event_id=original.logical_event_id,
        supersedes_event_id=original.event_id,
        recorded_at="2026-08-03T00:00:00+00:00",
    )
    assert revised.version == 2

    before = service.snapshot(
        scope_authority=scope,
        as_of="2026-07-31T00:00:00+00:00",
        realized_profit=Decimal("20"),
    )
    after = service.snapshot(
        scope_authority=scope,
        as_of="2026-08-31T00:00:00+00:00",
        realized_profit=Decimal("20"),
    )

    assert before["expected_return_cost"] == "5"
    assert before["versions"] == {original.logical_event_id: 1}
    assert after["expected_return_cost"] == "9"
    assert after["versions"] == {original.logical_event_id: 2}

    # The old row remains physically present and is never overwritten.
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from apps.control_plane.after_sales_ledger import AfterSalesEventRow

    with Session(engine) as session:
        rows = session.scalars(
            select(AfterSalesEventRow).order_by(AfterSalesEventRow.version)
        ).all()
    assert [row.amount for row in rows] == [Decimal("5"), Decimal("9")]


def test_idempotency_conflict_and_cross_scope_are_fail_closed():
    _, service, evidence, scope = _services()
    _record(service, evidence, scope)
    with pytest.raises(AfterSalesLedgerError, match="idempotency_key"):
        _record(service, evidence, scope, amount=Decimal("13"))

    other_scope = {
        **scope,
        "store_ref": "store-b",
        "source_evidence_sha256": "b" * 63,
    }
    with pytest.raises(AfterSalesLedgerError, match="source evidence authority"):
        _record(
            service,
            evidence,
            other_scope,
            idempotency_key="after-sales-other-store",
        )


def test_missing_baseline_or_events_never_uses_zero_as_no_data():
    _, service, _, scope = _services()
    empty = service.snapshot(
        scope_authority=scope,
        as_of="2026-08-01T00:00:00+00:00",
        realized_profit=Decimal("100"),
    )
    assert empty["status"] == "NO_DATA"
    assert empty["risk_adjusted_profit"] is None
    assert empty["expected_return_cost"] is None
