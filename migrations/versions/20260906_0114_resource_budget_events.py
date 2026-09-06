"""Add durable resource budget reservation and consumption events.

Revision ID: 20260906_0114
Revises: 20260906_0113
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0114"
down_revision = "20260906_0113"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_budgets",
        sa.Column("budget_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("cost_center", sa.String(length=160), nullable=False),
        sa.Column("limit_amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("limit_amount_text", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("budget_id"),
        sa.UniqueConstraint("tenant_id", "budget_id", name="uq_resource_budget_tenant_id"),
        sa.CheckConstraint("limit_amount >= 0", name="ck_resource_budget_limit_nonnegative"),
        sa.CheckConstraint("length(currency) = 3", name="ck_resource_budget_currency_shape"),
    )
    op.create_index("ix_resource_budget_scope", "resource_budgets", ["tenant_id", "resource_type", "cost_center"])
    op.create_table(
        "resource_budget_events",
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("budget_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(38, 18), nullable=False),
        sa.Column("amount_text", sa.String(length=100), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("parent_event_id", sa.String(length=200), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_resource_budget_event_tenant_idempotency"),
        sa.UniqueConstraint("tenant_id", "budget_id", "event_id", name="uq_resource_budget_event_scope_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "budget_id"],
            ["resource_budgets.tenant_id", "resource_budgets.budget_id"],
            name="fk_resource_budget_event_budget",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "budget_id", "parent_event_id"],
            ["resource_budget_events.tenant_id", "resource_budget_events.budget_id", "resource_budget_events.event_id"],
            name="fk_resource_budget_event_parent",
        ),
        sa.CheckConstraint(
            "state IN ('reserved', 'consumed', 'released', 'overrun')",
            name="ck_resource_budget_event_state",
        ),
        sa.CheckConstraint(
            "(state = 'reserved' AND parent_event_id IS NULL) OR "
            "(state IN ('consumed', 'released') AND parent_event_id IS NOT NULL) OR "
            "(state = 'overrun')",
            name="ck_resource_budget_event_parent_shape",
        ),
        sa.CheckConstraint("amount >= 0", name="ck_resource_budget_event_amount_nonnegative"),
        sa.CheckConstraint("length(currency) = 3", name="ck_resource_budget_event_currency_shape"),
    )
    op.create_index("ix_resource_budget_event_scope", "resource_budget_events", ["tenant_id", "budget_id", "occurred_at", "event_id"])
    op.execute(
        """
CREATE OR REPLACE FUNCTION kjds_resource_budget_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$
"""
    )
    for table in ("resource_budgets", "resource_budget_events"):
        op.execute(
            f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION kjds_resource_budget_immutable()"
        )
        op.execute(
            f'CREATE TRIGGER "trg_{table}_truncate_immutable" BEFORE TRUNCATE ON "{table}" '
            "FOR EACH STATEMENT EXECUTE FUNCTION kjds_resource_budget_immutable()"
        )


def downgrade() -> None:
    for table in ("resource_budget_events", "resource_budgets"):
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_truncate_immutable" ON "{table}"')
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"')
    op.execute("DROP FUNCTION IF EXISTS kjds_resource_budget_immutable()")
    op.drop_index("ix_resource_budget_event_scope", table_name="resource_budget_events")
    op.drop_table("resource_budget_events")
    op.drop_index("ix_resource_budget_scope", table_name="resource_budgets")
    op.drop_table("resource_budgets")
