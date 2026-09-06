"""Add append-only temporal fact revisions for replayable data products."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0104"
down_revision = "20260820_0103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "temporal_fact_revisions",
        sa.Column("revision_id", sa.String(length=200), primary_key=True),
        sa.Column("fact_id", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("fact_type", sa.String(length=200), nullable=False),
        sa.Column("natural_key", sa.String(length=300), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("entity_id", sa.String(length=160), nullable=False),
        sa.Column("scope_key", sa.String(length=500), nullable=False),
        sa.Column("store_ids_json", sa.JSON(), nullable=False),
        sa.Column("warehouse_ids_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("lineage_json", sa.JSON(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fresh_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_state", sa.String(length=40), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("source_system", sa.String(length=160), nullable=False),
        sa.Column("source_record_id", sa.String(length=240), nullable=False),
        sa.Column("source_version", sa.String(length=120), nullable=True),
        sa.Column("causation_id", sa.String(length=240), nullable=True),
        sa.Column("correlation_id", sa.String(length=240), nullable=True),
        sa.Column("idempotency_key", sa.String(length=300), nullable=True),
        sa.Column("permission_scope", sa.String(length=240), nullable=True),
        sa.Column("revision_reason", sa.String(length=1000), nullable=True),
        sa.Column("supersedes_revision", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(length=160), nullable=False),
    )
    op.create_index(
        "ix_temporal_fact_identity_revision",
        "temporal_fact_revisions",
        ["tenant_id", "entity_id", "scope_key", "fact_type", "natural_key", "revision"],
    )
    op.create_index(
        "ix_temporal_fact_revisions_fact_id",
        "temporal_fact_revisions",
        ["fact_id"],
    )
    op.create_index(
        "ix_temporal_fact_observed",
        "temporal_fact_revisions",
        ["tenant_id", "entity_id", "observed_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_temporal_fact_observed", table_name="temporal_fact_revisions")
    op.drop_index("ix_temporal_fact_revisions_fact_id", table_name="temporal_fact_revisions")
    op.drop_index("ix_temporal_fact_identity_revision", table_name="temporal_fact_revisions")
    op.drop_table("temporal_fact_revisions")
