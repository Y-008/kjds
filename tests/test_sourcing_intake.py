from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceService
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import ProfitInputs, SourcePlatform, SourcingService
from apps.control_plane.sourcing_intake import OfferEvidencePayload, SupplierComparisonIntakeService
from apps.control_plane.sql_repository import Base


class MemorySourcingStore:
    def __init__(self):
        self.offers = {}
        self.offer_keys = {}
        self.scenarios = {}

    def save_offer(self, offer):
        key = (offer.platform, offer.external_id)
        if key in self.offer_keys:
            return self.offers[self.offer_keys[key]]
        self.offers[offer.id] = offer
        self.offer_keys[key] = offer.id
        return offer

    def get_offer(self, offer_id):
        return self.offers[offer_id]

    def list_offers(self, limit=100):
        return list(self.offers.values())[:limit]

    def save_scenario(self, scenario):
        self.scenarios[scenario.id] = scenario
        return scenario

    def get_scenario(self, scenario_id):
        return self.scenarios[scenario_id]

    def list_scenarios(self, limit=1000):
        return list(reversed(list(self.scenarios.values())))[:limit]


def make_intake():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    repository = InMemoryRepository()
    commerce = CommerceService(repository, evidence_validator=evidence.require_valid)
    product = commerce.create_product(sku="RU-001", name="Storage box")
    store = MemorySourcingStore()
    sourcing = SourcingService(store, repository, evidence_validator=evidence.require_valid)
    return product, store, SupplierComparisonIntakeService(sourcing=sourcing, evidence=evidence)


def profit_inputs():
    return ProfitInputs(
        sale_price_rub=Decimal("1800"),
        rub_per_cny=Decimal("12"),
        international_freight_cny_per_kg=Decimal("30"),
        packaging_cny=Decimal("2"),
        last_mile_cny=Decimal("15"),
        customs_rate=Decimal("0.05"),
        platform_fee_rate=Decimal("0.15"),
        advertising_rate=Decimal("0.08"),
        return_reserve_rate=Decimal("0.04"),
    )


def offers():
    result = []
    for index, price in enumerate(("35", "38", "42"), start=1):
        result.append(
            OfferEvidencePayload(
                offer_data={
                    "supplier_ref": f"factory-{index}",
                    "platform": SourcePlatform.ALIBABA_1688,
                    "external_id": f"RU-001-{index}",
                    "source_url": f"https://example.com/offer-{index}",
                    "title": f"Storage box supplier {index}",
                    "currency": "CNY",
                    "unit_price": Decimal(price),
                    "source_to_cny_rate": Decimal("1"),
                    "min_order_quantity": 100,
                    "weight_kg": Decimal("0.5"),
                    "length_cm": Decimal("30"),
                    "width_cm": Decimal("20"),
                    "height_cm": Decimal("10"),
                    "domestic_logistics_per_unit": Decimal("2"),
                    "attributes": {},
                    "media": [],
                },
                content=f"supplier {index} signed quotation".encode(),
                filename=f"supplier-{index}.txt",
                content_type="text/plain",
            )
        )
    return result


def test_three_supplier_comparison_is_evidence_backed_and_idempotent():
    product, store, intake = make_intake()
    values = dict(
        product_id=product.id,
        effective_at="2026-07-16T00:00:00+08:00",
        offers=offers(),
        profit_inputs=profit_inputs(),
        assumption_content=b"approved logistics and fee assumptions",
        assumption_filename="assumptions.txt",
        assumption_content_type="text/plain",
        created_by="operator-1",
    )
    first = intake.ingest(**values)
    second = intake.ingest(**values)

    assert len(store.offers) == 3
    assert len(store.scenarios) == 3
    assert [item.id for item in first["offers"]] == [item.id for item in second["offers"]]
    assert first["comparison"]["supplier_count"] == 3
    assert first["comparison"]["ready_for_procurement_review"] is True
    assert first["comparison"]["rows"][0]["scenario"].cm3_cny > first["comparison"]["rows"][-1]["scenario"].cm3_cny


def test_supplier_comparison_rejects_duplicate_supplier_identity():
    product, _, intake = make_intake()
    payloads = offers()
    payloads[1].offer_data["supplier_ref"] = payloads[0].offer_data["supplier_ref"]
    with pytest.raises(ValueError, match="distinct supplier"):
        intake.ingest(
            product_id=product.id,
            effective_at="2026-07-16T00:00:00+08:00",
            offers=payloads,
            profit_inputs=profit_inputs(),
            assumption_content=b"assumptions",
            assumption_filename="assumptions.txt",
            assumption_content_type="text/plain",
            created_by="operator-1",
        )


def test_identical_procurement_approval_request_is_idempotent():
    product, _, intake = make_intake()
    payload = {"product_id": product.id, "offer_id": "offer-1", "quantity": 100}
    first = intake.sourcing.repository
    commerce = CommerceService(first, evidence_validator=lambda _: None)
    requested = commerce.request_approval(
        action="procurement.place_order",
        resource_type="profit_scenario",
        resource_id="scenario-1",
        requested_by="operator-1",
        payload=payload,
    )
    retry = commerce.request_approval(
        action="procurement.place_order",
        resource_type="profit_scenario",
        resource_id="scenario-1",
        requested_by="operator-1",
        payload=payload,
    )
    assert retry.id == requested.id
    assert len(first.list_approvals()) == 1
