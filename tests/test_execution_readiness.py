from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.content_growth import QA_ORDER
from apps.control_plane.cost_evidence_review import CostEvidenceAuthorityService
from apps.control_plane.demand_report_gate import DemandReportGateService
from apps.control_plane.domain import ContentAsset, ContentStatus, ContentType, PassportType
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.execution_authority import ListingExecutionAuthorityService
from apps.control_plane.readiness import (
    LISTING_EXECUTION_READINESS_KEYS,
    ExecutionReadinessContext,
    ExecutionReadinessService,
)
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.security import KillSwitchService
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
)
from apps.control_plane.sql_repository import Base

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
        "golden_sample_ref": "sample://RU-READY-001/golden",
        "inspection_plan": ["dimensions", "material", "appearance"],
        "packaging_test": "passed",
    },
}


class MemorySourcingStore:
    def __init__(self) -> None:
        self.offers: dict[str, SupplierOffer] = {}
        self.scenarios: dict[str, ProfitScenario] = {}
        self.drafts: dict[str, ListingDraft] = {}

    def save_offer(self, offer: SupplierOffer) -> SupplierOffer:
        self.offers[offer.id] = offer
        return offer

    def get_offer(self, offer_id: str) -> SupplierOffer:
        return self.offers[offer_id]

    def list_offers(self, limit: int = 100) -> list[SupplierOffer]:
        return list(self.offers.values())[:limit]

    def save_scenario(self, scenario: ProfitScenario) -> ProfitScenario:
        self.scenarios[scenario.id] = scenario
        return scenario

    def get_scenario(self, scenario_id: str) -> ProfitScenario:
        return self.scenarios[scenario_id]

    def list_scenarios(self, limit: int = 1000) -> list[ProfitScenario]:
        return list(self.scenarios.values())[:limit]

    def save_listing_draft(self, draft: ListingDraft) -> ListingDraft:
        self.drafts[draft.id] = draft
        return draft

    def attach_listing_approval(self, draft: ListingDraft) -> ListingDraft:
        self.drafts[draft.id] = draft
        return draft

    def get_listing_draft(self, draft_id: str) -> ListingDraft:
        return self.drafts[draft_id]

    def list_listing_drafts(self, limit: int = 100) -> list[ListingDraft]:
        return list(self.drafts.values())[:limit]


def capture(evidence: EvidenceService, name: str, *, created_by: str = "fixture-uploader"):
    return evidence.capture(
        content=name.encode(),
        filename=f"{name}.json",
        content_type="application/json",
        source="execution_readiness_fixture",
        source_ref=f"fixture://execution-readiness/{name}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-24T00:00:00Z",
        effective_until=None,
        created_by=created_by,
    )


