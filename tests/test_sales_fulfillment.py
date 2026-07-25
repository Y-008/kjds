from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.domain import PassportType
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.sales_fulfillment import SalesFulfillmentService
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import (
    REQUIRED_COST_EVIDENCE_KEYS,
    ProfitInputs,
    SourcePlatform,
    SourcingService,
    SupplierOffer,
)
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


PASSPORT_FACTS = {
    PassportType.PRODUCT: {
        "decision": "approved",
        "material": "PA+PE",
        "intended_use": "household storage",
        "country_of_origin": "CN",
        "weight_kg": "0.1",
        "dimensions_cm": {"length": 26, "width": 13, "height": 13},
    },
    PassportType.COMPLIANCE: {
        "decision": "approved",
        "hs_code": "3924.90",
        "eaeu_rules": ["reviewed"],
        "eac_requirement": "not_required_after_review",
        "chestny_znak_requirement": "not_required_after_review",
        "russian_labeling": "required",
        "ip_status": "cleared",
        "transport_restrictions": "none_identified",
        "sellability": "sellable",
    },
    PassportType.QUALITY: {
        "decision": "approved",
        "golden_sample_ref": "sample://VACUUM-001/golden",
        "inspection_plan": ["seal", "dimensions", "leakage"],
        "packaging_test": "passed",
    },
}


def capture(evidence, ref):
    return evidence.capture(
        content=ref.encode(),
        filename=f"{ref}.txt",
        content_type="text/plain",
        source="sales_fulfillment_test",
        source_ref=f"test://{ref}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-25T00:00:00+00:00",
        effective_until=None,
        created_by="tester",
    )


