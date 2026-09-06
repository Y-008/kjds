"""Bind explicitly admitted usage events to immutable entitlement receipts.

Revision ID: 20260906_0117
Revises: 20260906_0116

Legacy usage events remain valid with a NULL receipt reference.  New explicit
entitlement admissions write the usage row and its companion link in one
transaction; the link is append-only and tenant scoped.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0117"
down_revision = "20260906_0116"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_usage_events",
        sa.Column("entitlement_receipt_ref", sa.String(length=300), nullable=True),
    )
    op.create_check_constraint(
        "ck_skill_usage_entitlement_receipt_ref",
        "skill_usage_events",
        "entitlement_receipt_ref IS NULL OR length(entitlement_receipt_ref) > 0",
    )
    op.create_index(
        "ix_skill_usage_entitlement_receipt",
        "skill_usage_events",
        ["tenant_id", "entitlement_receipt_ref", "occurred_at"],
    )
    op.create_table(
        "skill_usage_entitlement_links",
        sa.Column("link_id", sa.String(length=64), nullable=False),
        sa.Column("usage_event_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("customer_id", sa.String(length=200), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column(
            "entitlement_receipt_ref", sa.String(length=300), nullable=False
        ),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("link_id"),
        sa.ForeignKeyConstraint(
            ["usage_event_id"],
            ["skill_usage_events.event_id"],
            name="fk_skill_usage_entitlement_link_event",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "usage_event_id",
            name="uq_skill_usage_entitlement_link_event",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_skill_usage_entitlement_link_idempotency",
        ),
        sa.CheckConstraint(
            "length(entitlement_receipt_ref) > 0",
            name="ck_skill_usage_entitlement_link_receipt_ref",
        ),
        sa.CheckConstraint(
            "length(fingerprint_sha256) = 64",
            name="ck_skill_usage_entitlement_link_fingerprint_shape",
        ),
    )
    op.create_index(
        "ix_skill_usage_entitlement_link_receipt",
        "skill_usage_entitlement_links",
        ["tenant_id", "entitlement_receipt_ref", "recorded_at"],
    )
    op.create_index(
        "ix_skill_usage_entitlement_link_scope",
        "skill_usage_entitlement_links",
        ["tenant_id", "customer_id", "recorded_at", "usage_event_id"],
    )
    op.execute(
        """
CREATE OR REPLACE FUNCTION kjds_skill_usage_entitlement_link_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$
"""
    )
    op.execute(
        'CREATE TRIGGER "trg_skill_usage_entitlement_links_immutable" '
        'BEFORE UPDATE OR DELETE ON "skill_usage_entitlement_links" FOR EACH ROW '
        "EXECUTE FUNCTION kjds_skill_usage_entitlement_link_immutable()"
    )
    op.execute(
        'CREATE TRIGGER "trg_skill_usage_entitlement_links_truncate_immutable" '
        'BEFORE TRUNCATE ON "skill_usage_entitlement_links" FOR EACH STATEMENT '
        "EXECUTE FUNCTION kjds_skill_usage_entitlement_link_immutable()"
    )


def downgrade() -> None:
    op.execute(
        'DROP TRIGGER IF EXISTS "trg_skill_usage_entitlement_links_truncate_immutable" '
        'ON "skill_usage_entitlement_links"'
    )
    op.execute(
        'DROP TRIGGER IF EXISTS "trg_skill_usage_entitlement_links_immutable" '
        'ON "skill_usage_entitlement_links"'
    )
    op.execute(
        "DROP FUNCTION IF EXISTS kjds_skill_usage_entitlement_link_immutable()"
    )
    op.drop_index(
        "ix_skill_usage_entitlement_link_scope",
        table_name="skill_usage_entitlement_links",
    )
    op.drop_index(
        "ix_skill_usage_entitlement_link_receipt",
        table_name="skill_usage_entitlement_links",
    )
    op.drop_table("skill_usage_entitlement_links")
    op.drop_index(
        "ix_skill_usage_entitlement_receipt", table_name="skill_usage_events"
    )
    op.drop_constraint(
        "ck_skill_usage_entitlement_receipt_ref",
        "skill_usage_events",
        type_="check",
    )
    op.drop_column("skill_usage_events", "entitlement_receipt_ref")
