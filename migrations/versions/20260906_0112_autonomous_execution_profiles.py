"""Persist standing autonomous execution profile governance revisions.

Revision ID: 20260906_0112
Revises: 20260906_0111
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0112"
down_revision = "20260906_0111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "autonomous_execution_profile_revisions",
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("profile_id", sa.String(length=200), nullable=False),
        sa.Column("profile_version", sa.String(length=80), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_refs_json", sa.JSON(), nullable=False),
        sa.Column("allowed_channels_json", sa.JSON(), nullable=False),
        sa.Column("allowed_operations_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_permit_ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("max_command_amount", sa.Numeric(38, 18), nullable=True),
        sa.Column("max_command_amount_text", sa.String(length=100), nullable=True),
        sa.Column("profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("revision_event", sa.String(length=40), nullable=False),
        sa.Column("created_by", sa.String(length=200), nullable=False),
        sa.Column("reviewer_id", sa.String(length=200), nullable=False),
        sa.Column("compliance_id", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "profile_version", name="uq_autonomy_profile_version"),
        sa.CheckConstraint(
            "max_permit_ttl_seconds BETWEEN 1 AND 3600",
            name="ck_autonomy_profile_ttl",
        ),
        sa.CheckConstraint(
            "max_command_amount IS NULL OR max_command_amount >= 0",
            name="ck_autonomy_profile_amount",
        ),
    )
    op.create_index(
        "ix_autonomy_profile_scope",
        "autonomous_execution_profile_revisions",
        ["tenant_ref", "entity_ref", "profile_id", "created_at"],
    )
    op.create_table(
        "autonomous_execution_profile_events",
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("profile_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("reviewer_id", sa.String(length=200), nullable=False),
        sa.Column("compliance_id", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "idempotency_key", name="uq_autonomy_profile_event_idempotency"),
        sa.UniqueConstraint("request_sha256", name="uq_autonomy_profile_event_request"),
    )
    op.create_index(
        "ix_autonomy_profile_events_profile",
        "autonomous_execution_profile_events",
        ["profile_id", "created_at"],
    )
    op.execute(
        """
CREATE OR REPLACE FUNCTION kjds_autonomy_profile_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = '55000';
END;
$$
"""
    )
    for table in (
        "autonomous_execution_profile_revisions",
        "autonomous_execution_profile_events",
    ):
        op.execute(
            f'CREATE TRIGGER "trg_{table}_immutable" '
            f'BEFORE UPDATE OR DELETE ON "{table}" FOR EACH ROW '
            "EXECUTE FUNCTION kjds_autonomy_profile_immutable()"
        )
        op.execute(
            f'CREATE TRIGGER "trg_{table}_truncate_immutable" '
            f'BEFORE TRUNCATE ON "{table}" FOR EACH STATEMENT '
            "EXECUTE FUNCTION kjds_autonomy_profile_immutable()"
        )


def downgrade() -> None:
    for table in (
        "autonomous_execution_profile_events",
        "autonomous_execution_profile_revisions",
    ):
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_truncate_immutable" ON "{table}"')
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"')
    op.execute("DROP FUNCTION IF EXISTS kjds_autonomy_profile_immutable()")
    op.drop_index("ix_autonomy_profile_events_profile", table_name="autonomous_execution_profile_events")
    op.drop_table("autonomous_execution_profile_events")
    op.drop_index("ix_autonomy_profile_scope", table_name="autonomous_execution_profile_revisions")
    op.drop_table("autonomous_execution_profile_revisions")
