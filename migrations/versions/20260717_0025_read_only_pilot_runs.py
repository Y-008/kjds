"""Add bounded read-only pilot run and result evidence ledger."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0025"
down_revision = "20260717_0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "read_only_pilot_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("pilot_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("response_sha256", sa.String(length=64), nullable=True),
        sa.Column("response_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("evidence_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["pilot_id"], ["read_only_pilots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_read_only_pilot_runs_usage",
        "read_only_pilot_runs",
        ["pilot_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_read_only_pilot_runs_usage", table_name="read_only_pilot_runs")
    op.drop_table("read_only_pilot_runs")
