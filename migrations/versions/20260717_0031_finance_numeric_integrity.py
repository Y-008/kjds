"""Enforce finite finance and imported monetary semantics in PostgreSQL."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0031"
down_revision = "20260717_0030"
branch_labels = None
depends_on = None


CHECKS = (
    ("fx_rates", "ck_fx_rates_rate_positive", "rate > 0 AND rate <> 'NaN'::numeric"),
    ("finance_entries", "ck_finance_entries_amount_finite", "amount <> 'NaN'::numeric"),
    (
        "reconciliation_runs",
        "ck_reconciliation_tolerance_range",
        "tolerance_ratio >= 0 AND tolerance_ratio < 1 AND tolerance_ratio <> 'NaN'::numeric",
    ),
    ("cash_plan_items", "ck_cash_plan_amount_finite", "amount <> 'NaN'::numeric"),
    (
        "cash_plan_items",
        "ck_cash_plan_probability_range",
        "probability >= 0 AND probability <= 1 AND probability <> 'NaN'::numeric",
    ),
)


def upgrade() -> None:
    for table, name, condition in CHECKS:
        op.create_check_constraint(name, table, sa.text(condition))


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
