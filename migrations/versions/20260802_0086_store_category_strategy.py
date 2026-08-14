"""Add store category strategy profiles and immutable plans.

Revision ID: 20260802_0086
Revises: 20260802_0085
Create Date: 2026-08-02
"""

import sqlalchemy as sa
from alembic import op

revision = "20260802_0086"
down_revision = "20260802_0085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "store_operating_profile_events",
        sa.Column("id", sa.String(length=180), primary_key=True),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column(
            "scope_grant_authority_sha256", sa.String(length=64), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_sha256", sa.String(length=64), nullable=False),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("request_evidence_id", sa.String(), nullable=False),
        sa.Column("supporting_evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("external_write_allowed", sa.Boolean(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 "
            "AND length(request_sha256) = 64 AND length(profile_sha256) = 64",
            name="ck_store_operating_profile_hashes",
        ),
        sa.CheckConstraint(
            "confirmed IS TRUE AND external_write_allowed IS FALSE",
            name="ck_store_operating_profile_control",
        ),
        sa.ForeignKeyConstraint(["request_evidence_id"], ["evidence_records.id"]),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_store_operating_profile_scope_idempotency",
        ),
    )
    op.create_index(
        "ix_store_operating_profile_scope_effective",
        "store_operating_profile_events",
        ["tenant_ref", "entity_ref", "store_ref", "effective_at"],
    )
    op.create_table(
        "store_operating_plan_snapshots",
        sa.Column("id", sa.String(length=180), primary_key=True),
        sa.Column("profile_id", sa.String(length=180), nullable=True),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("entity_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column(
            "scope_grant_authority_sha256", sa.String(length=64), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("input_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("output_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_write_allowed", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=240), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 "
            "AND length(input_snapshot_sha256) = 64 "
            "AND length(output_snapshot_sha256) = 64",
            name="ck_store_operating_plan_hashes",
        ),
        sa.CheckConstraint(
            "status IN ('ready_with_constraints','no_data','blocked')",
            name="ck_store_operating_plan_status",
        ),
        sa.CheckConstraint(
            "external_write_allowed IS FALSE",
            name="ck_store_operating_plan_control",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"], ["store_operating_profile_events.id"]
        ),
        sa.UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_store_operating_plan_scope_idempotency",
        ),
    )
    op.create_index(
        "ix_store_operating_plan_scope_created",
        "store_operating_plan_snapshots",
        ["tenant_ref", "entity_ref", "store_ref", "created_at"],
    )
    for table in (
        "store_operating_profile_events",
        "store_operating_plan_snapshots",
    ):
        op.execute(
            f'CREATE TRIGGER "trg_{table}_immutable" BEFORE UPDATE OR DELETE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION kjds_prevent_ledger_mutation()"
        )


def downgrade() -> None:
    for table in (
        "store_operating_plan_snapshots",
        "store_operating_profile_events",
    ):
        op.execute(f'DROP TRIGGER IF EXISTS "trg_{table}_immutable" ON "{table}"')
    op.drop_index(
        "ix_store_operating_plan_scope_created",
        table_name="store_operating_plan_snapshots",
    )
    op.drop_table("store_operating_plan_snapshots")
    op.drop_index(
        "ix_store_operating_profile_scope_effective",
        table_name="store_operating_profile_events",
    )
    op.drop_table("store_operating_profile_events")
