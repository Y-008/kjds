from __future__ import annotations

import json
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError

from apps.control_plane.database import create_database_engine, database_url

EXPECTED_DATABASE = "kjds_g1_smoke"


def main() -> None:
    url = database_url()
    if make_url(url).database != EXPECTED_DATABASE:
        raise RuntimeError(
            f"Policy capability verification requires disposable database {EXPECTED_DATABASE!r}"
        )

    engine = create_database_engine(url)
    policy_outcome_id = f"g1-policy-outcome-{uuid4().hex}"
    capability_id = f"g1-capability-{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("""INSERT INTO causal_policy_stage_outcomes (
                id, request_hash, release_id, verdict, observation_count,
                incremental_value_decimal, guardrail_breached, notes,
                evidence_json, recorded_by, created_at
            ) VALUES (
                :id, :request_hash, :release_id, 'continue', 1,
                1, false, 'G-1 numeric constraint fixture',
                '{}'::json, 'g1-verifier', now()
            )"""),
            {
                "id": policy_outcome_id,
                "request_hash": uuid4().hex.ljust(64, "0"),
                "release_id": f"g1-release-{uuid4().hex}",
            },
        )
        connection.execute(
            text("""INSERT INTO capability_economic_assessments (
                id, request_hash, window_id, plan_id, policy_id, adapter_id,
                outcome_status, realized_incremental_value, avoided_loss,
                model_compute_cost, human_review_cost, incident_loss,
                maintenance_cost, net_value, currency, evidence_json,
                assessed_by, created_at
            ) VALUES (
                :id, :request_hash, :window_id, :plan_id, :policy_id, 'g1-adapter',
                'observed', 10, 0, 1, 1, 0, 1, 7, 'RUB', '{}'::json,
                'g1-verifier', now()
            )"""),
            {
                "id": capability_id,
                "request_hash": uuid4().hex.ljust(64, "0"),
                "window_id": f"g1-window-{uuid4().hex}",
                "plan_id": f"g1-plan-{uuid4().hex}",
                "policy_id": f"g1-policy-{uuid4().hex}",
            },
        )

    statements = {
        "nan_policy_incremental_value": (
            "causal_policy_stage_outcomes",
            "UPDATE causal_policy_stage_outcomes "
            "SET incremental_value_decimal = 'NaN'::numeric WHERE id = :id",
            policy_outcome_id,
        ),
        "infinite_realized_value": (
            "capability_economic_assessments",
            "UPDATE capability_economic_assessments "
            "SET realized_incremental_value = 'Infinity'::numeric WHERE id = :id",
            capability_id,
        ),
        "negative_model_cost": (
            "capability_economic_assessments",
            "UPDATE capability_economic_assessments SET model_compute_cost = -1 WHERE id = :id",
            capability_id,
        ),
        "inconsistent_net_value": (
            "capability_economic_assessments",
            "UPDATE capability_economic_assessments SET net_value = net_value + 1 WHERE id = :id",
            capability_id,
        ),
        "non_ascii_currency": (
            "capability_economic_assessments",
            "UPDATE capability_economic_assessments SET currency = 'РУБ' WHERE id = :id",
            capability_id,
        ),
    }
    rejected = []
    for name, (table, statement, row_id) in statements.items():
        connection = engine.connect()
        transaction = connection.begin()
        try:
            connection.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
            connection.execute(text(statement), {"id": row_id})
        except (DataError, IntegrityError):
            transaction.rollback()
            rejected.append(name)
        except Exception:
            transaction.rollback()
            raise
        else:
            transaction.rollback()
            raise AssertionError(f"PostgreSQL accepted invalid policy capability data: {name}")
        finally:
            connection.close()

    expected = {
        "ck_causal_policy_stage_value_finite",
        "ck_capability_economic_values_finite",
        "ck_capability_economic_costs_nonnegative",
        "ck_capability_economic_net_consistent",
        "ck_capability_economic_currency_ascii",
    }
    with engine.connect() as connection:
        constraints = set(
            connection.execute(
                text("""SELECT conname FROM pg_constraint
                WHERE conrelid IN (
                    'causal_policy_stage_outcomes'::regclass,
                    'capability_economic_assessments'::regclass
                ) AND contype = 'c'""")
            ).scalars()
        )
    if not expected.issubset(constraints):
        raise AssertionError(
            f"Missing policy capability constraints: {sorted(expected - constraints)}"
        )

    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("DELETE FROM capability_economic_assessments WHERE id = :id"),
            {"id": capability_id},
        )
        connection.execute(
            text("DELETE FROM causal_policy_stage_outcomes WHERE id = :id"),
            {"id": policy_outcome_id},
        )

    print(
        json.dumps(
            {
                "database": EXPECTED_DATABASE,
                "constraints": sorted(expected),
                "rejected_invalid_writes": rejected,
                "rejected_count": len(rejected),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
