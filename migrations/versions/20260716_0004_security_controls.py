"""Add append-only kill switch audit events."""

import sqlalchemy as sa
from alembic import op

revision = "20260716_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kill_switch_events",
        sa.Column("sequence", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("engaged", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(sa.text('ALTER TABLE "kill_switch_events" ENABLE ROW LEVEL SECURITY'))


def downgrade() -> None:
    op.drop_table("kill_switch_events")