def build_ready_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    repository = InMemoryRepository()
    commerce = CommerceService(repository, evidence_validator=evidence.require_valid)
    store = MemorySourcingStore()
    cost_authority = CostEvidenceAuthorityService(evidence=evidence)
    sourcing = SourcingService(
        store,
        repository,
        evidence_validator=evidence.require_valid,
        actual_cost_validator=cost_authority.require_actual,
    )
    listing_authority = ListingExecutionAuthorityService(
        evidence=evidence,
        sourcing=sourcing,
    )
    demand_reports = DemandReportGateService(evidence=evidence)
    kill_switch = KillSwitchService(engine)

    product = commerce.create_product(sku="RU-READY-001", name="Storage box")
    passports = {}
    for kind in PassportType:
        basis = capture(evidence, f"passport-{kind.value}")
        passports[kind] = commerce.add_passport(
            product_id=product.id,
            kind=kind,
            facts=PASSPORT_FACTS[kind],
            evidence=[basis.id],
            approved_by="passport-reviewer",
        )
    commerce.validate_product(product.id)

    actual_cost_evidence = capture(
        evidence,
        "supplier-invoice-payment",
        created_by="cost-uploader",
    )
    actual_cost_review = cost_authority.review(
        evidence_id=actual_cost_evidence.id,
        cost_type="product_cost",
        authority_id="supplier_invoice_payment",
        accepted=True,
        authentic_original=True,
        cost_scope_matches=True,
        charging_party_matches=True,
        amount_currency_period_matches=True,
        rationale="Verified invoice, payment, scope, amount, currency, and period.",
        reviewed_by="cost-reviewer",
    )
    assumption_evidence = capture(evidence, "cost-assumptions")
    offer = sourcing.capture_offer(
        SupplierOffer(
            product_id=product.id,
            supplier_ref="1688-shop-100",
            platform=SourcePlatform.ALIBABA_1688,
            external_id="1688-ready-100",
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
            evidence_ref=actual_cost_evidence.id,
            captured_at="2026-07-24T00:00:00Z",
        )
    )
    cost_evidence = {
        key: assumption_evidence.id
        for key in REQUIRED_COST_EVIDENCE_KEYS
        if key not in {"product_cost", "domestic_logistics"}
    }
    cost_states = {key: "estimate" for key in REQUIRED_COST_EVIDENCE_KEYS}
    cost_states["product_cost"] = "actual"
    scenario = sourcing.calculate_profit(
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
        ),
        [assumption_evidence.id],
        cost_evidence,
        cost_states,
    )

    image_evidence = capture(evidence, "approved-main-image")
    asset = repository.add_content_asset(
        ContentAsset(
            product_id=product.id,
            content_type=ContentType.IMAGE,
            locale="ru-RU",
            channel="OZON",
            brief={"goal": "main image"},
            source_facts={},
            status=ContentStatus.APPROVED,
            artifact_ref=image_evidence.id,
            qa_results=[
                {
                    "check": check,
                    "passed": True,
                    "notes": f"{check} independently verified.",
                    "evidence_ids": [],
                    "reviewed_by": "content-reviewer",
                    "reviewed_at": datetime.now(UTC).isoformat(),
                }
                for check in QA_ORDER
            ],
        )
    )
    draft = sourcing.create_ozon_listing_draft(
        product_id=product.id,
        offer_id=offer.id,
        scenario_id=scenario.id,
        content_asset_ids=[asset.id],
        listing_data={
            "title": "Контейнер для хранения",
            "description": "Прочный контейнер для хранения бытовых вещей.",
            "category_id": "123",
            "attributes": [{"id": 1, "values": [{"value": "белый"}]}],
            "images": [image_evidence.id],
        },
        requested_by="listing-requester",
    )
    approval = commerce.request_approval(
        action="listing.publish",
        resource_type="listing_draft",
        resource_id=draft.id,
        requested_by=draft.requested_by,
        payload=listing_approval_payload(draft, scenario),
    )
    draft.approval_id = approval.id
    store.attach_listing_approval(draft)
    commerce.decide_approval(
        approval.id,
        approved=True,
        decided_by="listing-approver",
        reason="Approved the immutable Ozon listing snapshot.",
    )
    russian_review = listing_authority.review_listing(
        draft.id,
        accepted=True,
        native_russian_verified=True,
        listing_snapshot_reviewed=True,
        terminology_accepted=True,
        claims_grounded=True,
        ozon_policy_checked=True,
        rationale="Проверены русский язык, терминология, факты и правила Ozon.",
        reviewed_by="native-reviewer",
    )

    identity_ref = "ozon-worker"
    identity_inventory = capture(
        evidence,
        "ozon-execution-identity-inventory",
        created_by="identity-owner",
    )
    evidence.link(
        evidence_id=identity_inventory.id,
        target_type="gate_requirement",
        target_id="OZN-001",
        relationship="satisfies",
        created_by="identity-owner",
    )
    identity_review = listing_authority.review_execution_identity(
        identity_inventory.id,
        identity_ref=identity_ref,
        accepted=True,
        inventory_complete=True,
        credential_material_absent=True,
        owner_verified=True,
        caller_system_verified=True,
        scope_minimized=True,
        dedicated_executor=True,
        rationale="Verified the dedicated least-privilege Ozon execution identity.",
        reviewed_by="identity-reviewer",
    )

    demand_report = demand_reports.capture_report(
        content=b"date,views,orders\n2026-07-01,100,5\n",
        filename="ozon-data.csv",
        content_type="text/csv",
        effective_at="2026-07-01T00:00:00Z",
        report_window_days=28,
        created_by="demand-uploader",
        source_system="ozon_data",
    )["evidence"]
    demand_review = demand_reports.review(
        report_evidence_id=demand_report.id,
        accepted=True,
        rationale="Verified the Ozon Data source, report window, and fields.",
        reviewed_by="demand-reviewer",
    )
    before_state_evidence = capture(evidence, "ozon-before-state")

    readiness = ExecutionReadinessService(
        commerce=commerce,
        sourcing=sourcing,
        evidence=evidence,
        demand_reports=demand_reports,
        kill_switch=kill_switch,
        listing_execution_authority=listing_authority,
        execution_identity_ref=identity_ref,
    )
    context = ExecutionReadinessContext(
        action_id="listing_publish",
        target={"offer_id": product.sku},
        source_kind="approved_listing_draft",
        source_id=draft.id,
        source_approval_id=approval.id,
        source_snapshot_hash=listing_snapshot_sha256(draft),
        before_state_verified=True,
        before_state_evidence_id=before_state_evidence.id,
        executor_identity_ref=identity_ref,
    )
    return SimpleNamespace(
        evidence=evidence,
        repository=repository,
        commerce=commerce,
        store=store,
        sourcing=sourcing,
        cost_authority=cost_authority,
        listing_authority=listing_authority,
        demand_reports=demand_reports,
        kill_switch=kill_switch,
        readiness=readiness,
        context=context,
        product=product,
        passports=passports,
        scenario=scenario,
        asset=asset,
        draft=draft,
        actual_cost_evidence=actual_cost_evidence,
        actual_cost_review=actual_cost_review,
        russian_review=russian_review,
        identity_ref=identity_ref,
        identity_inventory=identity_inventory,
        identity_review=identity_review,
        demand_report=demand_report,
        demand_review=demand_review,
        before_state_evidence=before_state_evidence,
    )


