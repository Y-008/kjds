"""Add append-only Graph project operating-subject binding events."""
import sqlalchemy as sa
from alembic import op

revision = "20260728_0070"
down_revision = "20260728_0069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_project_subject_binding_events",
        sa.Column("sequence", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("id", sa.String(length=180), nullable=False),
        sa.Column("project_id", sa.String(length=180), nullable=False),
        sa.Column("tenant_ref", sa.String(length=160), nullable=False),
        sa.Column("store_ref", sa.String(length=160), nullable=False),
        sa.Column("subject_actor_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.String(length=160), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_type in ('bind', 'revoke')",
            name="ck_graph_project_subject_binding_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["graph_projects.id"],
        ),
        sa.PrimaryKeyConstraint("sequence"),
        sa.UniqueConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "idempotency_key",
            name="uq_graph_project_subject_binding_idempotency",
        ),
    )
    op.create_index(
        "ix_graph_project_subject_binding_events_project_id",
        "graph_project_subject_binding_events",
        ["project_id"],
    )
    op.create_index(
        "ix_graph_project_subject_binding_events_effective_at",
        "graph_project_subject_binding_events",
        ["effective_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_graph_project_subject_binding_events_effective_at",
        table_name="graph_project_subject_binding_events",
    )
    op.drop_index(
        "ix_graph_project_subject_binding_events_project_id",
        table_name="graph_project_subject_binding_events",
    )
    op.drop_table("graph_project_subject_binding_events")
