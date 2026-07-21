from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from apps.control_plane.database import create_database_engine, database_url

EXPECTED_DATABASE = "kjds_g1_smoke"


def main() -> None:
    url = database_url()
    if make_url(url).database != EXPECTED_DATABASE:
        raise RuntimeError(
            f"Decision verification requires disposable database {EXPECTED_DATABASE!r}"
        )

    engine = create_database_engine(url)
    suffix = uuid4().hex
    now = datetime.now(UTC)
    due = now + timedelta(days=1)
    contract_id = f"g1_dct_{suffix}"
    analysis_id = f"g1_dan_{suffix}"
    resolution_id = f"g1_drs_{suffix}"
    outcome_id = f"g1_out_{suffix}"
    protocol_id = f"g1_xpt_{suffix}"
    assignment_id = f"g1_xas_{suffix}"
    observation_id = f"g1_xob_{suffix}"
    safety_id = f"g1_xsc_{suffix}"

    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO decision_contracts (
                id, request_hash, profile_id, profile_version, objective,
                decision_domain, risk_level, horizon_days, maximum_loss_amount,
                currency, source_contract_id, input_json, output_requirements_json,
                evidence_json, compiler_policy_json, missing_inputs_json, status,
                execution_eligible, requires_human_approval, requested_by, created_at
            ) VALUES (
                :id, :hash, 'decision_review', '1', 'g1', 'risk', 'high', 30, 100,
                'CNY', NULL, '{}'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb,
                '[]'::jsonb, 'ready_for_analysis', false, true, 'g1', :now
            )"""),
            {"id": contract_id, "hash": uuid4().hex, "now": now},
        )
        connection.execute(
            text("""INSERT INTO decision_analyses (
                id, request_hash, contract_id, conclusion, recommended_option_id,
                confidence_decimal, forecast_metric, forecast_value_decimal,
                forecast_low_decimal, forecast_high_decimal, forecast_unit,
                forecast_due_at, assumptions_json, unknowns_json, evidence_json,
                selection_assessment_json, model_ref, submitted_by,
                execution_eligible, created_at
            ) VALUES (
                :id, :hash, :contract, 'g1', NULL, 0.5, 'cm3', 10, 5, 15, 'CNY',
                :due, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb,
                NULL, 'g1', false, :now
            )"""),
            {
                "id": analysis_id,
                "hash": uuid4().hex,
                "contract": contract_id,
                "due": due,
                "now": now,
            },
        )
        connection.execute(
            text("""INSERT INTO decision_resolutions (
                id, request_hash, contract_id, analysis_id, disposition, rationale,
                conditions_json, decided_by, execution_eligible, created_at
            ) VALUES (
                :id, :hash, :contract, :analysis, 'experiment', 'g1', '[]'::jsonb,
                'g1', false, :now
            )"""),
            {
                "id": resolution_id,
                "hash": uuid4().hex,
                "contract": contract_id,
                "analysis": analysis_id,
                "now": now,
            },
        )
        connection.execute(
            text("""INSERT INTO decision_outcomes (
                id, request_hash, resolution_id, metric, predicted_value_decimal,
                interval_low_decimal, interval_high_decimal, actual_value_decimal,
                unit, observed_at, evidence_json, notes, recorded_by, created_at
            ) VALUES (
                :id, :hash, :resolution, 'cm3', 10, 5, 15, 11, 'CNY', :due,
                '[]'::jsonb, 'g1', 'g1', :now
            )"""),
            {
                "id": outcome_id,
                "hash": uuid4().hex,
                "resolution": resolution_id,
                "due": due,
                "now": now,
            },
        )
        connection.execute(
            text("""INSERT INTO causal_experiment_protocols (
                id, request_hash, resolution_id, hypothesis, primary_metric,
                randomization_unit, interference_cluster, variants_json,
                target_sample_size, minimum_detectable_effect_decimal,
                budget_cap_amount_decimal, stop_loss_amount_decimal, currency,
                start_at, end_at, outcome_window_days, guardrails_json,
                stratification_keys_json, effect_metrics_json, assignment_seed,
                evidence_json, created_by, created_at
            ) VALUES (
                :id, :hash, :resolution, 'g1', 'cm3', 'visitor', NULL,
                CAST(:variants AS jsonb),
                20, 1, 100, 10, 'CNY', :now, :due, 7,
                CAST(:guardrails AS jsonb),
                '[]'::jsonb, '[]'::jsonb, :seed, '[]'::jsonb, 'g1', :now
            )"""),
            {
                "id": protocol_id,
                "hash": uuid4().hex,
                "resolution": resolution_id,
                "now": now,
                "due": due,
                "seed": uuid4().hex + uuid4().hex,
                "variants": json.dumps(
                    [
                        {"id": "control", "allocation": "0.5", "control": True},
                        {"id": "test", "allocation": "0.5", "control": False},
                    ]
                ),
                "guardrails": json.dumps(
                    [{"metric": "loss", "direction": "max", "threshold": "10"}]
                ),
            },
        )
        connection.execute(
            text("""INSERT INTO causal_experiment_assignments (
                id, protocol_id, unit_hash, variant_id, strata_json, assigned_at
            ) VALUES (:id, :protocol, :unit_hash, 'control', '{}'::jsonb, :now)"""),
            {
                "id": assignment_id,
                "protocol": protocol_id,
                "unit_hash": uuid4().hex + uuid4().hex,
                "now": now,
            },
        )
        connection.execute(
            text("""INSERT INTO causal_experiment_observations (
                id, request_hash, protocol_id, assignment_id, metric, value_decimal,
                observed_at, evidence_id, created_by, recorded_at
            ) SELECT :id, :hash, :protocol, :assignment, 'cm3', 10, :now, id, 'g1', :now
              FROM evidence_records ORDER BY recorded_at LIMIT 1"""),
            {
                "id": observation_id,
                "hash": uuid4().hex,
                "protocol": protocol_id,
                "assignment": assignment_id,
                "now": now,
            },
        )
        connection.execute(
            text("""INSERT INTO causal_experiment_safety_checks (
                id, request_hash, protocol_id, metric, value_decimal, direction,
                threshold_decimal, status, observed_at, evidence_id, created_by, recorded_at
            ) SELECT :id, :hash, :protocol, 'loss', 1, 'max', 10, 'within_limit',
                :now, id, 'g1', :now FROM evidence_records ORDER BY recorded_at LIMIT 1"""),
            {
                "id": safety_id,
                "hash": uuid4().hex,
                "protocol": protocol_id,
                "now": now,
            },
        )

    statements = {
        "nan_contract_loss": (
            "decision_contracts",
            "UPDATE decision_contracts SET maximum_loss_amount = 'NaN'::numeric WHERE id = :id",
            contract_id,
        ),
        "nan_analysis_confidence": (
            "decision_analyses",
            "UPDATE decision_analyses SET confidence_decimal = 'NaN'::numeric WHERE id = :id",
            analysis_id,
        ),
        "reversed_forecast_interval": (
            "decision_analyses",
            "UPDATE decision_analyses SET forecast_low_decimal = 20 WHERE id = :id",
            analysis_id,
        ),
        "nan_outcome": (
            "decision_outcomes",
            "UPDATE decision_outcomes SET actual_value_decimal = 'NaN'::numeric WHERE id = :id",
            outcome_id,
        ),
        "stop_loss_above_budget": (
            "causal_experiment_protocols",
            "UPDATE causal_experiment_protocols SET stop_loss_amount_decimal = 101 WHERE id = :id",
            protocol_id,
        ),
        "nan_observation": (
            "causal_experiment_observations",
            "UPDATE causal_experiment_observations SET value_decimal = 'NaN'::numeric WHERE id = :id",
            observation_id,
        ),
        "nan_safety_threshold": (
            "causal_experiment_safety_checks",
            "UPDATE causal_experiment_safety_checks SET threshold_decimal = 'NaN'::numeric WHERE id = :id",
            safety_id,
        ),
    }
    rejected = []
    for name, (table, statement, row_id) in statements.items():
        connection = engine.connect()
        transaction = connection.begin()
        try:
            # Ledger immutability is independently verified elsewhere. Disable
            # only user triggers inside this rollback-only transaction so the
            # numeric CHECK itself is exercised.
            connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
            connection.execute(text(statement), {"id": row_id})
        except IntegrityError:
            transaction.rollback()
            rejected.append(name)
        except Exception:
            transaction.rollback()
            raise
        else:
            transaction.rollback()
            raise AssertionError(f"PostgreSQL accepted invalid decision data: {name}")
        finally:
            connection.close()

    expected = {
        "ck_decision_contract_maximum_loss_finite",
        "ck_decision_analysis_confidence_range",
        "ck_decision_analysis_forecast_interval",
        "ck_decision_outcome_interval_finite",
        "ck_causal_experiment_risk_numbers",
        "ck_causal_experiment_observation_finite",
        "ck_causal_experiment_safety_finite",
    }
    with engine.connect() as connection:
        constraints = set(
            connection.execute(
                text("""SELECT conname FROM pg_constraint
                WHERE conrelid IN (
                    'decision_contracts'::regclass, 'decision_analyses'::regclass,
                    'decision_outcomes'::regclass, 'causal_experiment_protocols'::regclass,
                    'causal_experiment_observations'::regclass,
                    'causal_experiment_safety_checks'::regclass
                ) AND contype = 'c'""")
            ).scalars()
        )
    if not expected.issubset(constraints):
        raise AssertionError(f"Missing decision constraints: {sorted(expected - constraints)}")

    cleanup = (
        ("causal_experiment_safety_checks", safety_id),
        ("causal_experiment_observations", observation_id),
        ("causal_experiment_assignments", assignment_id),
        ("causal_experiment_protocols", protocol_id),
        ("decision_outcomes", outcome_id),
        ("decision_resolutions", resolution_id),
        ("decision_analyses", analysis_id),
        ("decision_contracts", contract_id),
    )
    with engine.begin() as connection:
        for table, _ in cleanup:
            connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        for table, row_id in cleanup:
            connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
        for table, _ in reversed(cleanup):
            connection.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))

    print(
        {
            "database": EXPECTED_DATABASE,
            "rejected": rejected,
            "constraint_count": len(expected),
            "status": "passed",
        }
    )


if __name__ == "__main__":
    main()
