"""Persist structured best-solution decision analysis assessments."""

import sqlalchemy as sa
from alembic import op

revision = "20260720_0038"
down_revision = "20260719_0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "decision_analyses",
        sa.Column(
            "selection_assessment_json",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.alter_column(
        "decision_analyses",
        "selection_assessment_json",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("decision_analyses", "selection_assessment_json")
