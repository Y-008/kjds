"""Add SLA escalation ledger and governed read-only pilots."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0024"
down_revision = "20260717_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "operations_escalation_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("queue_key", sa.String(), nullable=False),
        sa.Column("item_type", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("escalated_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("queue_key", "level", name="uq_operations_escalation_level"),
    )
    op.create_table(
        "read_only_pilots",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("account_alias", sa.String(), nullable=False),
        sa.Column("allowed_operations_json", sa.JSON(), nullable=False),
        sa.Column("max_daily_requests", sa.Integer(), nullable=False),
        sa.Column("max_targets", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("review_rationale", sa.Text(), nullable=True),
        sa.Column("activated_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_table(
        "pilot_control_attestations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("pilot_id", sa.String(), nullable=False),
        sa.Column("control", sa.String(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("attested_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pilot_id"], ["read_only_pilots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint(
            "pilot_id",
            "control",
            "request_hash",
            name="uq_pilot_control_attestation",
        ),
    )


def downgrade() -> None:
    op.drop_table("pilot_control_attestations")
    op.drop_table("read_only_pilots")
    op.drop_table("operations_escalation_events")
