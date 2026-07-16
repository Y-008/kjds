from decimal import Decimal
from unittest import TestCase

from apps.control_plane.domain import PassportType
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import (
    ListingDraft,
    ProfitInputs,
    ProfitScenario,
    SourcePlatform,
    SourcingService,
    SupplierOffer,
)

PASSPORT_FACTS = {
    PassportType.PRODUCT: {
        "decision": "approved",
        "material": "polypropylene",
        "intended_use": "household storage",
        "country_of_origin": "CN",
        "weight_kg": "0.5",
        "dimensions_cm": {"length": 30, "width": 20, "height": 10},
    },
    PassportType.COMPLIANCE: {
        "decision": "approved",
        "hs_code": "3924.90",
        "eaeu_rules": ["reviewed: not in regulated scope"],
        "eac_requirement": "not_required_after_review",
        "chestny_znak_requirement": "not_required_after_review",
        "russian_labeling": "required",
        "ip_status": "cleared",
        "transport_restrictions": "none_identified",
        "sellability": "sellable",
    },
    PassportType.QUALITY: {
        "decision": "approved",
        "golden_sample_ref": "sample://RU-001/golden",
        "inspection_plan": ["dimensions", "material", "appearance"],
        "packaging_test": "passed",
    },
}


class MemorySourcingStore:
    def __init__(self):
        self.offers: dict[str, SupplierOffer] = {}
        self.scenarios: dict[str, ProfitScenario] = {}
        self.drafts: dict[str, ListingDraft] = {}

    def save_offer(self, offer):
        self.offers[offer.id] = offer
        return offer

    def get_offer(self, offer_id):
        try:
            return self.offers[offer_id]
        except KeyError as exc:
            raise KeyError(f"Unknown supplier offer: {offer_id}") from exc

    def list_offers(self, limit=100):
        return list(self.offers.values())[:limit]

    def save_scenario(self, scenario):
        self.scenarios[scenario.id] = scenario
        return scenario

    def get_scenario(self, scenario_id):
        return self.scenarios[scenario_id]

    def save_listing_draft(self, draft):
        self.drafts[draft.id] = draft
        return draft

    def attach_listing_approval(self, draft):
        self.drafts[draft.id] = draft
        return draft

    def list_listing_drafts(self, limit=100):
        return list(self.drafts.values())[:limit]


class SourcingFlowTest(TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.commerce = CommerceService(self.repo)
        self.store = MemorySourcingStore()
        self.sourcing = SourcingService(self.store, self.repo)
        self.offer = self.sourcing.capture_offer(
            SupplierOffer(
                platform=SourcePlatform.ALIBABA_1688,
                external_id="1688-100",
                source_url="https://detail.1688.com/offer/100.html",
                title="Storage box",
                currency="CNY",
                unit_price=Decimal("50"),
                source_to_cny_rate=Decimal("1"),
                min_order_quantity=10,
                weight_kg=Decimal("0.5"),
                length_cm=Decimal("30"),
                width_cm=Decimal("20"),
                height_cm=Decimal("10"),
                domestic_logistics_per_unit=Decimal("5"),
                evidence_ref="capture://1688/100/2026-07-13",
            )
        )

    def scenario(self):
        return self.sourcing.calculate_profit(
            self.offer.id,
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
            ),
        )

    def test_profit_scenario_includes_logistics_and_break_even(self):
        result = self.scenario()
        self.assertEqual(result.revenue_cny, Decimal("150.00"))
        self.assertEqual(result.international_logistics_cny, Decimal("15.00"))
        self.assertEqual(result.cm3_cny, Decimal("23.30"))
        self.assertEqual(result.break_even_price_rub, Decimal("1427.20"))

    def test_listing_draft_requires_approved_product_passports(self):
        product = self.commerce.create_product(sku="RU-001", name="Storage box")
        result = self.scenario()
        payload = {
            "title": "Контейнер для хранения",
            "description": "Verified facts only",
            "category_id": "123",
            "attributes": {"color": "white"},
            "images": ["asset://main.jpg"],
        }
        with self.assertRaisesRegex(ValueError, "approved passports"):
            self.sourcing.create_ozon_listing_draft(
                product_id=product.id,
                offer_id=self.offer.id,
                scenario_id=result.id,
                listing_data=payload,
                requested_by="owner",
            )

        for kind in PassportType:
            self.commerce.add_passport(
                product_id=product.id,
                kind=kind,
                facts=PASSPORT_FACTS[kind],
                evidence=[f"evidence://{kind.value}"],
                approved_by="owner",
            )
        self.commerce.validate_product(product.id)
        draft = self.sourcing.create_ozon_listing_draft(
            product_id=product.id,
            offer_id=self.offer.id,
            scenario_id=result.id,
            listing_data=payload,
            requested_by="owner",
        )
        self.assertEqual(draft.status, "approval_pending")
