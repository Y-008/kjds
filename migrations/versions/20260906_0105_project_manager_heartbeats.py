"""Persist immutable project-manager heartbeat snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "20260906_0105"
down_revision = "20260906_0104"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_manager_heartbeats",
        sa.Column("heartbeat_id", sa.String(length=200), primary_key=True),
        sa.Column("project_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("entity_id", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("head", sa.String(length=200), nullable=False),
        sa.Column("graph_snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_pm_heartbeat_scope_revision",
        "project_manager_heartbeats",
        ["tenant_id", "entity_id", "project_id", "revision"],
    )
    op.create_index(
        "ix_pm_heartbeat_observed",
        "project_manager_heartbeats",
        ["tenant_id", "entity_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pm_heartbeat_observed", table_name="project_manager_heartbeats")
    op.drop_index("ix_pm_heartbeat_scope_revision", table_name="project_manager_heartbeats")
    op.drop_table("project_manager_heartbeats")
