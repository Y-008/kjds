from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase

from apps.control_plane.content_growth import IMAGE_QA, REQUIRED_QA, ContentGrowthService
from apps.control_plane.domain import (
    AgentMode,
    ApprovalStatus,
    ChargeType,
    ContentStatus,
    ContentType,
    PassportType,
    ProductStatus,
)
from apps.control_plane.evidence import EvidenceGrade
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
        self.demand_report_id = "evd-demand-report-approved"
        self.commerce = CommerceService(self.repo, evidence_validator=lambda _: None)
        self.generated_evidence = {}
        self.market_evidence = {}
        self.market = MarketIntelligenceService(
            self.repo,
            evidence_validator=self._validate_market_evidence,
            evidence_lookup=self._lookup_market_evidence,
            demand_report_validator=self._validate_demand_report,
            evidence_authority_lookup=self._candidate_authority_grade,
        )
        self.media_ready = {
            "ready_for_full_production": True,
            "roles": [
                {
                    "role": role,
                    "status": "approved",
                    "source_asset_evidence_id": f"evidence://source-{role}",
                    "rights_evidence_id": f"evidence://rights-{role}",
                }
                for role in (
                    "front_main",
                    "back",
                    "side",
                    "detail",
                    "accessories",
                    "packaging",
                    "scale_reference",
                )
            ],
        }
        self.media_ready["roles"][0]["source_asset_evidence_id"] = "evidence://quality"
        self.media_ready["roles"][0]["rights_evidence_id"] = "evidence://compliance"
        self.content = ContentGrowthService(
            self.repo,
            evidence_validator=lambda _: None,
            evidence_lookup=self.generated_evidence.__getitem__,
            image_readiness=lambda _: self.media_ready,
        )
        self.product = self.commerce.create_product(sku="TEST-001", name="Test Product")

    def _add_market_evidence(
        self,
        evidence_id: str,
        source: str,
        source_ref: str,
        *,
        effective_until: str | None = None,
        valid: bool = True,
        grade: EvidenceGrade = EvidenceGrade.A,
    ) -> str:
        self.market_evidence[evidence_id] = SimpleNamespace(
            id=evidence_id,
            source=source,
            source_ref=source_ref,
            effective_at="2026-07-18T00:00:00+00:00",
            effective_until=effective_until,
            valid=valid,
            grade=grade,
        )
        return evidence_id

    def _validate_market_evidence(self, evidence_ids: list[str]) -> None:
        for evidence_id in evidence_ids:
            record = self.market_evidence.get(evidence_id)
            if record is None or not record.valid:
                raise ValueError(f"Invalid evidence: {evidence_id}")

    def _lookup_market_evidence(self, evidence_id: str):
        try:
            return self.market_evidence[evidence_id]
        except KeyError as exc:
            raise KeyError(f"Unknown evidence: {evidence_id}") from exc

    def _validate_demand_report(self, evidence_id: str) -> None:
        if evidence_id != self.demand_report_id:
            raise ValueError("Demand report is not currently accepted")

    def _candidate_authority_grade(self, evidence_id: str, _metric: str) -> EvidenceGrade:
        return EvidenceGrade(self._lookup_market_evidence(evidence_id).grade)

    def _candidate_dimensions(self, candidate_ref: str, metric: str, evidence_id: str) -> dict[str, str]:
        return self.market.candidate_measurement_dimensions(
            candidate_ref=candidate_ref,
            evidence_id=evidence_id,
            demand_report_evidence_id=self.demand_report_id,
            metric=metric,
            window_days=30,
            sample_size=1 if metric in {"supplier_available", "compliance_redline"} else 30,
        )

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

    def test_candidate_research_requires_current_independent_evidence_before_quotes(self):
        candidate = "candidate://kitchen-organizer-v1"
        observations = (
            ("ozon-analytics", "demand_signal", "82", "https://seller.ozon.ru/analytics/demand"),
            ("ozon-analytics", "competition_gap", "61", "https://seller.ozon.ru/analytics/competition"),
            ("supplier-market", "supplier_available", "1", "https://detail.1688.com/offer/example"),
            ("official-rules", "compliance_redline", "0", "https://docs.ozon.ru/global/products/rules"),
            ("ozon-analytics", "return_risk", "24", "https://seller.ozon.ru/analytics/returns"),
        )
        for source, metric, value, source_ref in observations:
            evidence_id = self._add_market_evidence(f"evd-{metric}", source, source_ref)
            self.market.ingest(
                source=source,
                market="RU",
                category="kitchen_storage",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=source_ref,
                confidence=Decimal("0.8"),
                dimensions=self._candidate_dimensions(candidate, metric, evidence_id),
            )

        assessment = self.market.assess_candidate_research(
            candidate_ref=candidate,
            candidate_name="Kitchen organizer",
            market="RU",
            category="kitchen_storage",
            as_of="2026-07-19T00:00:00+00:00",
            demand_report_evidence_id=self.demand_report_id,
        )

        self.assertEqual(assessment["decision"], "request_three_quotes")
        self.assertEqual(assessment["demand_report_evidence_id"], self.demand_report_id)
        self.assertEqual(assessment["source_families"], ["1688.com", "ozon.ru"])
        self.assertEqual(len(assessment["observation_ids"]), 5)
        self.assertEqual(len(assessment["evidence_ids"]), 5)
        self.assertEqual(assessment["measurement_policy_id"], "ozon-ru-candidate-measurement-v1")
        self.assertEqual(assessment["quote_policy_id"], "ozon-ru-quote-screen-v1")
        self.assertEqual(assessment["quote_policy_status"], "engineering_default_requires_owner_review")
        self.assertEqual(assessment["metric_values"]["demand_signal"], "82")
        self.assertEqual(assessment["threshold_failures"], [])
        self.assertEqual(assessment["required_supplier_quotes"], 3)
        self.assertFalse(assessment["automatic_product_creation"])
        self.assertFalse(assessment["automatic_listing"])

    def test_candidate_research_keeps_secondary_sources_but_does_not_qualify_them(self):
        candidate = "candidate://secondary-only-v1"
        for metric, value, source_ref in (
            ("demand_signal", "82", "https://www.seerfar.cn/market/example"),
            ("competition_gap", "61", "https://www.bdmozon.com/category/example"),
            ("supplier_available", "1", "https://erp.91miaoshou.com/supplier/example"),
            ("compliance_redline", "0", "https://ozon.menglar.com/tools/example"),
            ("return_risk", "24", "https://www.51selling.com/returns/example"),
        ):
            evidence_id = self._add_market_evidence(
                f"evd-secondary-{metric}",
                "third-party-market-tool",
                source_ref,
                grade=EvidenceGrade.C,
            )
            self.market.ingest(
                source="third-party-market-tool",
                market="RU",
                category="storage",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=source_ref,
                confidence=Decimal("0.8"),
                dimensions=self._candidate_dimensions(candidate, metric, evidence_id),
            )

        assessment = self.market.assess_candidate_research(
            candidate_ref=candidate,
            candidate_name="Secondary-only candidate",
            market="RU",
            category="storage",
            as_of="2026-07-19T00:00:00Z",
            demand_report_evidence_id=self.demand_report_id,
        )

        self.assertEqual(assessment["decision"], "collect_evidence")
        self.assertEqual(len(assessment["low_authority_evidence_ids"]), 5)
        self.assertEqual(set(assessment["missing_metrics"]), set(assessment["required_metrics"]))
        self.assertEqual(assessment["minimum_evidence_grades"]["compliance_redline"], ["A"])
        self.assertIn("below the required authority grade", " ".join(assessment["reasons"]))
        self.assertEqual(len(self.repo.observations_for("RU", "storage")), 5)

    def test_candidate_research_rejects_unaccepted_or_mixed_demand_report(self):
        with self.assertRaisesRegex(ValueError, "not currently accepted"):
            self.market.assess_candidate_research(
                candidate_ref="candidate://unaccepted-report",
                candidate_name="Unaccepted report",
                market="RU",
                category="storage",
                as_of="2026-07-19T00:00:00Z",
                demand_report_evidence_id="evd-demand-report-pending",
            )

        candidate = "candidate://mixed-report"
        for metric, value in (
            ("demand_signal", "82"),
            ("competition_gap", "61"),
            ("supplier_available", "1"),
            ("compliance_redline", "0"),
            ("return_risk", "24"),
        ):
            evidence_id = self._add_market_evidence(
                f"evd-mixed-{metric}", "source-a", f"https://example.com/{metric}"
            )
            self.market.ingest(
                source="source-a",
                market="RU",
                category="storage",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=f"https://example.com/{metric}",
                confidence=Decimal("0.8"),
                dimensions=self._candidate_dimensions(candidate, metric, evidence_id),
            )

        self.market.demand_report_validator = lambda _evidence_id: None
        assessment = self.market.assess_candidate_research(
            candidate_ref=candidate,
            candidate_name="Mixed report",
            market="RU",
            category="storage",
            as_of="2026-07-19T00:00:00Z",
            demand_report_evidence_id="evd-demand-report-other",
        )
        self.assertEqual(assessment["decision"], "collect_evidence")
        self.assertEqual(len(assessment["invalid_evidence_ids"]), 5)
        self.assertEqual(set(assessment["missing_metrics"]), set(assessment["required_metrics"]))

    def test_candidate_research_rejects_metrics_below_quote_policy(self):
        candidate = "candidate://weak-economics-v1"
        for metric, value, source_ref in (
            ("demand_signal", "49", "https://seller.ozon.ru/analytics/demand"),
            ("competition_gap", "45", "https://seller.ozon.ru/analytics/competition"),
            ("supplier_available", "1", "https://detail.1688.com/offer/example"),
            ("compliance_redline", "0", "https://docs.ozon.ru/global/products/rules"),
            ("return_risk", "31", "https://seller.ozon.ru/analytics/returns"),
        ):
            source = "supplier-market" if "1688" in source_ref else "ozon-source"
            evidence_id = self._add_market_evidence(f"evd-weak-{metric}", source, source_ref)
            self.market.ingest(
                source=source,
                market="RU",
                category="storage",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=source_ref,
                confidence=Decimal("0.8"),
                dimensions=self._candidate_dimensions(candidate, metric, evidence_id),
            )

        assessment = self.market.assess_candidate_research(
            candidate_ref=candidate,
            candidate_name="Weak candidate",
            market="RU",
            category="storage",
            as_of="2026-07-19T00:00:00Z",
            demand_report_evidence_id=self.demand_report_id,
        )

        self.assertEqual(assessment["decision"], "reject")
        self.assertIsNone(assessment["next_gate"])
        self.assertEqual(
            {item["metric"] for item in assessment["threshold_failures"]},
            {"demand_signal", "competition_gap", "return_risk"},
        )

    def test_candidate_submission_rejects_insufficient_measurement_sample_without_writes(self):
        inputs = []
        for metric, value in (
            ("demand_signal", "82"),
            ("competition_gap", "61"),
            ("supplier_available", "1"),
            ("compliance_redline", "0"),
            ("return_risk", "24"),
        ):
            evidence_id = self._add_market_evidence(
                f"evd-small-sample-{metric}", "source-a", f"https://example.com/{metric}"
            )
            inputs.append(
                {
                    "metric": metric,
                    "value": value,
                    "confidence": "0.8",
                    "evidence_id": evidence_id,
                    "window_days": 30,
                    "sample_size": 1,
                }
            )

        with self.assertRaisesRegex(ValueError, "sample_size must be at least 30"):
            self.market.submit_candidate_research(
                candidate_ref="candidate://small-sample",
                candidate_name="Small sample",
                market="RU",
                category="storage",
                as_of="2026-07-19T00:00:00Z",
                demand_report_evidence_id=self.demand_report_id,
                observations=inputs,
            )

        self.assertEqual(self.repo.observations_for("RU", "storage"), [])

    def test_candidate_research_submission_is_atomic_and_idempotent(self):
        candidate = "candidate://drawer-organizer-v1"
        inputs = []
        for metric, value, source, source_ref in (
            ("demand_signal", "82", "ozon-analytics", "https://seller.ozon.ru/analytics/demand"),
            ("competition_gap", "61", "ozon-analytics", "https://seller.ozon.ru/analytics/competition"),
            ("supplier_available", "1", "supplier-market", "https://detail.1688.com/offer/example"),
            ("compliance_redline", "0", "official-rules", "https://docs.ozon.ru/global/products/rules"),
            ("return_risk", "24", "ozon-analytics", "https://seller.ozon.ru/analytics/returns"),
        ):
            evidence_id = self._add_market_evidence(f"evd-submit-{metric}", source, source_ref)
            inputs.append(
                {
                    "metric": metric,
                    "value": value,
                    "confidence": "0.8",
                    "evidence_id": evidence_id,
                    "window_days": 30,
                    "sample_size": 1 if metric in {"supplier_available", "compliance_redline"} else 30,
                }
            )

        arguments = {
            "candidate_ref": candidate,
            "candidate_name": "Drawer organizer",
            "market": "RU",
            "category": "kitchen_storage",
            "as_of": "2026-07-19T00:00:00Z",
            "demand_report_evidence_id": self.demand_report_id,
            "observations": inputs,
        }
        first = self.market.submit_candidate_research(**arguments)
        second = self.market.submit_candidate_research(**arguments)

        rows = self.repo.observations_for("RU", "kitchen_storage")
        self.assertEqual(first["decision"], "request_three_quotes")
        self.assertEqual(second["observation_ids"], first["observation_ids"])
        self.assertEqual(len(rows), 5)
        self.assertEqual(len([event for event in self.repo.events if event["type"] == "market.observation_ingested"]), 5)
        demand = next(row for row in rows if row.metric == "demand_signal")
        self.assertEqual(demand.source, "ozon-analytics")
        self.assertEqual(demand.source_ref, "https://seller.ozon.ru/analytics/demand")
        self.assertEqual(demand.observed_at, "2026-07-18T00:00:00+00:00")

    def test_candidate_sourcing_handoff_requires_confirmation_and_is_idempotent(self):
        candidate = "candidate://quote-workspace-v1"
        for metric, value, source, source_ref in (
            ("demand_signal", "82", "ozon-analytics", "https://seller.ozon.ru/analytics/demand"),
            ("competition_gap", "61", "ozon-analytics", "https://seller.ozon.ru/analytics/competition"),
            ("supplier_available", "1", "supplier-market", "https://detail.1688.com/offer/example"),
            ("compliance_redline", "0", "official-rules", "https://docs.ozon.ru/global/products/rules"),
            ("return_risk", "24", "ozon-analytics", "https://seller.ozon.ru/analytics/returns"),
        ):
            evidence_id = self._add_market_evidence(f"evd-handoff-{metric}", source, source_ref)
            self.market.ingest(
                source=source,
                market="RU",
                category="kitchen_storage",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=source_ref,
                confidence=Decimal("0.8"),
                dimensions=self._candidate_dimensions(candidate, metric, evidence_id),
            )

        arguments = {
            "candidate_ref": candidate,
            "candidate_name": "Quote workspace",
            "market": "RU",
            "category": "kitchen_storage",
            "as_of": "2026-07-19T00:00:00Z",
            "demand_report_evidence_id": self.demand_report_id,
            "sku": "RU-QUOTE-001",
            "confirmed_by": "operator@example.com",
        }
        with self.assertRaisesRegex(ValueError, "explicit human confirmation"):
            self.market.handoff_candidate_to_sourcing(**arguments, confirmed=False)

        with self.assertRaisesRegex(ValueError, "Action authorization denied"):
            self.market.handoff_candidate_to_sourcing(**arguments, confirmed=True)
        self.assertFalse(any(item.sku == "RU-QUOTE-001" for item in self.repo.list_products()))

        approval = self.commerce.request_approval(
            action="candidate.promote",
            resource_type="market_candidate",
            resource_id=candidate,
            requested_by=arguments["confirmed_by"],
            payload={
                "candidate_ref": candidate,
                "candidate_name": arguments["candidate_name"],
                "market": "RU",
                "category": arguments["category"],
                "as_of": arguments["as_of"],
                "demand_report_evidence_id": arguments["demand_report_evidence_id"],
                "sku": arguments["sku"],
                "max_age_days": 90,
            },
        )
        self.commerce.decide_approval(
            approval.id,
            approved=True,
            decided_by="reviewer@example.com",
            reason="Independent candidate promotion review passed",
        )
        first = self.market.handoff_candidate_to_sourcing(**arguments, confirmed=True)
        second = self.market.handoff_candidate_to_sourcing(**arguments, confirmed=True)

        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["product"].id, second["product"].id)
        self.assertEqual(first["product"].status, ProductStatus.CANDIDATE)
        self.assertEqual(first["demand_report_evidence_id"], self.demand_report_id)
        self.assertEqual(first["next_gate"], "sourcing_comparison_intake")
        self.assertFalse(first["automatic_procurement"])
        self.assertFalse(first["automatic_listing"])
        self.assertEqual(len([item for item in self.repo.list_products() if item.sku == "RU-QUOTE-001"]), 1)
        self.assertEqual(
            len(
                [
                    event
                    for event in self.repo.events
                    if event["type"] == "product.candidate_sourcing_workspace_created"
                ]
            ),
            1,
        )

    def test_candidate_research_submission_writes_nothing_when_any_evidence_is_invalid(self):
        inputs = []
        for metric, value in (
            ("demand_signal", "82"),
            ("competition_gap", "61"),
            ("supplier_available", "1"),
            ("compliance_redline", "0"),
            ("return_risk", "24"),
        ):
            evidence_id = self._add_market_evidence(
                f"evd-atomic-{metric}",
                "source-a",
                f"https://example.com/{metric}",
                valid=metric != "return_risk",
            )
            inputs.append(
                {
                    "metric": metric,
                    "value": value,
                    "confidence": "0.8",
                    "evidence_id": evidence_id,
                    "window_days": 30,
                    "sample_size": 1 if metric in {"supplier_available", "compliance_redline"} else 30,
                }
            )

        initial_events = list(self.repo.events)
        with self.assertRaisesRegex(ValueError, "Invalid evidence"):
            self.market.submit_candidate_research(
                candidate_ref="candidate://atomic-failure",
                candidate_name="Atomic failure",
                market="RU",
                category="storage",
                as_of="2026-07-19T00:00:00Z",
                demand_report_evidence_id=self.demand_report_id,
                observations=inputs,
            )

        self.assertEqual(self.repo.observations_for("RU", "storage"), [])
        self.assertEqual(self.repo.events, initial_events)

    def test_candidate_research_rejects_current_compliance_redline(self):
        candidate = "candidate://restricted-product-v1"
        for metric, value in (
            ("demand_signal", "90"),
            ("competition_gap", "70"),
            ("supplier_available", "1"),
            ("compliance_redline", "1"),
            ("return_risk", "10"),
        ):
            source = "source-a" if metric != "supplier_available" else "source-b"
            source_ref = f"https://example.com/{metric}"
            evidence_id = self._add_market_evidence(f"evd-redline-{metric}", source, source_ref)
            self.market.ingest(
                source=source,
                market="RU",
                category="regulated",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=source_ref,
                confidence=Decimal("0.8"),
                dimensions=self._candidate_dimensions(candidate, metric, evidence_id),
            )

        assessment = self.market.assess_candidate_research(
            candidate_ref=candidate,
            candidate_name="Restricted product",
            market="RU",
            category="regulated",
            as_of="2026-07-19T00:00:00Z",
            demand_report_evidence_id=self.demand_report_id,
        )

        self.assertEqual(assessment["decision"], "reject")
        self.assertIsNone(assessment["next_gate"])

    def test_candidate_research_does_not_mix_evidence_between_candidates(self):
        evidence_id = self._add_market_evidence(
            "evd-other-demand", "ozon-analytics", "https://seller.ozon.ru/analytics/demand"
        )
        self.market.ingest(
            source="ozon-analytics",
            market="RU",
            category="storage",
            metric="demand_signal",
            value=Decimal("80"),
            observed_at="2026-07-18T00:00:00Z",
            source_ref="https://seller.ozon.ru/analytics/demand",
            confidence=Decimal("0.9"),
            dimensions=self._candidate_dimensions("candidate://other", "demand_signal", evidence_id),
        )

        assessment = self.market.assess_candidate_research(
            candidate_ref="candidate://target",
            candidate_name="Target candidate",
            market="RU",
            category="storage",
            as_of="2026-07-19T00:00:00Z",
            demand_report_evidence_id=self.demand_report_id,
        )

        self.assertEqual(assessment["decision"], "collect_evidence")
        self.assertEqual(set(assessment["missing_metrics"]), set(assessment["required_metrics"]))
        self.assertEqual(assessment["observation_ids"], [])
        self.assertEqual(assessment["evidence_ids"], [])

    def test_candidate_research_rejects_zero_confidence_observations(self):
        candidate = "candidate://zero-confidence"
        for metric, value in (
            ("demand_signal", "80"),
            ("competition_gap", "60"),
            ("supplier_available", "1"),
            ("compliance_redline", "0"),
            ("return_risk", "20"),
        ):
            self.market.ingest(
                source="untrusted-feed",
                market="RU",
                category="storage",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=f"https://untrusted.example/{metric}",
                confidence=Decimal("0"),
                dimensions=self._candidate_dimensions(candidate, metric, f"missing-{metric}"),
            )

        assessment = self.market.assess_candidate_research(
            candidate_ref=candidate,
            candidate_name="Zero confidence candidate",
            market="RU",
            category="storage",
            as_of="2026-07-19T00:00:00Z",
            demand_report_evidence_id=self.demand_report_id,
        )

        self.assertEqual(assessment["decision"], "collect_evidence")
        self.assertEqual(set(assessment["missing_metrics"]), set(assessment["required_metrics"]))
        self.assertEqual(len(assessment["invalid_evidence_ids"]), len(assessment["required_metrics"]))

    def test_candidate_research_rejects_missing_or_mismatched_ledger_evidence(self):
        candidate = "candidate://unverified-source"
        for metric, value in (
            ("demand_signal", "80"),
            ("competition_gap", "60"),
            ("supplier_available", "1"),
            ("compliance_redline", "0"),
            ("return_risk", "20"),
        ):
            source = "ozon-analytics" if metric != "supplier_available" else "supplier-market"
            source_ref = f"https://seller.ozon.ru/{metric}"
            evidence_id = f"evd-unverified-{metric}"
            if metric != "demand_signal":
                recorded_ref = "https://different.example/source" if metric == "return_risk" else source_ref
                self._add_market_evidence(evidence_id, source, recorded_ref)
            self.market.ingest(
                source=source,
                market="RU",
                category="storage",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=source_ref,
                confidence=Decimal("0.8"),
                dimensions=self._candidate_dimensions(candidate, metric, evidence_id),
            )

        assessment = self.market.assess_candidate_research(
            candidate_ref=candidate,
            candidate_name="Unverified source candidate",
            market="RU",
            category="storage",
            as_of="2026-07-19T00:00:00Z",
            demand_report_evidence_id=self.demand_report_id,
        )

        self.assertEqual(assessment["decision"], "collect_evidence")
        self.assertEqual(len(assessment["invalid_evidence_ids"]), 2)
        self.assertEqual(set(assessment["missing_metrics"]), {"demand_signal", "return_risk"})

    def test_candidate_research_rejects_corrupt_or_expired_ledger_evidence(self):
        candidate = "candidate://corrupt-or-expired"
        for metric, value in (
            ("demand_signal", "80"),
            ("competition_gap", "60"),
            ("supplier_available", "1"),
            ("compliance_redline", "0"),
            ("return_risk", "20"),
        ):
            source = "ozon-analytics" if metric != "supplier_available" else "supplier-market"
            source_ref = f"https://seller.ozon.ru/{metric}"
            evidence_id = self._add_market_evidence(
                f"evd-integrity-{metric}",
                source,
                source_ref,
                effective_until="2026-07-18T12:00:00Z" if metric == "return_risk" else None,
                valid=metric != "demand_signal",
            )
            self.market.ingest(
                source=source,
                market="RU",
                category="storage",
                metric=metric,
                value=Decimal(value),
                observed_at="2026-07-18T00:00:00Z",
                source_ref=source_ref,
                confidence=Decimal("0.8"),
                dimensions=self._candidate_dimensions(candidate, metric, evidence_id),
            )

        assessment = self.market.assess_candidate_research(
            candidate_ref=candidate,
            candidate_name="Corrupt or expired candidate",
            market="RU",
            category="storage",
            as_of="2026-07-19T00:00:00Z",
            demand_report_evidence_id=self.demand_report_id,
        )

        self.assertEqual(assessment["decision"], "collect_evidence")
        self.assertEqual(len(assessment["invalid_evidence_ids"]), 1)
        self.assertEqual(len(assessment["stale_evidence_ids"]), 1)
        self.assertEqual(set(assessment["missing_metrics"]), {"demand_signal", "return_risk"})

    def test_content_requires_grounded_passports_and_full_qa(self):
        self.approve_passports()
        self.commerce.validate_product(self.product.id)
        with self.assertRaisesRegex(ValueError, "source_asset_evidence_ids"):
            self.content.create_content_brief(
                product_id=self.product.id,
                content_type=ContentType.IMAGE,
                locale="ru-RU",
                channel="OZON",
                brief={"goal": "main image", "generation_mode": "retouch", "preserve_product_facts": True},
            )
        asset = self.content.create_content_brief(
            product_id=self.product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="OZON",
            brief={
                "goal": "main image",
                "generation_mode": "retouch",
                "preserve_product_facts": True,
                "source_asset_evidence_ids": ["evidence://quality"],
                "rights_evidence_ids": ["evidence://compliance"],
            },
        )
        self.generated_evidence["evidence://generated-main"] = SimpleNamespace(
            content_type="image/png",
            metadata={
                "content_asset_id": asset.id,
                "generation_mode": "retouch",
                "source_asset_evidence_ids": ["evidence://quality"],
                "process": "manual-retouch",
                "generated_at": "2026-07-18T06:00:00Z",
            },
        )
        self.content.attach_generated_asset(asset.id, artifact_ref="evidence://generated-main")
        checks = [
            {"check": name, "passed": True, "notes": f"{name} checked", "evidence_ids": []}
            for name in sorted(REQUIRED_QA | IMAGE_QA)
        ]
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.content.review_asset(asset.id, checks=checks[:-1], reviewed_by="reviewer@example.com")
        unknown_checks = [*checks[:-1], {"check": "looks_nice", "passed": True, "notes": "subjective"}]
        with self.assertRaisesRegex(ValueError, "Unknown content QA checks"):
            self.content.review_asset(asset.id, checks=unknown_checks, reviewed_by="reviewer@example.com")
        reviewed = self.content.review_asset(asset.id, checks=checks, reviewed_by="reviewer@example.com")
        self.assertEqual(reviewed.status, ContentStatus.APPROVED)
        self.assertEqual({item["reviewed_by"] for item in reviewed.qa_results}, {"reviewer@example.com"})
        self.assertTrue(all(item["reviewed_at"].endswith("+00:00") for item in reviewed.qa_results))
        self.assertEqual(len(reviewed.qa_results), 8)

    def test_image_brief_requires_complete_approved_media_readiness(self):
        self.approve_passports()
        self.media_ready["ready_for_full_production"] = False
        self.media_ready["roles"][-1]["status"] = "missing"
        with self.assertRaisesRegex(ValueError, "all seven source and rights roles"):
            self.content.create_content_brief(
                product_id=self.product.id,
                content_type=ContentType.IMAGE,
                locale="ru-RU",
                channel="OZON",
                brief={
                    "goal": "main image",
                    "generation_mode": "retouch",
                    "preserve_product_facts": True,
                    "source_asset_evidence_ids": ["evidence://quality"],
                    "rights_evidence_ids": ["evidence://compliance"],
                },
            )

    def test_image_brief_requires_exact_source_rights_pair(self):
        self.approve_passports()
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.content.create_content_brief(
                product_id=self.product.id,
                content_type=ContentType.IMAGE,
                locale="ru-RU",
                channel="OZON",
                brief={
                    "goal": "main image",
                    "generation_mode": "retouch",
                    "preserve_product_facts": True,
                    "source_asset_evidence_ids": ["evidence://quality"],
                    "rights_evidence_ids": ["evidence://rights-back"],
                },
            )

    def test_image_qa_fails_closed_on_product_fidelity(self):
        self.approve_passports()
        asset = self.content.create_content_brief(
            product_id=self.product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="OZON",
            brief={
                "goal": "lifestyle image",
                "generation_mode": "composite",
                "preserve_product_facts": True,
                "source_asset_evidence_ids": ["evidence://quality"],
                "rights_evidence_ids": ["evidence://compliance"],
            },
        )
        self.generated_evidence["evidence://generated-scene"] = SimpleNamespace(
            content_type="image/webp",
            metadata={
                "content_asset_id": asset.id,
                "generation_mode": "composite",
                "source_asset_evidence_ids": ["evidence://quality"],
                "process": "comfyui",
                "generated_at": "2026-07-18T06:00:00Z",
            },
        )
        self.content.attach_generated_asset(asset.id, artifact_ref="evidence://generated-scene")
        checks = [
            {
                "check": name,
                "passed": name != "product_fidelity",
                "notes": "mismatch found" if name == "product_fidelity" else f"{name} checked",
                "evidence_ids": [],
            }
            for name in sorted(REQUIRED_QA | IMAGE_QA)
        ]
        reviewed = self.content.review_asset(asset.id, checks=checks, reviewed_by="reviewer@example.com")
        self.assertEqual(reviewed.status, ContentStatus.QA_FAILED)

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
            (ChargeType.WAREHOUSING, "10"),
            (ChargeType.TAX, "15"),
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
        self.assertEqual(snapshot.cm3_cny, Decimal("325"))
        approval = self.commerce.request_approval(
            action="listing.publish",
            resource_type="product",
            resource_id=product.id,
            requested_by="operator",
            payload={},
        )
        with self.assertRaisesRegex(ValueError, "own high-risk action"):
            self.commerce.decide_approval(approval.id, approved=True, decided_by="operator", reason="self")
        decided = self.commerce.decide_approval(
            approval.id,
            approved=True,
            decided_by="independent-approver",
            reason="independent evidence review",
        )
        self.assertEqual(decided.status, ApprovalStatus.APPROVED)
        with self.assertRaisesRegex(ValueError, "already been decided"):
            self.commerce.decide_approval(
                approval.id,
                approved=True,
                decided_by="another-approver",
                reason="replayed decision",
            )

    def test_core_numeric_boundaries_reject_nonfinite_values(self):
        self.approve_passports()
        product = self.commerce.validate_product(self.product.id)
        with self.assertRaisesRegex(ValueError, "Gross revenue must be finite"):
            self.commerce.create_order(
                external_id="OZON-NAN",
                product_id=product.id,
                quantity=1,
                currency="CNY",
                gross_revenue=Decimal("NaN"),
                booked_fx_rate=Decimal("1"),
            )
        order = self.commerce.create_order(
            external_id="OZON-FINITE",
            product_id=product.id,
            quantity=1,
            currency="CNY",
            gross_revenue=Decimal("100"),
            booked_fx_rate=Decimal("1"),
        )
        with self.assertRaisesRegex(ValueError, "Charge amount must be finite"):
            self.commerce.add_charge(
                order_id=order.id,
                kind=ChargeType.PLATFORM_FEE,
                amount=Decimal("NaN"),
                currency="CNY",
                fx_rate=Decimal("1"),
                evidence_ref="invoice://nan",
            )
        with self.assertRaisesRegex(ValueError, "Market observation confidence must be finite"):
            self.market.ingest(
                source="test",
                market="RU",
                category="storage",
                metric="demand",
                value=Decimal("1"),
                observed_at="2026-07-17T00:00:00+00:00",
                source_ref="source://test",
                confidence=Decimal("NaN"),
            )
        with self.assertRaisesRegex(ValueError, "Experiment budget must be finite"):
            self.content.create_experiment(
                product_id=product.id,
                channel="OZON",
                hypothesis="non-finite budget must fail",
                primary_metric="cm3",
                budget_cap_cny=Decimal("Infinity"),
                stop_loss_cny=Decimal("10"),
                variants=["a", "b"],
            )

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
