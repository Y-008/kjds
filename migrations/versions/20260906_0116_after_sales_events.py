"""Add an exact-scope append-only after-sales event ledger.

Revision ID: 20260906_0116
Revises: 20260906_0115
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0116"
down_revision = "20260906_0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "after_sales_events",
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("logical_event_id", sa.String(length=240), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=True),
        sa.Column("entity_ref", sa.String(length=160), nullable=True),
        sa.Column("store_ref", sa.String(length=160), nullable=True),
        sa.Column(
            "scope_grant_authority_sha256",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("source_evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("scope_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_ref", sa.String(length=240), nullable=False),
        sa.Column("sku", sa.String(length=240), nullable=True),
        sa.Column("event_kind", sa.String(length=40), nullable=False),
        sa.Column("impact", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("claim_status", sa.String(length=24), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("amount_text", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_system", sa.String(length=120), nullable=False),
        sa.Column("source_record_id", sa.String(length=240), nullable=False),
        sa.Column("source_version", sa.String(length=120), nullable=False),
        sa.Column("causation_id", sa.String(length=240), nullable=False),
        sa.Column("correlation_id", sa.String(length=240), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("supersedes_event_id", sa.String(length=200), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence_records.id"],
            name="fk_after_sales_event_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_event_id"],
            ["after_sales_events.event_id"],
            name="fk_after_sales_event_supersedes",
        ),
        sa.CheckConstraint(
            "((tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
            "AND scope_grant_authority_sha256 IS NULL "
            "AND source_evidence_sha256 IS NULL AND scope_as_of IS NULL) OR "
            "(tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
            "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
            "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
            "AND scope_grant_authority_sha256 IS NOT NULL "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND source_evidence_sha256 IS NOT NULL "
            "AND length(source_evidence_sha256) = 64 "
            "AND scope_as_of IS NOT NULL))",
            name="ck_after_sales_scope_complete",
        ),
        sa.CheckConstraint(
            "event_kind IN ("
            "'return_accrual','refund','chargeback','claim','recovery',"
            "'settlement_reopened','settlement_closed')",
            name="ck_after_sales_event_kind",
        ),
        sa.CheckConstraint(
            "impact IN ("
            "'expected_return_cost','chargeback_reserve','realized_adjustment',"
            "'recovery_amount','reopened_settlement','none')",
            name="ck_after_sales_impact",
        ),
        sa.CheckConstraint(
            "direction IN ('debit','credit')",
            name="ck_after_sales_direction",
        ),
        sa.CheckConstraint(
            "claim_status IN ('none','open','approved','paid','rejected','reopened')",
            name="ck_after_sales_claim_status",
        ),
        sa.CheckConstraint(
            "amount >= 0",
            name="ck_after_sales_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name="ck_after_sales_currency_shape",
        ),
        sa.CheckConstraint(
            "version > 0",
            name="ck_after_sales_version_positive",
        ),
    )
    op.create_index(
        "uq_after_sales_scope_idempotency",
        "after_sales_events",
        ["tenant_ref", "entity_ref", "store_ref", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_after_sales_scope_logical_version",
        "after_sales_events",
        ["tenant_ref", "entity_ref", "store_ref", "logical_event_id", "version"],
        unique=True,
        postgresql_where=sa.text("tenant_ref IS NOT NULL"),
        sqlite_where=sa.text("tenant_ref IS NOT NULL"),
    )
    op.create_index(
        "ix_after_sales_scope_order_effective",
        "after_sales_events",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "order_ref",
            "effective_time",
            "recorded_at",
        ],
    )
    op.create_index(
        "ix_after_sales_scope_source",
        "after_sales_events",
        [
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_system",
            "source_record_id",
            "source_version",
        ],
    )
    op.execute(
        """
CREATE OR REPLACE FUNCTION kjds_after_sales_events_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$
"""
    )
    op.execute(
        'CREATE TRIGGER "trg_after_sales_events_immutable" '
        'BEFORE UPDATE OR DELETE ON "after_sales_events" FOR EACH ROW '
        "EXECUTE FUNCTION kjds_after_sales_events_immutable()"
    )
    op.execute(
        'CREATE TRIGGER "trg_after_sales_events_truncate_immutable" '
        'BEFORE TRUNCATE ON "after_sales_events" FOR EACH STATEMENT '
        "EXECUTE FUNCTION kjds_after_sales_events_immutable()"
    )


def downgrade() -> None:
    op.execute(
        'DROP TRIGGER IF EXISTS "trg_after_sales_events_truncate_immutable" '
        'ON "after_sales_events"'
    )
    op.execute(
        'DROP TRIGGER IF EXISTS "trg_after_sales_events_immutable" '
        'ON "after_sales_events"'
    )
    op.execute("DROP FUNCTION IF EXISTS kjds_after_sales_events_immutable()")
    op.drop_index(
        "ix_after_sales_scope_source", table_name="after_sales_events"
    )
    op.drop_index(
        "ix_after_sales_scope_order_effective", table_name="after_sales_events"
    )
    op.drop_index(
        "uq_after_sales_scope_logical_version", table_name="after_sales_events"
    )
    op.drop_index(
        "uq_after_sales_scope_idempotency", table_name="after_sales_events"
    )
    op.drop_table("after_sales_events")
