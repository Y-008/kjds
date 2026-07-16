from decimal import Decimal
from unittest import TestCase

from apps.control_plane.content_growth import REQUIRED_QA, ContentGrowthService
from apps.control_plane.domain import AgentMode, ChargeType, ContentStatus, ContentType, PassportType, ProductStatus
from apps.control_plane.intelligence import MarketIntelligenceService
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.services import CommerceService

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
        "golden_sample_ref": "sample://TEST-001/golden",
        "inspection_plan": ["dimensions", "material", "appearance"],
        "packaging_test": "passed",
    },
}


class CoreFlowTest(TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.commerce = CommerceService(self.repo, evidence_validator=lambda _: None)
        self.market = MarketIntelligenceService(self.repo)
        self.content = ContentGrowthService(self.repo)
        self.product = self.commerce.create_product(sku="TEST-001", name="Test Product")

    def approve_passports(self):
        for kind in PassportType:
            self.commerce.add_passport(
                product_id=self.product.id,
                kind=kind,
                facts=PASSPORT_FACTS[kind],
                evidence=[f"evidence://{kind.value}"],
                approved_by="owner@example.com",
            )

    def test_product_cannot_validate_without_all_passports(self):
        with self.assertRaisesRegex(ValueError, "Approved passports required"):
            self.commerce.validate_product(self.product.id)

    def test_approved_passport_requires_complete_gate_facts(self):
        with self.assertRaisesRegex(ValueError, "missing required facts"):
            self.commerce.add_passport(
                product_id=self.product.id,
                kind=PassportType.COMPLIANCE,
                facts={"decision": "approved", "hs_code": "3924.90"},
                evidence=["review://compliance/1"],
                approved_by="compliance-owner",
            )

        readiness = self.commerce.product_readiness(self.product.id)
        self.assertFalse(readiness["ready_for_validation"])
        self.assertEqual({item["status"] for item in readiness["passports"]}, {"missing"})

    def test_reviewed_passport_fails_closed_when_evidence_gate_rejects_reference(self):
        def reject(_):
            raise ValueError("evidence is not registered")

        self.commerce.evidence_validator = reject
        with self.assertRaisesRegex(ValueError, "not registered"):
            self.commerce.add_passport(
                product_id=self.product.id,
                kind=PassportType.PRODUCT,
                facts=PASSPORT_FACTS[PassportType.PRODUCT],
                evidence=["evidence://untrusted"],
                approved_by="product-owner",
            )

    def test_rejected_compliance_passport_blocks_validation(self):
        self.commerce.add_passport(
            product_id=self.product.id,
            kind=PassportType.COMPLIANCE,
            facts={"decision": "rejected", "sellability": "blocked"},
            evidence=["review://compliance/rejection"],
            approved_by="compliance-owner",
        )
        readiness = self.commerce.product_readiness(self.product.id)
        compliance = next(item for item in readiness["passports"] if item["kind"] == "compliance")
        self.assertEqual(compliance["status"], "blocked")

    def test_market_observations_produce_traceable_score(self):
        row = self.market.ingest(
            source="ozon-export",
            market="RU",
            category="storage",
            metric="demand",
            value=Decimal("80"),
            observed_at="2026-07-11T00:00:00Z",
            source_ref="file://ozon.csv#row=2",
            confidence=Decimal("0.9"),
        )
        insight = self.market.score_opportunity(
            market="RU", category="storage", weights={"demand": Decimal("1")}, recommended_action="sample"
        )
        self.assertEqual(insight.score, Decimal("80"))
        self.assertIn(row.id, insight.evidence_ids)

    def test_content_requires_grounded_passports_and_full_qa(self):
        self.approve_passports()
        self.commerce.validate_product(self.product.id)
        asset = self.content.create_content_brief(
            product_id=self.product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="OZON",
            brief={"goal": "main image"},
        )
        self.content.attach_generated_asset(asset.id, artifact_ref="s3://assets/main.png")
        checks = [{"check": name, "passed": True} for name in REQUIRED_QA]
        reviewed = self.content.review_asset(asset.id, checks=checks)
        self.assertEqual(reviewed.status, ContentStatus.APPROVED)

    def test_order_cm3_and_dual_control(self):
        self.approve_passports()
        product = self.commerce.validate_product(self.product.id)
        self.assertEqual(product.status, ProductStatus.VALIDATED)
        order = self.commerce.create_order(
            external_id="OZON-1001",
            product_id=product.id,
            quantity=1,
            currency="CNY",
            gross_revenue=Decimal("1000"),
            booked_fx_rate=Decimal("1"),
        )
        for kind, amount in [
            (ChargeType.PRODUCT_COST, "300"),
            (ChargeType.PLATFORM_FEE, "100"),
            (ChargeType.INTERNATIONAL_LOGISTICS, "150"),
            (ChargeType.ADVERTISING, "80"),
            (ChargeType.RETURN, "20"),
        ]:
            self.commerce.add_charge(
                order_id=order.id,
                kind=kind,
                amount=Decimal(amount),
                currency="CNY",
                fx_rate=Decimal("1"),
                evidence_ref=f"invoice://{kind.value}",
            )
        snapshot = self.commerce.calculate_profit(order.id)
        self.assertEqual(snapshot.cm3_cny, Decimal("350"))
        approval = self.commerce.request_approval(
            action="listing.publish",
            resource_type="product",
            resource_id=product.id,
            requested_by="operator",
            payload={},
        )
        with self.assertRaisesRegex(ValueError, "own high-risk action"):
            self.commerce.decide_approval(approval.id, approved=True, decided_by="operator", reason="self")

    def test_agent_permissions_and_idempotency(self):
        first = self.commerce.submit_agent_task(
            agent="listing",
            mode=AgentMode.DRAFT,
            task_type="listing.generate",
            input_data={"product_id": self.product.id},
            requested_by="operator",
            idempotency_key="job-1",
        )
        second = self.commerce.submit_agent_task(
            agent="listing",
            mode=AgentMode.DRAFT,
            task_type="listing.generate",
            input_data={"product_id": self.product.id},
            requested_by="operator",
            idempotency_key="job-1",
        )
        self.assertEqual(first.id, second.id)
        with self.assertRaises(PermissionError):
            self.commerce.submit_agent_task(
                agent="listing",
                mode=AgentMode.LIMITED_EXECUTION,
                task_type="listing.publish",
                input_data={},
                requested_by="operator",
                idempotency_key="job-2",
            )