def setup_fulfillment():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    repository = InMemoryRepository()
    commerce = CommerceService(repository, evidence_validator=evidence.require_valid)
    product = commerce.create_product(sku="VACUUM-001", name="Compression storage bag")
    for kind in PassportType:
        proof = capture(evidence, f"passport-{kind.value}")
        commerce.add_passport(
            product_id=product.id,
            kind=kind,
            facts=PASSPORT_FACTS[kind],
            evidence=[proof.id],
            approved_by="reviewer-1",
        )
    commerce.validate_product(product.id)
    order = commerce.create_order(
        external_id="OZON-RU-ORDER-1001",
        product_id=product.id,
        quantity=2,
        currency="RUB",
        gross_revenue=Decimal("3600"),
        booked_fx_rate=Decimal("0.083"),
    )
    store = MemorySourcingStore()
    sourcing = SourcingService(store, repository, evidence_validator=evidence.require_valid)
    assumption = capture(evidence, "profit-assumptions")
    rows = []
    for index, price in enumerate(("2.50", "3.20", "2.19"), start=1):
        quote = capture(evidence, f"supplier-quote-{index}")
        offer = sourcing.capture_offer(
            SupplierOffer(
                product_id=product.id,
                supplier_ref=f"factory-{index}",
                platform=SourcePlatform.ALIBABA_1688,
                external_id=f"1688-offer-{index}",
                source_url=f"https://detail.1688.com/offer/{index}.html",
                title=f"Compression bag supplier {index}",
                currency="CNY",
                unit_price=Decimal(price),
                source_to_cny_rate=Decimal("1"),
                min_order_quantity=5,
                weight_kg=Decimal("0.1"),
                length_cm=Decimal("26"),
                width_cm=Decimal("13"),
                height_cm=Decimal("13"),
                domestic_logistics_per_unit=Decimal("0.5"),
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
            {
                key: assumption.id
                for key in REQUIRED_COST_EVIDENCE_KEYS
                if key not in {"product_cost", "domestic_logistics"}
            },
        )
        rows.append((offer, scenario))
    service = SalesFulfillmentService(
        engine=engine,
        repository=repository,
        sourcing_store=store,
        sourcing=sourcing,
        evidence=evidence,
        commerce=commerce,
    )
    return service, commerce, evidence, order, rows


def select_route(service, evidence, plan_id, *, carrier_code="GOOL", status="active", legacy=False):
    route_evidence = capture(evidence, f"route-{carrier_code}-{status}-{legacy}")
    plan = service.select_route(
        plan_id,
        effective_at="2026-07-25T01:00:00+00:00",
        evidence_id=route_evidence.id,
        facts={
            "aggregator": "kuajing84",
            "carrier_code": carrier_code,
            "service_code": f"OZON-{carrier_code}",
            "warehouse_id": "WH-SZ-001",
            "warehouse_name": "深圳跨境集运仓",
            "warehouse_address": "广东省深圳市测试路 1 号 A 仓",
            "address_valid_at": "2026-07-25T01:00:00+00:00",
            "delivery_method_status": status,
            "legacy_connection": legacy,
        },
        created_by="operator-1",
    )
    return plan


def test_listing_does_not_create_procurement_and_sales_order_plan_has_no_address():
    service, _, _, order, _ = setup_fulfillment()
    plan = service.create_plan(order.id, created_by="operator-1")
    retry = service.create_plan(order.id, created_by="operator-1")

    assert retry["id"] == plan["id"]
    assert plan["external_sales_order_id"] == "OZON-RU-ORDER-1001"
    assert plan["status"] == "awaiting_route"
    assert plan["route"] is None
    assert plan["domestic_warehouse_address_known"] is False
    assert plan["automatic_supplier_order"] is False
    assert plan["automatic_payment"] is False


def test_order_route_approval_and_supplier_order_are_bound_to_exact_warehouse():
    service, commerce, evidence, order, rows = setup_fulfillment()
    plan = service.create_plan(order.id, created_by="operator-1")
    plan = select_route(service, evidence, plan["id"])
    offer, scenario = rows[0]

    assert plan["route"]["carrier_code"] == "GUOO"
    assert plan["domestic_warehouse_address_known"] is True

    plan = service.request_procurement_approval(
        plan["id"],
        offer_id=offer.id,
        scenario_id=scenario.id,
        quantity=5,
        rationale="供应商 MOQ 超过本次销售数量，余量进入受控库存。",
        requested_by="operator-1",
    )
    approval_id = plan["procurement_approval"]["approval_id"]
    commerce.decide_approval(
        approval_id,
        approved=True,
        decided_by="approver-2",
        reason="订单、利润和仓址已复核",
    )
    proof = capture(evidence, "supplier-order-confirmation")
    plan = service.record_event(
        plan["id"],
        event_type="supplier_order_confirmed",
        effective_at="2026-07-25T02:00:00+00:00",
        evidence_id=proof.id,
        facts={
            "supplier_order_ref": "1688-PO-9001",
            "ship_to_warehouse_id": "WH-SZ-001",
            "ship_to_name": "深圳跨境集运仓",
            "ship_to_address": "广东省深圳市测试路 1 号 A 仓",
            "promised_dispatch_at": "2026-07-26T02:00:00+00:00",
        },
        created_by="operator-1",
    )

    assert plan["status"] == "supplier_order_confirmed"
    assert plan["ready_for_supplier_order"] is True


def test_supplier_order_rejects_address_mismatch_and_uni_new_connection():
    service, commerce, evidence, order, rows = setup_fulfillment()
    plan = service.create_plan(order.id, created_by="operator-1")
    with pytest.raises(ValueError, match="already-connected legacy"):
        select_route(service, evidence, plan["id"], carrier_code="UNI")

    plan = select_route(
        service,
        evidence,
        plan["id"],
        carrier_code="UNI",
        status="legacy_only",
        legacy=True,
    )
    offer, scenario = rows[0]
    plan = service.request_procurement_approval(
        plan["id"],
        offer_id=offer.id,
        scenario_id=scenario.id,
        quantity=5,
        rationale="供应商 MOQ 余量进入受控库存。",
        requested_by="operator-1",
    )
    commerce.decide_approval(
        plan["procurement_approval"]["approval_id"],
        approved=True,
        decided_by="approver-2",
        reason="批准",
    )
    proof = capture(evidence, "wrong-warehouse")
    with pytest.raises(ValueError, match="must equal the selected logistics warehouse"):
        service.record_event(
            plan["id"],
            event_type="supplier_order_confirmed",
            effective_at="2026-07-25T02:00:00+00:00",
            evidence_id=proof.id,
            facts={
                "supplier_order_ref": "1688-PO-9002",
                "ship_to_warehouse_id": "WH-OTHER",
                "ship_to_name": "其他仓",
                "ship_to_address": "错误地址",
                "promised_dispatch_at": "2026-07-26T02:00:00+00:00",
            },
            created_by="operator-1",
        )


def test_route_can_be_refreshed_before_procurement_approval():
    service, _, evidence, order, _ = setup_fulfillment()
    plan = service.create_plan(order.id, created_by="operator-1")
    plan = select_route(service, evidence, plan["id"], carrier_code="GUOO")
    refreshed_evidence = capture(evidence, "route-cel-refreshed")
    plan = service.select_route(
        plan["id"],
        effective_at="2026-07-25T01:30:00+00:00",
        evidence_id=refreshed_evidence.id,
        facts={
            "aggregator": "kuajing84",
            "carrier_code": "CEL",
            "service_code": "OZON-CEL-FAST",
            "warehouse_id": "WH-YW-002",
            "warehouse_name": "义乌跨境集运仓",
            "warehouse_address": "浙江省义乌市测试路 2 号 B 仓",
            "address_valid_at": "2026-07-25T01:30:00+00:00",
            "delivery_method_status": "active",
            "legacy_connection": False,
        },
        created_by="operator-1",
    )

    assert plan["route"]["carrier_code"] == "CEL"
    assert plan["route"]["warehouse_id"] == "WH-YW-002"
    assert len([item for item in plan["events"] if item["event_type"] == "route_selected"]) == 2
