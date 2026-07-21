from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from apps.control_plane.database import create_database_engine, database_url
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import (
    REQUIRED_COST_EVIDENCE_KEYS,
    ProfitInputs,
    SourcePlatform,
    SourcingService,
    SupplierOffer,
)
from apps.control_plane.sourcing_store import SqlSourcingStore
from apps.control_plane.sql_repository import SqlAlchemyRepository

EXPECTED_DATABASE = "kjds_g1_smoke"


def main() -> None:
    url = database_url()
    if make_url(url).database != EXPECTED_DATABASE:
        raise RuntimeError(f"Sourcing verification requires disposable database {EXPECTED_DATABASE!r}")

    engine = create_database_engine(url)
    repository = SqlAlchemyRepository(engine)
    product = CommerceService(repository, lambda _evidence: None).create_product(
        sku=f"G1-SOURCING-{uuid4().hex}",
        name="sourcing numeric integrity probe",
    )

    def invalid_offer(*, unit_price: Decimal, logistics: Decimal) -> None:
        with engine.begin() as connection:
            connection.execute(
                text("""
                    INSERT INTO source_offers (
                        id, product_id, supplier_ref, platform, external_id, source_url, title, currency,
                        unit_price_decimal, source_to_cny_rate_decimal, min_order_quantity, weight_kg_decimal,
                        length_cm_decimal, width_cm_decimal, height_cm_decimal,
                        domestic_logistics_per_unit_decimal, evidence_ref, attributes_json, media_json, captured_at
                    ) VALUES (
                        :id, :product_id, 'g1-factory', 'manual', :external_id, 'https://example.com/g1',
                        'invalid offer probe', 'CNY', :unit_price, 1, 1, 1, 0, 0, 0, :logistics,
                        'evidence://g1/sourcing', '{}'::jsonb, '[]'::jsonb, :captured_at
                    )
                """),
                {
                    "id": f"off_{uuid4().hex}",
                    "product_id": product.id,
                    "external_id": uuid4().hex,
                    "unit_price": unit_price,
                    "logistics": logistics,
                    "captured_at": datetime.now(UTC),
                },
            )

    rejected = []
    for name, values in (
        ("negative_unit_price", {"unit_price": Decimal("-0.01"), "logistics": Decimal("0")}),
        ("nan_unit_price", {"unit_price": Decimal("NaN"), "logistics": Decimal("0")}),
        ("negative_logistics", {"unit_price": Decimal("1"), "logistics": Decimal("-0.01")}),
    ):
        try:
            invalid_offer(**values)
        except IntegrityError:
            rejected.append(name)
        else:
            raise AssertionError(f"PostgreSQL accepted invalid sourcing data: {name}")

    with engine.connect() as connection:
        constraints = set(
            connection.execute(
                text("""
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid IN ('source_offers'::regclass, 'profit_scenarios'::regclass)
                      AND contype = 'c'
                """)
            ).scalars()
        )
    expected = {
        "ck_source_offers_unit_price_positive",
        "ck_source_offers_domestic_logistics_nonnegative",
        "ck_profit_scenarios_costs_nonnegative",
        "ck_profit_scenarios_named_costs_nonnegative",
    }
    if not expected.issubset(constraints):
        raise AssertionError(f"Missing sourcing constraints: {sorted(expected - constraints)}")

    store = SqlSourcingStore(engine)
    offer = store.save_offer(
        SupplierOffer(
            product_id=product.id,
            supplier_ref="g1-full-cost-factory",
            platform=SourcePlatform.MANUAL,
            external_id=uuid4().hex,
            source_url="https://example.com/g1/full-cost",
            title="full-cost persistence probe",
            currency="CNY",
            unit_price=Decimal("20"),
            source_to_cny_rate=Decimal("1"),
            min_order_quantity=1,
            weight_kg=Decimal("0.5"),
            length_cm=Decimal("1"),
            width_cm=Decimal("1"),
            height_cm=Decimal("1"),
            domestic_logistics_per_unit=Decimal("1"),
            evidence_ref="evidence://g1/full-cost-offer",
        )
    )
    assumption = "evidence://g1/full-cost-assumptions"
    scenario = SourcingService(store, repository, lambda _ids: None).calculate_profit(
        offer.id,
        ProfitInputs(
            sale_price_rub=Decimal("1800"),
            rub_per_cny=Decimal("12"),
            international_freight_cny_per_kg=Decimal("30"),
            packaging_cny=Decimal("2"),
            last_mile_cny=Decimal("10"),
            customs_rate=Decimal("0.10"),
            platform_fee_rate=Decimal("0.10"),
            advertising_rate=Decimal("0.05"),
            return_reserve_rate=Decimal("0.10"),
            warehousing_cny=Decimal("1"),
            tax_cny=Decimal("2"),
            fx_cost_cny=Decimal("1"),
            capital_cost_cny=Decimal("1"),
            aftersales_cny=Decimal("1"),
            loss_reserve_cny=Decimal("1"),
        ),
        [assumption],
        {
            key: assumption
            for key in REQUIRED_COST_EVIDENCE_KEYS
            if key not in {"product_cost", "domestic_logistics"}
        },
    )
    loaded = store.get_scenario(scenario.id)
    if not loaded.cost_complete or loaded.tax_cny != Decimal("2.00000000"):
        raise AssertionError("Named full-cost scenario did not survive PostgreSQL round trip")
    try:
        store.save_scenario(
            replace(
                scenario,
                id=f"scn_{uuid4().hex}",
                warehousing_cny=Decimal("-0.01"),
            )
        )
    except IntegrityError:
        rejected.append("negative_named_cost")
    else:
        raise AssertionError("PostgreSQL accepted a negative named scenario cost")

    print(
        {
            "database": EXPECTED_DATABASE,
            "rejected": rejected,
            "constraint_count": len(constraints),
            "full_cost_scenario": scenario.id,
            "status": "passed",
        }
    )


if __name__ == "__main__":
    main()
