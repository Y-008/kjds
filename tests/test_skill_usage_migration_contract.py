"""Offline contracts for the usage-entitlement schema boundary.

These checks intentionally do not connect to PostgreSQL.  They catch a
 migration that looks tenant-scoped in Python while leaving the database FK
 able to join an event to another tenant/customer/receipt.  The actual
 PostgreSQL upgrade/replay gate remains a separate environment-dependent
 check.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.control_plane.skill_usage_ledger import SkillUsageEvent
from apps.control_plane.skill_usage_sql import (
    SkillUsageEntitlementLinkRow,
    SkillUsageEventRow,
    SqlSkillUsageLedger,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations" / "versions"
MIGRATION_0117 = MIGRATIONS / "20260906_0117_usage_entitlement_receipt_links.py"
MIGRATION_0118 = MIGRATIONS / "20260906_0118_usage_entitlement_scope_integrity.py"


def _load_migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load migration: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _event() -> SkillUsageEvent:
    return SkillUsageEvent(
        event_id="usage-contract-event",
        idempotency_key="usage-contract-key",
        tenant_id="tenant-contract",
        customer_id="customer-contract",
        skill_id="image.generate",
        units=Decimal("1"),
        unit_cost=Decimal("0.25"),
        currency="USD",
        occurred_at=datetime(2026, 9, 6, tzinfo=UTC),
        entitlement_receipt_ref="receipt-contract",
    )


def test_migration_0118_is_linear_and_restores_0117_on_downgrade() -> None:
    migration = _load_migration(MIGRATION_0118)
    assert migration.revision == "20260906_0118"
    assert migration.down_revision == "20260906_0117"
    assert migration.PARENT_COLUMNS == [
        "tenant_id",
        "event_id",
        "customer_id",
        "idempotency_key",
        "entitlement_receipt_ref",
    ]
    assert migration.CHILD_COLUMNS == [
        "tenant_id",
        "usage_event_id",
        "customer_id",
        "idempotency_key",
        "entitlement_receipt_ref",
    ]

    source = MIGRATION_0118.read_text(encoding="utf-8")
    assert "ondelete=\"RESTRICT\"" in source
    assert "onupdate=\"RESTRICT\"" in source
    assert "CREATE POLICY" not in source
    assert "ENABLE ROW LEVEL SECURITY" not in source
    assert "ADR-0038" in source

    # The downgrade must remove the exact FK, recreate the legacy FK, then
    # remove the helper unique constraint.  This leaves 0117 reproducible.
    drop_exact = source.index('op.drop_constraint(EXACT_FK')
    recreate_old = source.index('op.create_foreign_key(\n        OLD_FK')
    drop_parent = source.index('op.drop_constraint(PARENT_IDENTITY')
    assert drop_exact < recreate_old < drop_parent


def test_0117_keeps_append_only_trigger_contract_for_event_and_link() -> None:
    source = MIGRATION_0117.read_text(encoding="utf-8")
    assert 'trg_skill_usage_entitlement_links_immutable' in source
    assert 'trg_skill_usage_entitlement_links_truncate_immutable' in source
    assert "BEFORE UPDATE OR DELETE" in source
    assert "BEFORE TRUNCATE" in source


def test_sqlalchemy_models_expose_exact_composite_fk_identity() -> None:
    parent_names = {
        constraint.name
        for constraint in SkillUsageEventRow.__table__.constraints
        if constraint.name
    }
    assert "uq_skill_usage_entitlement_parent_identity" in parent_names

    foreign_keys = SkillUsageEntitlementLinkRow.__table__.foreign_key_constraints
    assert len(foreign_keys) == 1
    constraint = next(iter(foreign_keys))
    assert constraint.name == "fk_skill_usage_entitlement_link_exact_event"
    assert [column.name for column in constraint.columns] == [
        "tenant_id",
        "usage_event_id",
        "customer_id",
        "idempotency_key",
        "entitlement_receipt_ref",
    ]
    assert [element.column.name for element in constraint.elements] == [
        "tenant_id",
        "event_id",
        "customer_id",
        "idempotency_key",
        "entitlement_receipt_ref",
    ]
    assert constraint.ondelete == "RESTRICT"
    assert constraint.onupdate == "RESTRICT"


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "tenant-forged"),
        ("customer_id", "customer-forged"),
        ("idempotency_key", "key-forged"),
        ("entitlement_receipt_ref", "receipt-forged"),
    ],
)
def test_sqlite_fk_probe_rejects_scope_or_receipt_mismatch(field: str, value: str) -> None:
    """Exercise the same composite identity locally without starting Postgres."""

    engine = create_engine("sqlite:///:memory:")

    @sqlalchemy_event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    store = SqlSkillUsageLedger(engine)
    # ``for_url`` owns only the local test schema; production still uses
    # Alembic.  Calling it with our engine would create a second engine, so
    # create the two tables explicitly here.
    from apps.control_plane.sql_repository import Base

    Base.metadata.create_all(
        engine,
        tables=[SkillUsageEventRow.__table__, SkillUsageEntitlementLinkRow.__table__],
    )
    original = _event()
    store.record(original)
    values = {
        "link_id": f"forged-{field}",
        "usage_event_id": original.event_id,
        "tenant_id": original.tenant_id,
        "customer_id": original.customer_id,
        "idempotency_key": original.idempotency_key,
        "entitlement_receipt_ref": original.entitlement_receipt_ref,
        "fingerprint_sha256": "f" * 64,
        "recorded_at": datetime.now(UTC),
    }
    values[field] = value
    with pytest.raises(IntegrityError), Session(engine) as session, session.begin():
        session.add(SkillUsageEntitlementLinkRow(**values))

