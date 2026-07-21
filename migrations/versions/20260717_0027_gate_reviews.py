"""Add structured governance gate review contracts."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0027"
down_revision = "20260717_0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gate_reviews",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=300), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("gate_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("approver_id", sa.String(), nullable=False),
        sa.Column("participants_json", sa.JSON(), nullable=False),
        sa.Column("objective", sa.String(), nullable=False),
        sa.Column("exit_criteria", sa.String(), nullable=False),
        sa.Column("deliverables_json", sa.JSON(), nullable=False),
        sa.Column("evidence_ids_json", sa.JSON(), nullable=False),
        sa.Column("unknowns_json", sa.JSON(), nullable=False),
        sa.Column("blockers_json", sa.JSON(), nullable=False),
        sa.Column("risk_budget_json", sa.JSON(), nullable=False),
        sa.Column("max_loss_json", sa.JSON(), nullable=False),
        sa.Column("rollback_plan", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("rationale", sa.String(), nullable=True),
        sa.Column("conditions_json", sa.JSON(), nullable=False),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_gate_reviews_gate_status", "gate_reviews", ["gate_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_gate_reviews_gate_status", table_name="gate_reviews")
    op.drop_table("gate_reviews")
