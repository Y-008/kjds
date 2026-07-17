"""Add immutable policy evaluations, shadow batches, and activation handoffs."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0018"
down_revision = "20260717_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "causal_policy_evaluations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("release_id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("policy_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("context_hash", sa.String(length=64), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("evaluated_by", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["causal_policies.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["causal_policy_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("release_id", "idempotency_key", name="uq_causal_policy_evaluation_key"),
    )
    op.create_table(
        "causal_policy_shadow_batches",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("release_id", sa.String(), nullable=False),
        sa.Column("batch_key", sa.String(), nullable=False),
        sa.Column("evaluation_ids_json", sa.JSON(), nullable=False),
        sa.Column("context_count", sa.Integer(), nullable=False),
        sa.Column("matched_count", sa.Integer(), nullable=False),
        sa.Column("fallback_count", sa.Integer(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["causal_policies.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["causal_policy_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("release_id", "batch_key", name="uq_causal_policy_shadow_batch"),
    )
    op.create_table(
        "causal_policy_activation_handoffs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_id", sa.String(), nullable=False),
        sa.Column("release_id", sa.String(), nullable=False),
        sa.Column("approval_id", sa.String(), nullable=False),
        sa.Column("evaluation_ids_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("policy_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["causal_policies.id"]),
        sa.ForeignKeyConstraint(["release_id"], ["causal_policy_releases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("release_id"),
        sa.UniqueConstraint("approval_id"),
    )


def downgrade() -> None:
    op.drop_table("causal_policy_activation_handoffs")
    op.drop_table("causal_policy_shadow_batches")
    op.drop_table("causal_policy_evaluations")
