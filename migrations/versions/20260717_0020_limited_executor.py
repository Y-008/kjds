"""Add limited execution command and receipt state machine."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0020"
down_revision = "20260717_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "limited_execution_commands",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("parent_command_id", sa.String(), nullable=True),
        sa.Column("command_kind", sa.String(), nullable=False),
        sa.Column("idempotency_token", sa.String(length=64), nullable=False),
        sa.Column("adapter_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("target_json", sa.JSON(), nullable=False),
        sa.Column("patch_json", sa.JSON(), nullable=False),
        sa.Column("expected_state_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("queued_by", sa.String(), nullable=False),
        sa.Column("claimed_by", sa.String(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["governed_execution_plans.id"]),
        sa.ForeignKeyConstraint(["parent_command_id"], ["limited_execution_commands.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_token"),
        sa.UniqueConstraint("plan_id", "command_kind", name="uq_limited_command_kind"),
    )
    op.create_table(
        "limited_execution_receipts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("command_id", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("remote_operation_id", sa.String(), nullable=True),
        sa.Column("resulting_state_hash", sa.String(length=64), nullable=True),
        sa.Column("mutation_applied", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_detail", sa.String(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["command_id"], ["limited_execution_commands.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("command_id"),
    )


def downgrade() -> None:
    op.drop_table("limited_execution_receipts")
    op.drop_table("limited_execution_commands")
