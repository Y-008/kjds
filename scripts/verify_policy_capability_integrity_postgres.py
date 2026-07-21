from __future__ import annotations

import json

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
    with engine.connect() as connection:
        policy_outcome_id = connection.scalar(
            text("SELECT id FROM causal_policy_stage_outcomes ORDER BY created_at LIMIT 1")
        )
        capability_id = connection.scalar(
            text("SELECT id FROM capability_economic_assessments ORDER BY created_at LIMIT 1")
        )
    if not policy_outcome_id or not capability_id:
        raise AssertionError("G-1 API smoke did not create policy and capability ledger rows")

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
