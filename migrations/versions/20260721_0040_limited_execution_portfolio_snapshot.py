"""Freeze the aggregate action budget snapshot on limited execution commands."""

import sqlalchemy as sa
from alembic import op

revision = "20260721_0040"
down_revision = "20260721_0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "limited_execution_commands",
        sa.Column(
            "portfolio_risk_json",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.alter_column("limited_execution_commands", "portfolio_risk_json", server_default=None)


def downgrade() -> None:
    op.drop_column("limited_execution_commands", "portfolio_risk_json")
