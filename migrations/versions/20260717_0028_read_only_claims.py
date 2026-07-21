"""Add reviewed claim bridge for successful read-only pilot runs."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0028"
down_revision = "20260717_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "read_only_claims",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("claim_type", sa.String(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("source_state_sha256", sa.String(length=64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("proposed_by", sa.String(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("rationale", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["read_only_pilot_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("run_id", "payload_hash", name="uq_read_only_claim_run_payload"),
    )
    op.create_index(
        "ix_read_only_claims_run_status",
        "read_only_claims",
        ["run_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_read_only_claims_run_status", table_name="read_only_claims")
    op.drop_table("read_only_claims")
