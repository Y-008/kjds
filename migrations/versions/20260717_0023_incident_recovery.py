"""Add operational incident recovery and drill ledgers."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0023"
down_revision = "20260717_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operational_incidents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False),
        sa.Column("trigger_type", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=True),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("review_status", sa.String(), nullable=True),
        sa.Column("opened_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "incident_recovery_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("incident_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["operational_incidents.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
    )


def downgrade() -> None:
    op.drop_table("incident_recovery_events")
    op.drop_table("operational_incidents")
