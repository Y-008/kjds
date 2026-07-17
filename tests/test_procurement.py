from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.procurement import ProcurementService
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import ProfitInputs, SourcePlatform, SourcingService, SupplierOffer
from apps.control_plane.sql_repository import Base


class MemorySourcingStore:
    def __init__(self):
        self.offers = {}
        self.scenarios = {}

    def save_offer(self, offer):
        self.offers[offer.id] = offer
        return offer

    def get_offer(self, offer_id):
        return self.offers[offer_id]

    def list_offers(self, limit=100):
        return list(reversed(list(self.offers.values())))[:limit]

    def save_scenario(self, scenario):
        self.scenarios[scenario.id] = scenario
        return scenario

    def get_scenario(self, scenario_id):
        return self.scenarios[scenario_id]

    def list_scenarios(self, limit=1000):
        return list(reversed(list(self.scenarios.values())))[:limit]


def capture(evidence, *, ref, content, effective_at="2026-07-16T00:00:00+00:00"):
    return evidence.capture(
        content=content.encode(),
        filename=f"{ref}.txt",
        content_type="text/plain",
        source="procurement_test",
        source_ref=f"test://{ref}",
        grade=EvidenceGrade.A,
        effective_at=effective_at,
        effective_until=None,
        created_by="tester",
    )


def setup_procurement():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    repository = InMemoryRepository()
    commerce = CommerceService(repository, evidence_validator=evidence.require_valid)
    product = commerce.create_product(sku="RU-001", name="Storage box")
    store = MemorySourcingStore()
    sourcing = SourcingService(store, repository, evidence_validator=evidence.require_valid)
    assumption = capture(evidence, ref="assumptions", content="profit assumptions")
    scenarios = []
    for index, price in enumerate(("30", "34", "38"), start=1):
        quote = capture(evidence, ref=f"quote-{index}", content=f"supplier quote {index}")
        offer = sourcing.capture_offer(
            SupplierOffer(
                product_id=product.id,
                supplier_ref=f"factory-{index}",
                platform=SourcePlatform.ALIBABA_1688,
                external_id=f"offer-{index}",
                source_url=f"https://example.com/{index}",
                title=f"Supplier {index}",
                currency="CNY",
                unit_price=Decimal(price),
                source_to_cny_rate=Decimal("1"),
                min_order_quantity=100,
                weight_kg=Decimal("0.5"),
                length_cm=Decimal("30"),
                width_cm=Decimal("20"),
                height_cm=Decimal("10"),
                domestic_logistics_per_unit=Decimal("2"),
                evidence_ref=quote.id,
            )
        )
        scenario = sourcing.calculate_profit(
            offer.id,
            ProfitInputs(
                sale_price_rub=Decimal("1800"),
                rub_per_cny=Decimal("12"),
                international_freight_cny_per_kg=Decimal("30"),
                packaging_cny=Decimal("2"),
                last_mile_cny=Decimal("15"),
                customs_rate=Decimal("0.05"),
                platform_fee_rate=Decimal("0.15"),
                advertising_rate=Decimal("0.08"),
                return_reserve_rate=Decimal("0.04"),
            ),
            [assumption.id],
        )
        scenarios.append((offer, scenario))
    selected_offer, selected_scenario = scenarios[0]
    approval = commerce.request_approval(
        action="procurement.place_order",
        resource_type="profit_scenario",
        resource_id=selected_scenario.id,
        requested_by="operator-1",
        payload={
            "product_id": product.id,
            "offer_id": selected_offer.id,
            "scenario_id": selected_scenario.id,
            "quantity": 100,
        },
    )
    commerce.decide_approval(approval.id, approved=True, decided_by="approver-2", reason="approved")
    service = ProcurementService(
        engine=engine,
        repository=repository,
        sourcing_store=store,
        sourcing=sourcing,
        evidence=evidence,
    )
    return evidence, service, approval


def record(service, evidence, order_id, event_type, facts, sequence, effective_at):
    source = capture(
        evidence,
        ref=f"event-{sequence}-{event_type}",
        content=f"event evidence {sequence}",
        effective_at=effective_at,
    )
    return service.record_event(
        order_id,
        event_type=event_type,
        effective_at=effective_at,
        evidence_id=source.id,
        facts=facts,
        created_by="operator-1",
    ), source


def test_sample_procurement_timeline_performance_and_backup_options():
    evidence, service, approval = setup_procurement()
    order = service.create_sample_order(approval.id, created_by="operator-1")
    retry = service.create_sample_order(approval.id, created_by="operator-1")
    assert retry["id"] == order["id"]
    assert order["status"] == "approved_to_order"

    order, first_evidence = record(
        service,
        evidence,
        order["id"],
        "order_confirmed",
        {"supplier_order_ref": "PO-1001", "promised_delivery_at": "2026-07-20T00:00:00+00:00"},
        1,
        "2026-07-16T01:00:00+00:00",
    )
    retry = service.record_event(
        order["id"],
        event_type="order_confirmed",
        effective_at="2026-07-16T01:00:00+00:00",
        evidence_id=first_evidence.id,
        facts={"supplier_order_ref": "PO-1001", "promised_delivery_at": "2026-07-20T00:00:00+00:00"},
        created_by="operator-1",
    )
    assert len(retry["events"]) == 1
    order, _ = record(service, evidence, order["id"], "shipped", {"tracking_ref": "TRK-1", "carrier": "carrier"}, 2, "2026-07-17T00:00:00+00:00")
    order, _ = record(service, evidence, order["id"], "received", {"received_quantity": 100, "damaged_quantity": 0}, 3, "2026-07-19T00:00:00+00:00")
    order, _ = record(service, evidence, order["id"], "inspection_completed", {"inspected_quantity": 10, "passed_quantity": 10, "defect_count": 0, "result": "passed"}, 4, "2026-07-19T01:00:00+00:00")
    order, _ = record(service, evidence, order["id"], "golden_sample_approved", {"golden_sample_ref": "GOLD-RU-001"}, 5, "2026-07-19T02:00:00+00:00")

    assert order["status"] == "golden_sample_approved"
    performance = service.supplier_performance()[0]
    assert performance["score"] == "100.0"
    assert performance["quality_yield"] == "1.0000"
    backup = service.backup_options(order["id"])
    assert backup["automatic_switch"] is False
    assert len(backup["options"]) == 2


def test_sample_procurement_rejects_invalid_transition():
    evidence, service, approval = setup_procurement()
    order = service.create_sample_order(approval.id, created_by="operator-1")
    shipment = capture(evidence, ref="early-shipment", content="too early")
    with pytest.raises(ValueError, match="while sample order is approved_to_order"):
        service.record_event(
            order["id"],
            event_type="shipped",
            effective_at="2026-07-16T00:00:00+00:00",
            evidence_id=shipment.id,
            facts={"tracking_ref": "TRK", "carrier": "carrier"},
            created_by="operator-1",
        )
