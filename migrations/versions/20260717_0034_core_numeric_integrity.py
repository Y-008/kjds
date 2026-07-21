"""Enforce numeric semantics on legacy core business ledgers."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0034"
down_revision = "20260717_0033"
branch_labels = None
depends_on = None


CHECKS = (
    (
        "orders",
        "ck_orders_business_numbers",
        "quantity > 0 AND gross_revenue_decimal >= 0 "
        "AND gross_revenue_decimal <> 'NaN'::numeric "
        "AND booked_fx_rate_decimal > 0 AND booked_fx_rate_decimal <> 'NaN'::numeric "
        "AND currency ~ '^[A-Z]{3}$'",
    ),
    (
        "charges",
        "ck_charges_business_numbers",
        "amount_decimal >= 0 AND amount_decimal <> 'NaN'::numeric "
        "AND fx_rate_decimal > 0 AND fx_rate_decimal <> 'NaN'::numeric "
        "AND currency ~ '^[A-Z]{3}$'",
    ),
    (
        "market_observations",
        "ck_market_observation_numbers",
        "value_decimal <> 'NaN'::numeric AND confidence_decimal >= 0 "
        "AND confidence_decimal <= 1 AND confidence_decimal <> 'NaN'::numeric",
    ),
    (
        "opportunities",
        "ck_opportunity_score_range",
        "score_decimal >= 0 AND score_decimal <= 100 AND score_decimal <> 'NaN'::numeric",
    ),
    (
        "growth_experiments",
        "ck_growth_experiment_risk_numbers",
        "budget_cap_cny_decimal > 0 AND budget_cap_cny_decimal <> 'NaN'::numeric "
        "AND stop_loss_cny_decimal > 0 AND stop_loss_cny_decimal <> 'NaN'::numeric "
        "AND stop_loss_cny_decimal <= budget_cap_cny_decimal",
    ),
    (
        "decision_recommendations",
        "ck_recommendation_expected_value_finite",
        "expected_cm3_delta_decimal IS NULL OR expected_cm3_delta_decimal <> 'NaN'::numeric",
    ),
    (
        "sample_purchase_orders",
        "ck_sample_purchase_order_numbers",
        "quantity > 0 AND unit_price > 0 AND unit_price <> 'NaN'::numeric "
        "AND currency ~ '^[A-Z]{3}$'",
    ),
)


def upgrade() -> None:
    for table, name, condition in CHECKS:
        op.create_check_constraint(name, table, sa.text(condition))


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
