"""Persist named full-cost scenario amounts and per-cost evidence."""

import sqlalchemy as sa
from alembic import op

revision = "20260719_0037"
down_revision = "20260718_0036"
branch_labels = None
depends_on = None


NAMED_COST_COLUMNS = (
    "warehousing_cny_decimal",
    "tax_cny_decimal",
    "fx_cost_cny_decimal",
    "capital_cost_cny_decimal",
    "aftersales_cny_decimal",
    "loss_reserve_cny_decimal",
)


def upgrade() -> None:
    for name in NAMED_COST_COLUMNS:
        op.add_column(
            "profit_scenarios",
            sa.Column(name, sa.Numeric(24, 8), server_default="0", nullable=False),
        )
        op.alter_column("profit_scenarios", name, server_default=None)
    op.add_column(
        "profit_scenarios",
        sa.Column(
            "cost_evidence_json",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )
    op.alter_column("profit_scenarios", "cost_evidence_json", server_default=None)
    checks = " AND ".join(f"{name} >= 0 AND {name} <> 'NaN'::numeric" for name in NAMED_COST_COLUMNS)
    op.create_check_constraint(
        "ck_profit_scenarios_named_costs_nonnegative",
        "profit_scenarios",
        sa.text(checks),
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_profit_scenarios_named_costs_nonnegative",
        "profit_scenarios",
        type_="check",
    )
    op.drop_column("profit_scenarios", "cost_evidence_json")
    for name in reversed(NAMED_COST_COLUMNS):
        op.drop_column("profit_scenarios", name)
