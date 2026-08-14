"""Add append-only tenant/entity/store scope grant authority."""

import sqlalchemy as sa
from alembic import op

revision = "20260727_0056"
down_revision = "20260727_0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scope_grant_events",
        sa.Column("sequence", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_ref", sa.String(), nullable=False),
        sa.Column("entity_ref", sa.String(), nullable=False),
        sa.Column("store_ref", sa.String(), nullable=False),
        sa.Column("subject_actor_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('grant','revoke')",
            name="ck_scope_grant_event_type",
        ),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence_records.id"]),
        sa.PrimaryKeyConstraint("sequence"),
        sa.UniqueConstraint("id"),
        sa.UniqueConstraint(
            "tenant_ref",
            "idempotency_key",
            name="uq_scope_grant_event_idempotency",
        ),
    )
    op.create_index(
        "ix_scope_grant_current",
        "scope_grant_events",
        [
            "tenant_ref",
            "subject_actor_id",
            "store_ref",
            "effective_at",
            "sequence",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_scope_grant_current", table_name="scope_grant_events")
    op.drop_table("scope_grant_events")
