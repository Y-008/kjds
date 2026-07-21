"""Enforce finite decision and experiment risk semantics in PostgreSQL."""

import sqlalchemy as sa
from alembic import op

revision = "20260717_0032"
down_revision = "20260717_0031"
branch_labels = None
depends_on = None


CHECKS = (
    (
        "decision_contracts",
        "ck_decision_contract_maximum_loss_finite",
        "maximum_loss_amount IS NULL OR "
        "(maximum_loss_amount >= 0 AND maximum_loss_amount <> 'NaN'::numeric)",
    ),
    (
        "decision_analyses",
        "ck_decision_analysis_confidence_range",
        "confidence_decimal >= 0 AND confidence_decimal <= 1 "
        "AND confidence_decimal <> 'NaN'::numeric",
    ),
    (
        "decision_analyses",
        "ck_decision_analysis_forecast_interval",
        "(forecast_value_decimal IS NULL AND forecast_low_decimal IS NULL "
        "AND forecast_high_decimal IS NULL) OR "
        "(forecast_value_decimal IS NOT NULL AND forecast_low_decimal IS NOT NULL "
        "AND forecast_high_decimal IS NOT NULL "
        "AND forecast_value_decimal <> 'NaN'::numeric "
        "AND forecast_low_decimal <> 'NaN'::numeric "
        "AND forecast_high_decimal <> 'NaN'::numeric "
        "AND forecast_low_decimal <= forecast_value_decimal "
        "AND forecast_value_decimal <= forecast_high_decimal)",
    ),
    (
        "decision_outcomes",
        "ck_decision_outcome_interval_finite",
        "predicted_value_decimal <> 'NaN'::numeric "
        "AND interval_low_decimal <> 'NaN'::numeric "
        "AND interval_high_decimal <> 'NaN'::numeric "
        "AND actual_value_decimal <> 'NaN'::numeric "
        "AND interval_low_decimal <= predicted_value_decimal "
        "AND predicted_value_decimal <= interval_high_decimal",
    ),
    (
        "causal_experiment_protocols",
        "ck_causal_experiment_risk_numbers",
        "minimum_detectable_effect_decimal > 0 "
        "AND minimum_detectable_effect_decimal <> 'NaN'::numeric "
        "AND budget_cap_amount_decimal > 0 "
        "AND budget_cap_amount_decimal <> 'NaN'::numeric "
        "AND stop_loss_amount_decimal > 0 "
        "AND stop_loss_amount_decimal <> 'NaN'::numeric "
        "AND stop_loss_amount_decimal <= budget_cap_amount_decimal",
    ),
    (
        "causal_experiment_observations",
        "ck_causal_experiment_observation_finite",
        "value_decimal <> 'NaN'::numeric",
    ),
    (
        "causal_experiment_safety_checks",
        "ck_causal_experiment_safety_finite",
        "value_decimal <> 'NaN'::numeric AND threshold_decimal <> 'NaN'::numeric",
    ),
)


def upgrade() -> None:
    for table, name, condition in CHECKS:
        op.create_check_constraint(name, table, sa.text(condition))


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.drop_constraint(name, table, type_="check")
