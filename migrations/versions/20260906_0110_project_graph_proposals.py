"""Persist immutable project-graph dispatch and invalidation proposals.

Revision ID: 20260906_0110
Revises: 20260906_0109
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260906_0110"
down_revision = "20260906_0109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_graph_proposals",
        sa.Column("proposal_id", sa.String(length=220), primary_key=True),
        sa.Column("project_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=160), nullable=False),
        sa.Column("entity_id", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("proposal_sha256", sa.String(length=64), nullable=False),
        sa.Column("graph_snapshot_sha256", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "external_write_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("recorded_by", sa.String(length=160), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "kind",
            "idempotency_key",
            name="uq_graph_proposal_scope_idempotency",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "kind",
            "revision",
            name="uq_graph_proposal_scope_revision",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_graph_proposal_revision_positive"
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_graph_proposal_request_hash_shape",
        ),
        sa.CheckConstraint(
            "length(proposal_sha256) = 64",
            name="ck_graph_proposal_proposal_hash_shape",
        ),
        sa.CheckConstraint(
            "length(payload_sha256) = 64",
            name="ck_graph_proposal_payload_hash_shape",
        ),
        sa.CheckConstraint(
            "external_write_allowed = false",
            name="ck_graph_proposal_external_write_forbidden",
        ),
    )
    op.create_index(
        "ix_graph_proposal_scope_recorded",
        "project_graph_proposals",
        [
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "recorded_at",
        ],
    )
    op.create_index(
        "ix_graph_proposal_scope_kind_revision",
        "project_graph_proposals",
        [
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "kind",
            "revision",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_graph_proposal_scope_kind_revision",
        table_name="project_graph_proposals",
    )
    op.drop_index(
        "ix_graph_proposal_scope_recorded",
        table_name="project_graph_proposals",
    )
    op.drop_table("project_graph_proposals")
