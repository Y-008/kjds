"""Add knowledge-backed conditional policies and controlled release gates."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0017"
down_revision = "20260717_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "causal_policies",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("knowledge_ids_json", sa.JSON(), nullable=False),
        sa.Column("applicability_json", sa.JSON(), nullable=False),
        sa.Column("conditions_json", sa.JSON(), nullable=False),
        sa.Column("action_json", sa.JSON(), nullable=False),
        sa.Column("guardrails_json", sa.JSON(), nullable=False),
        sa.Column("fallback_action_json", sa.JSON(), nullable=False),
        sa.Column("rollout_stages_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("proposed_by", sa.String(), nullable=False),
        sa.Column("execution_eligible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
    )
    op.create_table(
        "causal_policy_reviews",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("counterarguments_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["causal_policies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("policy_id", "reviewed_by", name="uq_causal_policy_reviewer"),
    )
    op.create_table(
        "causal_policy_releases",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("review_id", sa.String(), nullable=False),
        sa.Column("stage_index", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=False),
        sa.Column("execution_eligible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["causal_policies.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["causal_policy_reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("policy_id", "stage_index", name="uq_causal_policy_release_stage"),
    )
    op.create_table(
        "causal_policy_stage_outcomes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("release_id", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("incremental_value_decimal", sa.Numeric(precision=38, scale=12), nullable=False),
        sa.Column("guardrail_breached", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("recorded_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["release_id"], ["causal_policy_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("release_id"),
    )


def downgrade() -> None:
    op.drop_table("causal_policy_stage_outcomes")
    op.drop_table("causal_policy_releases")
    op.drop_table("causal_policy_reviews")
    op.drop_table("causal_policies")
