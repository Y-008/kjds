"""Enforce finite policy outcomes and balanced capability economics."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0033"
down_revision = "20260717_0032"
branch_labels = None
depends_on = None


CHECKS = (
    (
        "causal_policy_stage_outcomes",
        "ck_causal_policy_stage_value_finite",
        "incremental_value_decimal NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
    ),
    (
        "capability_economic_assessments",
        "ck_capability_economic_values_finite",
        "realized_incremental_value NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND avoided_loss NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND model_compute_cost NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND human_review_cost NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND incident_loss NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND maintenance_cost NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) "
        "AND net_value NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric)",
    ),
    (
        "capability_economic_assessments",
        "ck_capability_economic_costs_nonnegative",
        "avoided_loss >= 0 AND model_compute_cost >= 0 AND human_review_cost >= 0 "
        "AND incident_loss >= 0 AND maintenance_cost >= 0",
    ),
    (
        "capability_economic_assessments",
        "ck_capability_economic_net_consistent",
        "net_value = realized_incremental_value + avoided_loss - model_compute_cost "
        "- human_review_cost - incident_loss - maintenance_cost",
    ),
    (
        "capability_economic_assessments",
        "ck_capability_economic_currency_ascii",
        "currency ~ '^[A-Z]{3}$'",
    ),
)


def upgrade() -> None:
    for table, name, condition in CHECKS:
        op.create_check_constraint(name, table, sa.text(condition))


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
