"""Add immutable capability economic assessments."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0022"
down_revision = "20260717_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_economic_assessments",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("window_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("adapter_id", sa.String(), nullable=False),
        sa.Column("outcome_status", sa.String(), nullable=False),
        sa.Column("realized_incremental_value", sa.Numeric(38, 12), nullable=False),
        sa.Column("avoided_loss", sa.Numeric(38, 12), nullable=False),
        sa.Column("model_compute_cost", sa.Numeric(38, 12), nullable=False),
        sa.Column("human_review_cost", sa.Numeric(38, 12), nullable=False),
        sa.Column("incident_loss", sa.Numeric(38, 12), nullable=False),
        sa.Column("maintenance_cost", sa.Numeric(38, 12), nullable=False),
        sa.Column("net_value", sa.Numeric(38, 12), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("assessed_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["window_id"], ["execution_observation_windows.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["governed_execution_plans.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["causal_policies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("window_id"),
    )


def downgrade() -> None:
    op.drop_table("capability_economic_assessments")
