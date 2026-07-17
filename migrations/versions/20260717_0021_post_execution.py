"""Add post-execution observation windows and immutable metric readings."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0021"
down_revision = "20260717_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_observation_windows",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("command_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("primary_metric", sa.String(), nullable=False),
        sa.Column("baseline_json", sa.JSON(), nullable=False),
        sa.Column("guardrails_json", sa.JSON(), nullable=False),
        sa.Column("required_observations", sa.Integer(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["command_id"], ["limited_execution_commands.id"]),
        sa.ForeignKeyConstraint(["plan_id"], ["governed_execution_plans.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["causal_policies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("command_id"),
    )
    op.create_table(
        "execution_metric_observations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("window_id", sa.String(), nullable=False),
        sa.Column("metric", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["window_id"], ["execution_observation_windows.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint(
            "window_id",
            "metric",
            "observed_at",
            name="uq_execution_metric_observation",
        ),
    )


def downgrade() -> None:
    op.drop_table("execution_metric_observations")
    op.drop_table("execution_observation_windows")
