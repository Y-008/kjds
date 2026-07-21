from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError

from apps.control_plane.database import create_database_engine, database_url

EXPECTED_DATABASE = "kjds_g1_smoke"


def main() -> None:
    url = database_url()
    if make_url(url).database != EXPECTED_DATABASE:
        raise RuntimeError(f"Core verification requires disposable database {EXPECTED_DATABASE!r}")

    engine = create_database_engine(url)
    suffix = uuid4().hex
    now = datetime.now(UTC)
    ids = {
        "product": f"g1_prd_{suffix}",
        "approval": f"g1_apr_{suffix}",
        "sample_order": f"g1_smp_{suffix}",
        "order": f"g1_ord_{suffix}",
        "charge": f"g1_chg_{suffix}",
        "observation": f"g1_obs_{suffix}",
        "opportunity": f"g1_opp_{suffix}",
        "experiment": f"g1_exp_{suffix}",
        "recommendation": f"g1_rec_{suffix}",
    }
    with engine.begin() as connection:
        # These rows only exercise CHECK constraints. Keep the fixture independent from
        # domain workflow ordering and bypass unrelated sourcing foreign keys locally.
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("""INSERT INTO products (
                id, sku, name, market, channel, status, created_at
            ) VALUES (:id, :sku, 'G-1 numeric fixture', 'RU', 'OZON', 'draft', :now)"""),
            {"id": ids["product"], "sku": f"G1-{suffix}", "now": now},
        )
        connection.execute(
            text("""INSERT INTO approvals (
                id, action, resource_type, resource_id, requested_by, payload_json,
                status, decided_by, decision_reason, created_at
            ) VALUES (:id, 'sample_purchase', 'product', :product, 'g1', '{}'::jsonb,
                'approved', 'g1', 'numeric fixture', :now)"""),
            {
                "id": ids["approval"],
                "product": ids["product"],
                "now": now,
            },
        )
        connection.execute(
            text("""INSERT INTO sample_purchase_orders (
                id, approval_id, product_id, offer_id, scenario_id, supplier_ref,
                quantity, currency, unit_price, requested_by, created_at
            ) VALUES (:id, :approval, :product, 'g1-offer', 'g1-scenario', 'g1-supplier',
                1, 'CNY', 10, 'g1', :now)"""),
            {
                "id": ids["sample_order"],
                "approval": ids["approval"],
                "product": ids["product"],
                "now": now,
            },
        )
        connection.execute(
            text("""INSERT INTO orders (
                id, external_id, product_id, quantity, currency, gross_revenue_decimal,
                booked_fx_rate_decimal, status, created_at
            ) VALUES (:id, :external, :product, 1, 'CNY', 100, 1, 'created', :now)"""),
            {
                "id": ids["order"],
                "external": f"g1-{suffix}",
                "product": ids["product"],
                "now": now,
            },
        )
        connection.execute(
            text("""INSERT INTO charges (
                id, order_id, kind, amount_decimal, currency, fx_rate_decimal,
                evidence_ref, created_at
            ) VALUES (:id, :order, 'platform_fee', 10, 'CNY', 1, 'g1', :now)"""),
            {"id": ids["charge"], "order": ids["order"], "now": now},
        )
        connection.execute(
            text("""INSERT INTO market_observations (
                id, source, market, category, metric, value_decimal, observed_at,
                source_ref, confidence_decimal, dimensions_json, ingested_at
            ) VALUES (:id, 'g1', 'RU', 'g1', 'demand', 10, :now, 'g1', 0.8, '{}'::jsonb, :now)"""),
            {"id": ids["observation"], "now": now},
        )
        connection.execute(
            text("""INSERT INTO opportunities (
                id, market, category, title, score_decimal, rationale_json,
                evidence_ids_json, recommended_action, created_at
            ) VALUES (:id, 'RU', 'g1', 'g1', 80, '[]'::jsonb, '[]'::jsonb, 'observe', :now)"""),
            {"id": ids["opportunity"], "now": now},
        )
        connection.execute(
            text("""INSERT INTO growth_experiments (
                id, product_id, channel, hypothesis, primary_metric,
                budget_cap_cny_decimal, stop_loss_cny_decimal, variants_json, status, created_at
            ) VALUES (:id, :product, 'OZON', 'g1', 'cm3', 100, 10, '[]'::jsonb, 'draft', :now)"""),
            {"id": ids["experiment"], "product": ids["product"], "now": now},
        )
        connection.execute(
            text("""INSERT INTO decision_recommendations (
                id, product_id, agent, action, rationale, evidence_json,
                expected_cm3_delta_decimal, risk, status, shadow_mode, created_at, decided_at
            ) VALUES (:id, :product, 'g1', 'observe', 'g1', '[]'::jsonb, 5,
                'low', 'observing', true, :now, NULL)"""),
            {"id": ids["recommendation"], "product": ids["product"], "now": now},
        )

    statements = {
        "nan_order_revenue": (
            "orders",
            "UPDATE orders SET gross_revenue_decimal = 'NaN'::numeric WHERE id = :id",
            ids["order"],
        ),
        "negative_charge": (
            "charges",
            "UPDATE charges SET amount_decimal = -1 WHERE id = :id",
            ids["charge"],
        ),
        "nan_market_confidence": (
            "market_observations",
            "UPDATE market_observations SET confidence_decimal = 'NaN'::numeric WHERE id = :id",
            ids["observation"],
        ),
        "opportunity_score_above_one_hundred": (
            "opportunities",
            "UPDATE opportunities SET score_decimal = 101 WHERE id = :id",
            ids["opportunity"],
        ),
        "growth_stop_loss_above_budget": (
            "growth_experiments",
            "UPDATE growth_experiments SET stop_loss_cny_decimal = 101 WHERE id = :id",
            ids["experiment"],
        ),
        "nan_recommendation_value": (
            "decision_recommendations",
            "UPDATE decision_recommendations "
            "SET expected_cm3_delta_decimal = 'NaN'::numeric WHERE id = :id",
            ids["recommendation"],
        ),
        "negative_sample_price": (
            "sample_purchase_orders",
            "UPDATE sample_purchase_orders SET unit_price = -1 WHERE id = :id",
            ids["sample_order"],
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
            raise AssertionError(f"PostgreSQL accepted invalid core data: {name}")
        finally:
            connection.close()

    expected = {
        "ck_orders_business_numbers",
        "ck_charges_business_numbers",
        "ck_market_observation_numbers",
        "ck_opportunity_score_range",
        "ck_growth_experiment_risk_numbers",
        "ck_recommendation_expected_value_finite",
        "ck_sample_purchase_order_numbers",
    }
    with engine.connect() as connection:
        constraints = set(
            connection.execute(
                text("""SELECT conname FROM pg_constraint
                WHERE conrelid IN (
                    'orders'::regclass, 'charges'::regclass,
                    'market_observations'::regclass, 'opportunities'::regclass,
                    'growth_experiments'::regclass, 'decision_recommendations'::regclass,
                    'sample_purchase_orders'::regclass
                ) AND contype = 'c'""")
            ).scalars()
        )
    if not expected.issubset(constraints):
        raise AssertionError(f"Missing core constraints: {sorted(expected - constraints)}")

    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        for table, key in (
            ("decision_recommendations", "recommendation"),
            ("growth_experiments", "experiment"),
            ("opportunities", "opportunity"),
            ("market_observations", "observation"),
            ("charges", "charge"),
            ("orders", "order"),
            ("sample_purchase_orders", "sample_order"),
            ("approvals", "approval"),
            ("products", "product"),
        ):
            connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": ids[key]})

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
