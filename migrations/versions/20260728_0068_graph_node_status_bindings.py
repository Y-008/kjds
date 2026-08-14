"""Bind canonical Graph nodes to verifier-owned Goal task status."""

import sqlalchemy as sa
from alembic import op

revision = "20260728_0068"
down_revision = "20260728_0067"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_node_status_bindings",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(180),
            sa.ForeignKey("graph_projects.id"),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.String(180),
            sa.ForeignKey("graph_nodes.id"),
            nullable=False,
        ),
        sa.Column(
            "task_id",
            sa.String(180),
            sa.ForeignKey("goal_tasks.id"),
            nullable=False,
        ),
        sa.Column("binding_role", sa.String(40), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "binding_role = 'status_source'",
            name="ck_graph_node_status_binding_role",
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64",
            name="ck_graph_node_status_binding_hash",
        ),
        sa.UniqueConstraint(
            "project_id",
            "node_id",
            "binding_role",
            name="uq_graph_node_status_binding",
        ),
    )
    op.create_index(
        "ix_graph_node_status_bindings_project_id",
        "graph_node_status_bindings",
        ["project_id"],
    )
    op.create_index(
        "ix_graph_node_status_bindings_node_id",
        "graph_node_status_bindings",
        ["node_id"],
    )
    op.create_index(
        "ix_graph_node_status_bindings_task_id",
        "graph_node_status_bindings",
        ["task_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_graph_node_status_bindings_task_id",
        table_name="graph_node_status_bindings",
    )
    op.drop_index(
        "ix_graph_node_status_bindings_node_id",
        table_name="graph_node_status_bindings",
    )
    op.drop_index(
        "ix_graph_node_status_bindings_project_id",
        table_name="graph_node_status_bindings",
    )
    op.drop_table("graph_node_status_bindings")
