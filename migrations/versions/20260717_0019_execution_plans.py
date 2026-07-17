"""Add governed execution plans and immutable dry-run receipts."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0019"
down_revision = "20260717_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "governed_execution_plans",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("handoff_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("release_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("adapter_id", sa.String(), nullable=False),
        sa.Column("target_json", sa.JSON(), nullable=False),
        sa.Column("precondition_state_hash", sa.String(length=64), nullable=False),
        sa.Column("intended_patch_json", sa.JSON(), nullable=False),
        sa.Column("rollback_patch_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["handoff_id"], ["causal_policy_activation_handoffs.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["causal_policies.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["causal_policy_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("approval_id"),
        sa.UniqueConstraint("handoff_id", "idempotency_key", name="uq_execution_plan_key"),
    )
    op.create_table(
        "governed_execution_dry_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("current_state_hash", sa.String(length=64), nullable=False),
        sa.Column("checks_json", sa.JSON(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("performed_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["governed_execution_plans.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("plan_id"),
    )


def downgrade() -> None:
    op.drop_table("governed_execution_dry_runs")
    op.drop_table("governed_execution_plans")
