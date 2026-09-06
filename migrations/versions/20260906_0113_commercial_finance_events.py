"""Add tenant-scoped commercial cost and revenue-share events.

Revision ID: 20260906_0113
Revises: 20260906_0112
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0113"
down_revision = "20260906_0112"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commercial_finance_events",
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("customer_id", sa.String(length=200), nullable=False),
        sa.Column("contract_id", sa.String(length=240), nullable=False),
        sa.Column("entitlement_id", sa.String(length=240), nullable=False),
        sa.Column("event_kind", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("amount_text", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.String(length=300), nullable=True),
        sa.Column("usage_event_id", sa.String(length=200), nullable=True),
        sa.Column("asset_ref", sa.String(length=300), nullable=True),
        sa.Column("cost_center", sa.String(length=160), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_commercial_finance_tenant_idempotency"),
        sa.CheckConstraint("amount >= 0", name="ck_commercial_finance_amount_nonnegative"),
        sa.CheckConstraint("length(currency) = 3", name="ck_commercial_finance_currency_shape"),
    )
    op.create_index(
        "ix_commercial_finance_scope_occurred",
        "commercial_finance_events",
        ["tenant_id", "customer_id", "occurred_at", "event_id"],
    )
    op.create_index(
        "ix_commercial_finance_entitlement",
        "commercial_finance_events",
        ["tenant_id", "entitlement_id", "occurred_at"],
    )
    op.execute(
        """
CREATE OR REPLACE FUNCTION kjds_commercial_finance_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$
"""
    )
    op.execute(
        'CREATE TRIGGER "trg_commercial_finance_events_immutable" '
        'BEFORE UPDATE OR DELETE ON "commercial_finance_events" FOR EACH ROW '
        "EXECUTE FUNCTION kjds_commercial_finance_immutable()"
    )
    op.execute(
        'CREATE TRIGGER "trg_commercial_finance_events_truncate_immutable" '
        'BEFORE TRUNCATE ON "commercial_finance_events" FOR EACH STATEMENT '
        "EXECUTE FUNCTION kjds_commercial_finance_immutable()"
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS "trg_commercial_finance_events_truncate_immutable" ON "commercial_finance_events"')
    op.execute('DROP TRIGGER IF EXISTS "trg_commercial_finance_events_immutable" ON "commercial_finance_events"')
    op.execute("DROP FUNCTION IF EXISTS kjds_commercial_finance_immutable()")
    op.drop_index("ix_commercial_finance_entitlement", table_name="commercial_finance_events")
    op.drop_index("ix_commercial_finance_scope_occurred", table_name="commercial_finance_events")
    op.drop_table("commercial_finance_events")
