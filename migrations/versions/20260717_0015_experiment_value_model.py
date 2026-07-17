"""Add preregistered experiment strata and incremental value metrics."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0015"
down_revision = "20260717_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "causal_experiment_protocols",
        sa.Column(
            "stratification_keys_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "causal_experiment_protocols",
        sa.Column(
            "effect_metrics_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "causal_experiment_assignments",
        sa.Column(
            "strata_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("causal_experiment_assignments", "strata_json")
    op.drop_column("causal_experiment_protocols", "effect_metrics_json")
    op.drop_column("causal_experiment_protocols", "stratification_keys_json")