@pytest.fixture
def execution_ready():
    return build_ready_fixture()


def test_listing_execution_snapshot_exposes_all_ready_server_facts(execution_ready):
    snapshot = execution_ready.readiness.snapshot(execution_ready.context)

    assert tuple(snapshot) == LISTING_EXECUTION_READINESS_KEYS
    assert all(item["ready"] is True for item in snapshot.values())
    assert all(item["blocking_reasons"] == [] for item in snapshot.values())
    assert snapshot["finance.actual_cost_authority"]["evidence_ids"] == sorted(
        [
            execution_ready.actual_cost_evidence.id,
            execution_ready.actual_cost_review["review"].id,
        ]
    )


def revoke_demand(fixture):
    fixture.demand_reports.review(
        report_evidence_id=fixture.demand_report.id,
        accepted=False,
        rationale="The report is no longer accepted for execution.",
        reviewed_by="demand-revoker",
    )


def revoke_snapshot(fixture):
    fixture.context = replace(fixture.context, source_snapshot_hash="0" * 64)


def revoke_passport(fixture):
    fixture.commerce.add_passport(
        product_id=fixture.product.id,
        kind=PassportType.QUALITY,
        facts={
            **PASSPORT_FACTS[PassportType.QUALITY],
            "decision": "blocked",
            "review_notes": "Authority withdrawn.",
        },
        evidence=fixture.passports[PassportType.QUALITY].evidence,
        approved_by="passport-revoker",
    )


def revoke_russian_review(fixture):
    fixture.listing_authority.review_listing(
        fixture.draft.id,
        accepted=False,
        native_russian_verified=False,
        listing_snapshot_reviewed=True,
        terminology_accepted=False,
        claims_grounded=False,
        ozon_policy_checked=True,
        rationale="Listing no longer passes Russian-native review.",
        reviewed_by="native-revoker",
    )


def revoke_image_qa(fixture):
    fixture.asset.qa_results[0]["passed"] = False
    fixture.repository.save_content_asset(fixture.asset)


def revoke_cost_complete(fixture):
    fixture.scenario.cost_evidence.pop("tax")
    fixture.scenario.cost_states["tax"] = "unknown"
    fixture.store.save_scenario(fixture.scenario)


def revoke_cm3(fixture):
    fixture.scenario.cm3_cny = Decimal("0")
    fixture.store.save_scenario(fixture.scenario)


def revoke_actual_cost_authority(fixture):
    fixture.cost_authority.review(
        evidence_id=fixture.actual_cost_evidence.id,
        cost_type="product_cost",
        authority_id="supplier_invoice_payment",
        accepted=False,
        authentic_original=True,
        cost_scope_matches=False,
        charging_party_matches=True,
        amount_currency_period_matches=True,
        rationale="The cost scope no longer matches the product.",
        reviewed_by="cost-revoker",
    )


def revoke_product_source_binding(fixture):
    fixture.context = replace(fixture.context, target={"offer_id": "OTHER-SKU"})


def revoke_before_state(fixture):
    fixture.context = replace(
        fixture.context,
        before_state_verified=False,
        before_state_evidence_id=None,
    )


