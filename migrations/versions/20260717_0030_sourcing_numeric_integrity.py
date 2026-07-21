"""Enforce sourcing amount and measurement semantics in PostgreSQL."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0030"
down_revision = "20260717_0029"
branch_labels = None
depends_on = None


OFFER_CHECKS = {
    "ck_source_offers_unit_price_positive": "unit_price_decimal > 0 AND unit_price_decimal <> 'NaN'::numeric",
    "ck_source_offers_fx_positive": (
        "source_to_cny_rate_decimal > 0 AND source_to_cny_rate_decimal <> 'NaN'::numeric"
    ),
    "ck_source_offers_moq_positive": "min_order_quantity > 0",
    "ck_source_offers_weight_positive": "weight_kg_decimal > 0 AND weight_kg_decimal <> 'NaN'::numeric",
    "ck_source_offers_dimensions_nonnegative": (
        "length_cm_decimal >= 0 AND width_cm_decimal >= 0 AND height_cm_decimal >= 0 "
        "AND length_cm_decimal <> 'NaN'::numeric AND width_cm_decimal <> 'NaN'::numeric "
        "AND height_cm_decimal <> 'NaN'::numeric"
    ),
    "ck_source_offers_domestic_logistics_nonnegative": (
        "domestic_logistics_per_unit_decimal >= 0 "
        "AND domestic_logistics_per_unit_decimal <> 'NaN'::numeric"
    ),
}

SCENARIO_CHECKS = {
    "ck_profit_scenarios_revenue_positive": "revenue_cny_decimal > 0 AND revenue_cny_decimal <> 'NaN'::numeric",
    "ck_profit_scenarios_purchase_positive": "purchase_cny_decimal > 0 AND purchase_cny_decimal <> 'NaN'::numeric",
    "ck_profit_scenarios_costs_nonnegative": (
        "domestic_logistics_cny_decimal >= 0 AND international_logistics_cny_decimal >= 0 "
        "AND packaging_cny_decimal >= 0 AND customs_cny_decimal >= 0 AND last_mile_cny_decimal >= 0 "
        "AND platform_fee_cny_decimal >= 0 AND advertising_cny_decimal >= 0 "
        "AND return_reserve_cny_decimal >= 0 AND other_cost_cny_decimal >= 0 "
        "AND total_cost_cny_decimal >= 0 "
        "AND domestic_logistics_cny_decimal <> 'NaN'::numeric "
        "AND international_logistics_cny_decimal <> 'NaN'::numeric "
        "AND packaging_cny_decimal <> 'NaN'::numeric AND customs_cny_decimal <> 'NaN'::numeric "
        "AND last_mile_cny_decimal <> 'NaN'::numeric AND platform_fee_cny_decimal <> 'NaN'::numeric "
        "AND advertising_cny_decimal <> 'NaN'::numeric AND return_reserve_cny_decimal <> 'NaN'::numeric "
        "AND other_cost_cny_decimal <> 'NaN'::numeric AND total_cost_cny_decimal <> 'NaN'::numeric"
    ),
    "ck_profit_scenarios_break_even_positive": (
        "break_even_price_rub_decimal > 0 AND break_even_price_rub_decimal <> 'NaN'::numeric"
    ),
    "ck_profit_scenarios_cm3_finite": (
        "cm3_cny_decimal <> 'NaN'::numeric AND cm3_rate_decimal <> 'NaN'::numeric"
    ),
}


def upgrade() -> None:
    for name, condition in OFFER_CHECKS.items():
        op.create_check_constraint(name, "source_offers", sa.text(condition))
    for name, condition in SCENARIO_CHECKS.items():
        op.create_check_constraint(name, "profit_scenarios", sa.text(condition))


def downgrade() -> None:
    for name in reversed(SCENARIO_CHECKS):
        op.drop_constraint(name, "profit_scenarios", type_="check")
    for name in reversed(OFFER_CHECKS):
        op.drop_constraint(name, "source_offers", type_="check")
