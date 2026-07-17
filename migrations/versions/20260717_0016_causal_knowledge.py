"""Add governed causal experiment reviews and knowledge registry."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0016"
down_revision = "20260717_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "causal_experiment_reviews",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("protocol_id", sa.String(), nullable=False),
        sa.Column("evaluation_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluation_json", sa.JSON(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("method_assessment", sa.Text(), nullable=False),
        sa.Column("data_quality_assessment", sa.Text(), nullable=False),
        sa.Column("counterarguments_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["protocol_id"], ["causal_experiment_protocols.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("protocol_id", "reviewed_by", name="uq_causal_experiment_reviewer"),
    )
    op.create_table(
        "causal_knowledge_entries",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("protocol_id", sa.String(), nullable=False),
        sa.Column("review_id", sa.String(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("mechanism", sa.Text(), nullable=False),
        sa.Column("applicability_json", sa.JSON(), nullable=False),
        sa.Column("falsification_conditions_json", sa.JSON(), nullable=False),
        sa.Column("effect_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reevaluate_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execution_eligible", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["protocol_id"], ["causal_experiment_protocols.id"]),
        sa.ForeignKeyConstraint(["review_id"], ["causal_experiment_reviews.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("protocol_id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint("review_id"),
    )
    op.create_table(
        "causal_replication_links",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("source_knowledge_id", sa.String(), nullable=False),
        sa.Column("replication_knowledge_id", sa.String(), nullable=False),
        sa.Column("scope_relation", sa.String(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_knowledge_id"], ["causal_knowledge_entries.id"]),
        sa.ForeignKeyConstraint(["replication_knowledge_id"], ["causal_knowledge_entries.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_hash"),
        sa.UniqueConstraint(
            "source_knowledge_id",
            "replication_knowledge_id",
            name="uq_causal_replication_pair",
        ),
        sa.UniqueConstraint("replication_knowledge_id", name="uq_causal_replication_child"),
    )


def downgrade() -> None:
    op.drop_table("causal_replication_links")
    op.drop_table("causal_knowledge_entries")
    op.drop_table("causal_experiment_reviews")
