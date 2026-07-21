from dataclasses import asdict
from decimal import Decimal
from unittest import TestCase

from apps.control_plane.domain import ContentAsset, ContentStatus, ContentType, PassportType
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import (
    REQUIRED_COST_EVIDENCE_KEYS,
    ListingDraft,
    ProfitInputs,
    ProfitScenario,
    SourcePlatform,
    SourcingService,
    SupplierOffer,
    listing_approval_payload,
    listing_snapshot_sha256,
    profit_template_contract,
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

FULL_COST_EVIDENCE = {
    key: "evidence://assumptions/ru/2026-07-13"
    for key in REQUIRED_COST_EVIDENCE_KEYS
    if key not in {"product_cost", "domestic_logistics"}
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

    def list_scenarios(self, limit=1000):
        return list(self.scenarios.values())[:limit]

    def save_listing_draft(self, draft):
        self.drafts[draft.id] = draft
        return draft

    def attach_listing_approval(self, draft):
        self.drafts[draft.id] = draft
        return draft

    def get_listing_draft(self, draft_id):
        return self.drafts[draft_id]

    def list_listing_drafts(self, limit=100):
        return list(self.drafts.values())[:limit]


class SourcingFlowTest(TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.commerce = CommerceService(self.repo, evidence_validator=lambda _: None)
        self.store = MemorySourcingStore()
        self.sourcing = SourcingService(self.store, self.repo, evidence_validator=lambda _: None)
        self.product = self.commerce.create_product(sku="RU-001", name="Storage box")
        self.offer = self.sourcing.capture_offer(
            SupplierOffer(
                product_id=self.product.id,
                supplier_ref="1688-shop-100",
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
                captured_at="2026-07-13T00:00:00+00:00",
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
            ["evidence://assumptions/ru/2026-07-13"],
            FULL_COST_EVIDENCE,
        )

    def approved_image_asset(
        self,
        *,
        product_id: str | None = None,
        artifact_ref: str = "evidence://image/main",
    ) -> ContentAsset:
        return self.repo.add_content_asset(
            ContentAsset(
                product_id=product_id or self.product.id,
                content_type=ContentType.IMAGE,
                locale="ru-RU",
                channel="OZON",
                brief={"goal": "main image"},
                source_facts={},
                status=ContentStatus.APPROVED,
                artifact_ref=artifact_ref,
            )
        )

    def test_profit_scenario_includes_logistics_and_break_even(self):
        result = self.scenario()
        self.assertEqual(result.revenue_cny, Decimal("150.00"))
        self.assertEqual(result.international_logistics_cny, Decimal("15.00"))
        self.assertEqual(result.cm3_cny, Decimal("23.30"))
        self.assertEqual(result.break_even_price_rub, Decimal("1427.20"))
        self.assertTrue(result.cost_complete)
        self.assertEqual(
            result.evidence,
            ["capture://1688/100/2026-07-13", "evidence://assumptions/ru/2026-07-13"],
        )

    def test_comparison_does_not_reuse_profit_from_superseded_supplier_offer(self):
        self.scenario()
        replacement = self.sourcing.capture_offer(
            SupplierOffer(
                product_id=self.product.id,
                supplier_ref=self.offer.supplier_ref,
                platform=SourcePlatform.ALIBABA_1688,
                external_id="1688-100-requoted",
                source_url="https://detail.1688.com/offer/100.html",
                title="Storage box updated quote",
                currency="CNY",
                unit_price=Decimal("55"),
                source_to_cny_rate=Decimal("1"),
                min_order_quantity=10,
                weight_kg=Decimal("0.5"),
                length_cm=Decimal("30"),
                width_cm=Decimal("20"),
                height_cm=Decimal("10"),
                domestic_logistics_per_unit=Decimal("5"),
                evidence_ref="capture://1688/100/2026-07-21",
                captured_at="2026-07-21T00:00:00+00:00",
            )
        )

        comparison = self.sourcing.compare_product_offers(self.product.id)

        self.assertEqual(comparison["offer_count"], 1)
        self.assertEqual(comparison["rows"][0]["offer"].id, replacement.id)
        self.assertIsNone(comparison["rows"][0]["scenario"])
        self.assertFalse(comparison["ready_for_procurement_review"])

    def test_versioned_cost_states_explain_sources_and_block_unknowns(self):
        template = profit_template_contract()
        self.assertEqual(template["id"], "ozon-ru-full-cost-v1")
        self.assertEqual(len(template["fields"]), 15)
        self.assertFalse(template["automatic_pricing"])

        evidence = {key: value for key, value in FULL_COST_EVIDENCE.items() if key != "tax"}
        states = {key: "estimate" for key in REQUIRED_COST_EVIDENCE_KEYS}
        states["tax"] = "unknown"
        result = self.sourcing.calculate_profit(
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
            ["evidence://assumptions/ru/2026-07-13"],
            evidence,
            states,
        )
        explanation = result.explain()
        tax = next(item for item in explanation["items"] if item["key"] == "tax")
        self.assertEqual(tax["state"], "unknown")
        self.assertIsNone(tax["evidence_id"])
        self.assertEqual(explanation["unknown_costs"], ["tax"])
        self.assertFalse(explanation["release_ready"])
        self.assertEqual(explanation["sensitivity"]["baseline"]["cm3_cny"], str(result.cm3_cny))
        self.assertFalse(explanation["automatic_pricing"])

    def test_actual_cost_requires_authority_and_is_revalidated_before_release(self):
        states = {key: "estimate" for key in REQUIRED_COST_EVIDENCE_KEYS}
        states["product_cost"] = "actual"
        inputs = ProfitInputs(
            sale_price_rub=Decimal("1800"),
            rub_per_cny=Decimal("12"),
            international_freight_cny_per_kg=Decimal("30"),
            packaging_cny=Decimal("2"),
            last_mile_cny=Decimal("10"),
            customs_rate=Decimal("0.10"),
            platform_fee_rate=Decimal("0.10"),
            advertising_rate=Decimal("0.05"),
            return_reserve_rate=Decimal("0.10"),
        )
        with self.assertRaisesRegex(ValueError, "authority validator"):
            self.sourcing.calculate_profit(
                self.offer.id,
                inputs,
                ["evidence://assumptions/ru/2026-07-13"],
                FULL_COST_EVIDENCE,
                states,
            )

        validation_enabled = True

        def validate_actual(evidence_id, cost_type):
            self.assertEqual(evidence_id, self.offer.evidence_ref)
            self.assertEqual(cost_type, "product_cost")
            if not validation_enabled:
                raise ValueError("authority withdrawn")

        sourcing = SourcingService(
            self.store,
            self.repo,
            evidence_validator=lambda _: None,
            actual_cost_validator=validate_actual,
        )
        scenario = sourcing.calculate_profit(
            self.offer.id,
            inputs,
            ["evidence://assumptions/ru/2026-07-13"],
            FULL_COST_EVIDENCE,
            states,
        )
        self.assertTrue(sourcing.release_ready(scenario))
        validation_enabled = False
        self.assertFalse(sourcing.release_ready(scenario))
        with self.assertRaisesRegex(ValueError, "withdrawn"):
            sourcing.require_release_ready(scenario)

    def test_named_full_costs_reduce_cm3_and_other_cost_blocks_release(self):
        inputs = ProfitInputs(
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
        )
        result = self.sourcing.calculate_profit(
            self.offer.id,
            inputs,
            ["evidence://assumptions/ru/2026-07-13"],
            FULL_COST_EVIDENCE,
        )
        self.assertEqual(result.cm3_cny, Decimal("16.30"))
        self.assertEqual(result.cost_breakdown()["tax"], "2.00")
        self.assertTrue(result.cost_complete)

        unclassified = self.sourcing.calculate_profit(
            self.offer.id,
            ProfitInputs(**{**asdict(inputs), "other_cost_cny": Decimal("0.01")}),
            ["evidence://assumptions/ru/2026-07-13"],
            FULL_COST_EVIDENCE,
        )
        self.assertFalse(unclassified.cost_complete)

    def test_offer_rejects_invalid_amounts_and_normalizes_time_and_currency(self):
        values = {
            "product_id": self.product.id,
            "supplier_ref": "factory-2",
            "platform": SourcePlatform.ALIBABA_1688,
            "external_id": "offer-2",
            "source_url": "https://example.com/offer-2",
            "title": "Offer 2",
            "currency": "cny",
            "unit_price": Decimal("10"),
            "source_to_cny_rate": Decimal("1"),
            "min_order_quantity": 1,
            "weight_kg": Decimal("1"),
            "length_cm": Decimal("0"),
            "width_cm": Decimal("0"),
            "height_cm": Decimal("0"),
            "domestic_logistics_per_unit": Decimal("0"),
            "evidence_ref": "evidence://offer-2",
            "captured_at": "2026-07-17T08:00:00+08:00",
        }
        offer = SupplierOffer(**values)
        self.assertEqual(offer.currency, "CNY")
        self.assertEqual(offer.captured_at, "2026-07-17T00:00:00+00:00")

        with self.assertRaisesRegex(ValueError, "timezone"):
            SupplierOffer(**{**values, "captured_at": "2026-07-17T08:00:00"})
        with self.assertRaisesRegex(ValueError, "finite"):
            SupplierOffer(**{**values, "unit_price": Decimal("NaN")})
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            SupplierOffer(**{**values, "domestic_logistics_per_unit": Decimal("-0.01")})

    def test_profit_inputs_reject_invalid_money_and_combined_rates(self):
        values = {
            "sale_price_rub": Decimal("1800"),
            "rub_per_cny": Decimal("12"),
            "international_freight_cny_per_kg": Decimal("30"),
            "packaging_cny": Decimal("2"),
            "last_mile_cny": Decimal("10"),
            "customs_rate": Decimal("0.10"),
            "platform_fee_rate": Decimal("0.10"),
            "advertising_rate": Decimal("0.05"),
            "return_reserve_rate": Decimal("0.10"),
        }
        with self.assertRaisesRegex(ValueError, "finite"):
            ProfitInputs(**{**values, "rub_per_cny": Decimal("Infinity")})
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            ProfitInputs(**{**values, "packaging_cny": Decimal("-0.01")})
        with self.assertRaisesRegex(ValueError, "Combined"):
            ProfitInputs(
                **{
                    **values,
                    "platform_fee_rate": Decimal("0.60"),
                    "advertising_rate": Decimal("0.25"),
                    "return_reserve_rate": Decimal("0.15"),
                }
            )

    def test_offer_and_scenario_require_valid_evidence(self):
        rejected = SourcingService(
            self.store,
            self.repo,
            evidence_validator=lambda _: (_ for _ in ()).throw(ValueError("invalid evidence")),
        )
        with self.assertRaisesRegex(ValueError, "invalid evidence"):
            rejected.calculate_profit(
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
                ["invalid"],
            )

        with self.assertRaisesRegex(ValueError, "Profit assumptions require"):
            self.sourcing.calculate_profit(
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
                [],
            )

    def test_listing_draft_requires_approved_product_passports(self):
        product = self.product
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
                content_asset_ids=["asset-not-reached"],
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
        approved_asset = self.approved_image_asset()
        payload["images"] = [approved_asset.artifact_ref]
        draft = self.sourcing.create_ozon_listing_draft(
            product_id=product.id,
            offer_id=self.offer.id,
            scenario_id=result.id,
            content_asset_ids=[approved_asset.id],
            listing_data=payload,
            requested_by="owner",
        )
        self.assertEqual(draft.status, "approval_pending")
        self.assertEqual(draft.listing_data["content_asset_ids"], [approved_asset.id])

        repeated = self.sourcing.create_ozon_listing_draft(
            product_id=product.id,
            offer_id=self.offer.id,
            scenario_id=result.id,
            content_asset_ids=[approved_asset.id],
            listing_data=payload,
            requested_by="owner",
        )
        self.assertEqual(repeated.id, draft.id)
        self.assertEqual(len(self.store.list_listing_drafts()), 1)

        result.cost_evidence = {}
        with self.assertRaisesRegex(ValueError, "full cost evidence"):
            self.sourcing.create_ozon_listing_draft(
                product_id=product.id,
                offer_id=self.offer.id,
                scenario_id=result.id,
                content_asset_ids=[approved_asset.id],
                listing_data=payload,
                requested_by="owner",
            )

    def test_listing_draft_rejects_offer_from_another_product(self):
        other = self.commerce.create_product(sku="RU-002", name="Other product")
        result = self.scenario()
        for kind in PassportType:
            self.commerce.add_passport(
                product_id=other.id,
                kind=kind,
                facts=PASSPORT_FACTS[kind],
                evidence=[f"evidence://{kind.value}/other"],
                approved_by="owner",
            )
        self.commerce.validate_product(other.id)
        with self.assertRaisesRegex(ValueError, "does not belong"):
            self.sourcing.create_ozon_listing_draft(
                product_id=other.id,
                offer_id=self.offer.id,
                scenario_id=result.id,
                content_asset_ids=["asset-not-reached"],
                listing_data={
                    "title": "Other",
                    "description": "Other",
                    "category_id": "123",
                    "attributes": {},
                    "images": ["asset://other.jpg"],
                },
                requested_by="owner",
            )

    def test_listing_draft_rejects_unapproved_or_mismatched_image_evidence(self):
        result = self.scenario()
        for kind in PassportType:
            self.commerce.add_passport(
                product_id=self.product.id,
                kind=kind,
                facts=PASSPORT_FACTS[kind],
                evidence=[f"evidence://{kind.value}"],
                approved_by="owner",
            )
        self.commerce.validate_product(self.product.id)
        asset = self.approved_image_asset()
        asset.status = ContentStatus.GENERATED
        payload = {
            "title": "Контейнер для хранения",
            "description": "Verified facts only",
            "category_id": "123",
            "attributes": {"color": "white"},
            "images": [asset.artifact_ref],
        }
        with self.assertRaisesRegex(ValueError, "must be approved images"):
            self.sourcing.create_ozon_listing_draft(
                product_id=self.product.id,
                offer_id=self.offer.id,
                scenario_id=result.id,
                content_asset_ids=[asset.id],
                listing_data=payload,
                requested_by="owner",
            )

        asset.status = ContentStatus.APPROVED
        payload["images"] = ["evidence://image/not-approved"]
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.sourcing.create_ozon_listing_draft(
                product_id=self.product.id,
                offer_id=self.offer.id,
                scenario_id=result.id,
                content_asset_ids=[asset.id],
                listing_data=payload,
                requested_by="owner",
            )

    def test_listing_approval_binds_readable_context_to_deterministic_snapshot(self):
        scenario = self.scenario()
        listing_data = {
            "title": "Контейнер для хранения",
            "description": "Verified facts only",
            "category_id": "123",
            "attributes": {"color": "white", "count": 1},
            "images": ["evidence://image/approved"],
            "content_asset_ids": ["cnt-approved"],
        }
        draft = ListingDraft(
            product_id=self.product.id,
            offer_id=self.offer.id,
            scenario_id=scenario.id,
            target_platform="OZON",
            listing_data=listing_data,
            requested_by="operator-a",
        )
        reordered = ListingDraft(
            product_id=self.product.id,
            offer_id=self.offer.id,
            scenario_id=scenario.id,
            target_platform="OZON",
            listing_data={
                "content_asset_ids": ["cnt-approved"],
                "images": ["evidence://image/approved"],
                "attributes": {"count": 1, "color": "white"},
                "category_id": "123",
                "description": "Verified facts only",
                "title": "Контейнер для хранения",
            },
            requested_by="another-operator",
        )

        digest = listing_snapshot_sha256(draft)
        self.assertEqual(digest, listing_snapshot_sha256(reordered))
        self.assertEqual(len(digest), 64)

        payload = listing_approval_payload(draft, scenario)
        self.assertEqual(payload["draft_id"], draft.id)
        self.assertEqual(payload["listing_snapshot_sha256"], digest)
        self.assertEqual(payload["title"], listing_data["title"])
        self.assertEqual(payload["content_asset_ids"], ["cnt-approved"])
        self.assertEqual(payload["image_evidence_refs"], ["evidence://image/approved"])
        self.assertEqual(payload["expected_cm3_cny"], str(scenario.cm3_cny))
        self.assertFalse(payload["platform_write_executed"])

        draft.approval_id = "apr-independent-review"
        self.store.save_listing_draft(draft)
        verified = self.sourcing.verify_listing_approval(
            draft_id=draft.id,
            approval_id=draft.approval_id,
            approval_payload=payload,
        )
        self.assertEqual(verified.id, draft.id)
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.sourcing.verify_listing_approval(
                draft_id=draft.id,
                approval_id="apr-other",
                approval_payload=payload,
            )

        draft.listing_data["description"] = "Changed description"
        self.assertNotEqual(listing_snapshot_sha256(draft), digest)
        with self.assertRaisesRegex(ValueError, "changed"):
            self.sourcing.verify_listing_approval(
                draft_id=draft.id,
                approval_id=draft.approval_id,
                approval_payload=payload,
            )