def revoke_execution_identity(fixture):
    fixture.listing_authority.review_execution_identity(
        fixture.identity_inventory.id,
        identity_ref=fixture.identity_ref,
        accepted=False,
        inventory_complete=True,
        credential_material_absent=True,
        owner_verified=False,
        caller_system_verified=True,
        scope_minimized=False,
        dedicated_executor=True,
        rationale="Owner verification and scope minimization are no longer accepted.",
        reviewed_by="identity-revoker",
    )


def revoke_kill_switch(fixture):
    fixture.kill_switch.set_state(
        engaged=True,
        reason="Test execution revocation",
        actor_id="operations-owner",
    )


REVOCATION_MATRIX = (
    ("demand.real_execution", revoke_demand, "REAL_EXECUTION_DEMAND_EVIDENCE_REQUIRED"),
    ("listing.snapshot_unchanged", revoke_snapshot, "LISTING_SNAPSHOT_OR_APPROVAL_INVALID"),
    ("product.passports", revoke_passport, "PASSPORT_NOT_APPROVED:quality:blocked"),
    ("listing.russian_native_review", revoke_russian_review, "RUSSIAN_NATIVE_REVIEW_INVALID"),
    ("listing.image_qa", revoke_image_qa, "LISTING_IMAGE_QA_INVALID"),
    ("finance.cost_complete", revoke_cost_complete, "FULL_COST_SCENARIO_INVALID"),
    ("finance.cm3_positive", revoke_cm3, "CM3_NOT_POSITIVE"),
    ("finance.actual_cost_authority", revoke_actual_cost_authority, "ACTUAL_COST_AUTHORITY_INVALID"),
    (
        "listing.product_source_binding",
        revoke_product_source_binding,
        "LISTING_PRODUCT_SOURCE_BINDING_INVALID",
    ),
    ("ozon.before_state_claim", revoke_before_state, "OZON_BEFORE_STATE_CLAIM_INVALID"),
    ("ozon.execution_identity", revoke_execution_identity, "OZON_EXECUTION_IDENTITY_INVALID"),
    ("kill_switch.released", revoke_kill_switch, "KILL_SWITCH_ENGAGED"),
)


@pytest.mark.parametrize(
    ("key", "revoke", "blocker"),
    REVOCATION_MATRIX,
    ids=[item[0] for item in REVOCATION_MATRIX],
)
def test_each_listing_execution_fact_is_current_and_revocable(
    execution_ready,
    key,
    revoke,
    blocker,
):
    revoke(execution_ready)
    snapshot = execution_ready.readiness.snapshot(execution_ready.context)

    assert snapshot[key]["ready"] is False
    assert blocker in snapshot[key]["blocking_reasons"]


def test_execution_readiness_scopes_listing_facts_to_listing_sources(execution_ready):
    unsupported = execution_ready.readiness.snapshot(
        replace(execution_ready.context, action_id="sample_pay")
    )
    causal = execution_ready.readiness.snapshot(
        replace(execution_ready.context, source_kind="causal_policy_handoff")
    )
    unavailable = execution_ready.readiness.snapshot(
        replace(execution_ready.context, source_id="lst_missing")
    )

    assert set(unsupported) == {"demand.real_execution"}
    assert set(causal) == {"demand.real_execution"}
    assert all(
        requirement["blocking_reasons"] == ["APPROVED_LISTING_SOURCE_UNAVAILABLE"]
        for key, requirement in unavailable.items()
        if key != "demand.real_execution"
    )


def test_readiness_providers_and_execution_identity_fail_closed(execution_ready):
    execution_ready.demand_reports.status = lambda: {"readiness": {}}
    demand = execution_ready.readiness.snapshot(execution_ready.context)
    assert demand["demand.real_execution"] == {
        "ready": False,
        "evidence_ids": [],
        "blocking_reasons": ["REAL_EXECUTION_DEMAND_STATE_INVALID"],
    }

    mismatched = execution_ready.readiness.snapshot(
        replace(execution_ready.context, executor_identity_ref="other-worker")
    )
    assert mismatched["ozon.execution_identity"]["blocking_reasons"] == [
        "OZON_EXECUTION_IDENTITY_MISMATCH"
    ]

    execution_ready.kill_switch.current = lambda: (_ for _ in ()).throw(
        RuntimeError("unavailable")
    )
    unavailable = execution_ready.readiness.snapshot(execution_ready.context)
    assert unavailable["kill_switch.released"]["blocking_reasons"] == [
        "KILL_SWITCH_STATE_UNAVAILABLE"
    ]
