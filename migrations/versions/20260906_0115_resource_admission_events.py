"""Bind resource budget events to governed command permits.

Revision ID: 20260906_0115
Revises: 20260906_0114
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0115"
down_revision = "20260906_0114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_admission_events",
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("admission_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("command_id", sa.String(length=200), nullable=False),
        sa.Column("action_id", sa.String(length=200), nullable=False),
        sa.Column("permit_ref", sa.String(length=300), nullable=False),
        sa.Column("budget_id", sa.String(length=200), nullable=False),
        sa.Column("resource_event_id", sa.String(length=200), nullable=True),
        sa.Column("parent_resource_event_id", sa.String(length=200), nullable=True),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("amount_text", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "budget_id"],
            ["resource_budgets.tenant_id", "resource_budgets.budget_id"],
            name="fk_resource_admission_budget",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "budget_id", "resource_event_id"],
            [
                "resource_budget_events.tenant_id",
                "resource_budget_events.budget_id",
                "resource_budget_events.event_id",
            ],
            name="fk_resource_admission_resource_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "budget_id", "parent_resource_event_id"],
            [
                "resource_budget_events.tenant_id",
                "resource_budget_events.budget_id",
                "resource_budget_events.event_id",
            ],
            name="fk_resource_admission_parent_resource_event",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_resource_admission_tenant_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "admission_id",
            "operation",
            name="uq_resource_admission_operation",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "resource_event_id",
            name="uq_resource_admission_resource_event",
        ),
        sa.CheckConstraint(
            "operation IN ('reserve', 'consume', 'release', 'hold_unknown')",
            name="ck_resource_admission_operation",
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'consumed', 'released', 'unknown')",
            name="ck_resource_admission_status",
        ),
        sa.CheckConstraint(
            "amount >= 0", name="ck_resource_admission_amount_nonnegative"
        ),
        sa.CheckConstraint(
            "length(currency) = 3", name="ck_resource_admission_currency_shape"
        ),
        sa.CheckConstraint(
            "(operation = 'reserve' AND status = 'reserved' "
            "AND parent_resource_event_id IS NULL AND resource_event_id IS NOT NULL) OR "
            "(operation = 'consume' AND status = 'consumed' "
            "AND parent_resource_event_id IS NOT NULL AND resource_event_id IS NOT NULL) OR "
            "(operation = 'release' AND status = 'released' "
            "AND parent_resource_event_id IS NOT NULL AND resource_event_id IS NOT NULL) OR "
            "(operation = 'hold_unknown' AND status = 'unknown' "
            "AND parent_resource_event_id IS NOT NULL AND resource_event_id IS NULL)",
            name="ck_resource_admission_shape",
        ),
    )
    op.create_index(
        "ix_resource_admission_command",
        "resource_admission_events",
        ["tenant_id", "command_id", "recorded_at", "event_id"],
    )
    op.create_index(
        "ix_resource_admission_scope",
        "resource_admission_events",
        ["tenant_id", "admission_id", "recorded_at", "event_id"],
    )
    op.execute(
        """
CREATE OR REPLACE FUNCTION kjds_resource_admission_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$
"""
    )
    for table in ("resource_admission_events",):
        op.execute(
            f'CREATE TRIGGER "trg_{table}_immutable" '
            f'BEFORE UPDATE OR DELETE ON "{table}" FOR EACH ROW '
            "EXECUTE FUNCTION kjds_resource_admission_immutable()"
        )
        op.execute(
            f'CREATE TRIGGER "trg_{table}_truncate_immutable" '
            f'BEFORE TRUNCATE ON "{table}" FOR EACH STATEMENT '
            "EXECUTE FUNCTION kjds_resource_admission_immutable()"
        )


def downgrade() -> None:
    for table in ("resource_admission_events",):
        op.execute(
            f'DROP TRIGGER IF EXISTS "trg_{table}_truncate_immutable" ON "{table}"'
        )
        op.execute(
            f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"'
        )
    op.execute("DROP FUNCTION IF EXISTS kjds_resource_admission_immutable()")
    op.drop_index(
        "ix_resource_admission_scope", table_name="resource_admission_events"
    )
    op.drop_index(
        "ix_resource_admission_command", table_name="resource_admission_events"
    )
    op.drop_table("resource_admission_events")
