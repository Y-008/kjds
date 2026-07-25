"""Add relational lineage from profit scenarios to logistics calculations."""

import sqlalchemy as sa
from alembic import op

revision = "20260726_0047"
down_revision = "20260726_0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "profit_scenarios",
        sa.Column("logistics_calculation_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_profit_scenario_logistics_calculation",
        "profit_scenarios",
        "logistics_calculations",
        ["logistics_calculation_id"],
        ["id"],
    )
    op.create_index(
        "ix_profit_scenario_logistics_calculation",
        "profit_scenarios",
        ["logistics_calculation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_profit_scenario_logistics_calculation",
        table_name="profit_scenarios",
    )
    op.drop_constraint(
        "fk_profit_scenario_logistics_calculation",
        "profit_scenarios",
        type_="foreignkey",
    )
    op.drop_column("profit_scenarios", "logistics_calculation_id")
