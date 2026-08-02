from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.logistics import (
    InMemoryLogisticsStore,
    LogisticsQuoteWorkspace,
    LogisticsRateCard,
)
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.security import Principal
from apps.control_plane.services import CommerceService
from apps.control_plane.sourcing import (
    REQUIRED_COST_EVIDENCE_KEYS,
    ProfitInputs,
    SourcePlatform,
    SourcingService,
    SupplierOffer,
)
from apps.control_plane.sourcing_intake import OfferEvidencePayload, SupplierComparisonIntakeService
from apps.control_plane.sql_repository import Base
from apps.control_plane.supplier_quote_authority import SupplierQuoteAuthorityService


class ReadyScopedEvidence:
    def project_targets(self, *, evidence_ids, **_values):
        return {
            "status": "ready",
            "records": [
                {
                    "evidence_id": evidence_id,
                    "scope_binding": {"status": "ready"},
                }
                for evidence_id in evidence_ids
            ],
        }


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
    candidate_basis = evidence.capture(
        content=b"candidate research basis",
        filename="candidate-basis.txt",
        content_type="text/plain",
        source="candidate_research",
        source_ref="https://market.example/candidates/RU-001",
        grade=EvidenceGrade.A,
        effective_at="2026-07-16T00:00:00+08:00",
        effective_until=None,
        created_by="operator-1",
    )
    repository.append_event(
        "product.candidate_sourcing_workspace_created",
        product.id,
        {"candidate_ref": "candidate-RU-001"},
        actor_id="operator-1",
        source_evidence_id=candidate_basis.id,
    )
    evidence.link(
        evidence_id=candidate_basis.id,
        target_type="product",
        target_id=product.id,
        relationship="candidate_basis",
        created_by="operator-1",
    )
    store = MemorySourcingStore()
    authority = SupplierQuoteAuthorityService(evidence=evidence)
    sourcing = SourcingService(
        store,
        repository,
        evidence_validator=evidence.require_valid,
        offer_authority_validator=authority.require_accepted,
    )
    return product, store, SupplierComparisonIntakeService(
        sourcing=sourcing,
        evidence=evidence,
        quote_authority=authority,
    )


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


def accepted_quote_ids(product, intake, payloads=None):
    quote_ids = []
    for payload in payloads or offers():
        record = intake.capture_quote_source(
            product_id=product.id,
            document_kind="supplier_confirmed_quote",
            offer_data=payload.offer_data,
            content=payload.content,
            filename=payload.filename,
            content_type=payload.content_type,
            effective_at="2026-07-16T00:00:00+08:00",
            effective_until="2027-07-16T00:00:00+08:00",
            created_by="operator-1",
        )
        intake.quote_authority.review(
            evidence_id=record.id,
            accepted=True,
            authentic_original=True,
            supplier_identity_matches=True,
            product_spec_matches=True,
            amount_currency_moq_matches=True,
            validity_and_delivery_terms_present=True,
            rationale="Verified against the immutable supplier quotation.",
            reviewed_by="reviewer-1",
        )
        quote_ids.append(record.id)
    return quote_ids


def test_quote_source_replay_cannot_change_immutable_dispatch_context():
    product, _, intake = make_intake()
    payload = offers()[0]
    values = {
        "product_id": product.id,
        "document_kind": "supplier_confirmed_quote",
        "offer_data": payload.offer_data,
        "content": payload.content,
        "filename": payload.filename,
        "content_type": payload.content_type,
        "effective_at": "2026-07-16T00:00:00+08:00",
        "effective_until": "2027-07-16T00:00:00+08:00",
        "created_by": "operator-1",
        "rfq_package_evidence_id": "evd_rfq_1",
        "rfq_dispatch_evidence_id": "evd_dispatch_1",
    }
    first = intake.quote_authority.capture(**values)

    with pytest.raises(ValueError, match="immutable RFQ dispatch context"):
        intake.quote_authority.capture(
            **{
                **values,
                "rfq_dispatch_evidence_id": "evd_dispatch_2",
            }
        )

    assert (
        intake.evidence.get(first.id).metadata[
            "rfq_dispatch_evidence_id"
        ]
        == "evd_dispatch_1"
    )


def test_public_display_price_is_research_only_and_cannot_be_accepted():
    product, store, intake = make_intake()
    payload = offers()[0]
    record = intake.capture_quote_source(
        product_id=product.id,
        document_kind="public_display_price",
        offer_data=payload.offer_data,
        content=b"1688 public product card display price",
        filename="1688-public-card.txt",
        content_type="text/plain",
        effective_at="2026-07-16T00:00:00+08:00",
        effective_until=None,
        created_by="operator-1",
    )

    assert record.grade == EvidenceGrade.B
    assert intake.quote_authority.status(record.id)["status"] == "research_only"
    with pytest.raises(ValueError, match="Public display prices"):
        intake.quote_authority.review(
            evidence_id=record.id,
            accepted=True,
            authentic_original=True,
            supplier_identity_matches=True,
            product_spec_matches=True,
            amount_currency_moq_matches=True,
            validity_and_delivery_terms_present=True,
            rationale="This must remain a research signal.",
            reviewed_by="reviewer-1",
        )
    assert store.offers == {}


def test_supplier_quote_requires_independent_reviewer():
    product, _, intake = make_intake()
    payload = offers()[0]
    record = intake.capture_quote_source(
        product_id=product.id,
        document_kind="supplier_confirmed_quote",
        offer_data=payload.offer_data,
        content=payload.content,
        filename=payload.filename,
        content_type=payload.content_type,
        effective_at="2026-07-16T00:00:00+08:00",
        effective_until="2027-07-16T00:00:00+08:00",
        created_by="operator-1",
    )
    with pytest.raises(ValueError, match="cannot review their own"):
        intake.quote_authority.review(
            evidence_id=record.id,
            accepted=True,
            authentic_original=True,
            supplier_identity_matches=True,
            product_spec_matches=True,
            amount_currency_moq_matches=True,
            validity_and_delivery_terms_present=True,
            rationale="Self-review is forbidden.",
            reviewed_by="operator-1",
        )


def test_accepted_quote_terms_cannot_be_changed_when_creating_formal_offer():
    product, store, intake = make_intake()
    quote_id = accepted_quote_ids(product, intake, offers()[:1])[0]
    changed = dict(offers()[0].offer_data)
    changed["unit_price"] = Decimal("34.99")

    with pytest.raises(ValueError, match="differ from the accepted immutable quote"):
        intake.sourcing.capture_offer(
            SupplierOffer(
                product_id=product.id,
                evidence_ref=quote_id,
                **changed,
            )
        )
    assert store.offers == {}


def test_three_supplier_comparison_is_evidence_backed_and_idempotent():
    product, store, intake = make_intake()
    values = dict(
        product_id=product.id,
        effective_at="2026-07-16T00:00:00+08:00",
        quote_evidence_ids=accepted_quote_ids(product, intake),
        profit_inputs=profit_inputs(),
        assumption_content=b"approved logistics and fee assumptions",
        assumption_filename="assumptions.txt",
        assumption_content_type="text/plain",
        created_by="operator-1",
    )
    first = intake.finalize(**values)
    second = intake.finalize(**values)

    assert len(store.offers) == 3
    assert len(store.scenarios) == 3
    assert [item.id for item in first["offers"]] == [item.id for item in second["offers"]]
    assert first["comparison"]["supplier_count"] == 3
    assert first["comparison"]["ready_for_procurement_review"] is True
    assert first["comparison"]["rows"][0]["scenario"].cm3_cny > first["comparison"]["rows"][-1]["scenario"].cm3_cny


def test_three_supplier_comparison_uses_one_versioned_logistics_tier_per_offer():
    product, store, intake = make_intake()
    rate_evidence = intake.evidence.capture(
        content=b"carrier rate card",
        filename="carrier-rate.txt",
        content_type="text/plain",
        source="carrier_rate_card",
        source_ref="carrier://route-1/2026-07",
        grade=EvidenceGrade.B,
        effective_at="2026-07-15T00:00:00+08:00",
        effective_until=None,
        created_by="operator-1",
    )
    logistics_store = InMemoryLogisticsStore()
    logistics = LogisticsQuoteWorkspace(
        logistics_store,
        evidence_validator=intake.evidence.require_valid,
        evidence_resolver=intake.evidence.get,
        fx_evidence_current_validator=intake.evidence.require_current,
        scoped_evidence=ReadyScopedEvidence(),
    )
    logistics_context = logistics.context(
        principal=Principal(
            actor_id="operator-1",
            roles=frozenset({"operator"}),
            tenant_ref="tenant-a",
            store_refs=frozenset({"store-a"}),
        ),
        entity_scope={
            "status": "ready",
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "authority_sha256": "a" * 64,
        },
        store_ref="store-a",
        as_of=datetime(2026, 7, 16, 0, 0, tzinfo=UTC),
    )
    card = logistics.capture_rate_card(
        logistics_context,
        LogisticsRateCard(
            provider="Carrier A",
            route_code="OZON-RFBS-ALL",
            service_name="Ozon rFBS",
            origin_country="CN",
            destination_country="RU",
            marketplace="OZON",
            currency="CNY",
            declared_value_currency="RUB",
            price_per_kg=Decimal("20"),
            base_charge_per_parcel=Decimal("5"),
            minimum_charge_per_parcel=Decimal("0"),
            volumetric_divisor_cm3_per_kg=Decimal("0"),
            weight_increment_kg=Decimal("0.001"),
            min_weight_kg=Decimal("0.001"),
            max_weight_kg=Decimal("30"),
            max_length_cm=Decimal("150"),
            max_width_cm=Decimal("80"),
            max_height_cm=Decimal("80"),
            max_dimensions_sum_cm=Decimal("310"),
            min_declared_value=Decimal("0"),
            max_declared_value=Decimal("5000"),
            effective_at="2026-07-15T00:00:00+08:00",
            effective_until=None,
            evidence_id=rate_evidence.id,
            captured_by="operator-1",
            source_sheet="rates",
            source_range="A1:H2",
        )
    )
    intake.logistics = logistics
    intake.sourcing.logistics_profit_resolver = logistics.resolve_profit_cost
    inputs = replace(
        profit_inputs(),
        international_freight_cny_per_kg=Decimal("0"),
    )

    quote_ids = accepted_quote_ids(product, intake)
    result = intake.finalize(
        product_id=product.id,
        effective_at="2026-07-16T00:00:00+08:00",
        quote_evidence_ids=quote_ids,
        profit_inputs=inputs,
        assumption_content=b"approved non-logistics fee assumptions",
        assumption_filename="assumptions.txt",
        assumption_content_type="text/plain",
        created_by="operator-1",
        logistics_rate_card_id=card.id,
        logistics_currency_to_cny_rate=Decimal("1"),
        logistics_context=logistics_context,
    )

    assert len(logistics_store.calculations) == 3
    assert len(store.scenarios) == 3
    assert all(item.logistics_calculation_id for item in result["scenarios"])
    assert all(
        item.international_logistics_cny == Decimal("15.00")
        for item in result["scenarios"]
    )
    assert all(
        item.cost_evidence["international_logistics"] == rate_evidence.id
        for item in result["scenarios"]
    )
    with pytest.raises(ValueError, match="exact scope context"):
        intake.finalize(
            product_id=product.id,
            effective_at="2026-07-16T00:00:00+08:00",
            quote_evidence_ids=quote_ids,
            profit_inputs=inputs,
            assumption_content=b"must fail before capture",
            assumption_filename="assumptions.txt",
            assumption_content_type="text/plain",
            created_by="operator-1",
            logistics_rate_card_id=card.id,
            logistics_currency_to_cny_rate=Decimal("1"),
        )
    drifted_context = logistics.context(
        principal=logistics_context.principal,
        entity_scope={
            "status": "ready",
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "authority_sha256": "b" * 64,
        },
        store_ref="store-a",
        as_of=datetime(2026, 7, 16, 0, 0, tzinfo=UTC),
    )
    with pytest.raises(KeyError, match="Unknown logistics rate card"):
        intake.finalize(
            product_id=product.id,
            effective_at="2026-07-16T00:00:00+08:00",
            quote_evidence_ids=quote_ids,
            profit_inputs=inputs,
            assumption_content=b"must fail before capture",
            assumption_filename="assumptions.txt",
            assumption_content_type="text/plain",
            created_by="operator-1",
            logistics_rate_card_id=card.id,
            logistics_currency_to_cny_rate=Decimal("1"),
            logistics_context=drifted_context,
        )
    assert len(logistics_store.calculations) == 3
    assert len(store.scenarios) == 3


def test_supplier_comparison_rejects_duplicate_supplier_identity():
    product, _, intake = make_intake()
    payloads = offers()
    payloads[1].offer_data["supplier_ref"] = payloads[0].offer_data["supplier_ref"]
    quote_ids = accepted_quote_ids(product, intake, payloads)
    with pytest.raises(ValueError, match="distinct supplier"):
        intake.finalize(
            product_id=product.id,
            effective_at="2026-07-16T00:00:00+08:00",
            quote_evidence_ids=quote_ids,
            profit_inputs=profit_inputs(),
            assumption_content=b"assumptions",
            assumption_filename="assumptions.txt",
            assumption_content_type="text/plain",
            created_by="operator-1",
        )


def test_supplier_comparison_rejects_product_without_candidate_handoff_before_capture():
    product, store, intake = make_intake()
    intake.sourcing.repository.events.clear()

    with pytest.raises(ValueError, match="candidate or existing-listing"):
        payload = offers()[0]
        intake.capture_quote_source(
            product_id=product.id,
            document_kind="supplier_confirmed_quote",
            effective_at="2026-07-16T00:00:00+08:00",
            effective_until="2027-07-16T00:00:00+08:00",
            offer_data=payload.offer_data,
            content=payload.content,
            filename=payload.filename,
            content_type=payload.content_type,
            created_by="operator-1",
        )

    assert store.offers == {}
    assert len(intake.evidence.list()) == 1


def test_existing_listing_handoff_can_enter_governed_supplier_quote_intake():
    product, store, intake = make_intake()
    basis_id = intake.evidence.target_evidence_ids(
        target_type="product",
        target_id=product.id,
        relationship="candidate_basis",
    )[0]
    intake.sourcing.repository.events.clear()
    intake.sourcing.repository.append_event(
        "product.existing_listing_growth_workspace_created",
        product.id,
        {"offer_id": product.sku, "store_ref": "store-main"},
        actor_id="operator-1",
        source_evidence_id=basis_id,
    )
    intake.evidence.link(
        evidence_id=basis_id,
        target_type="product",
        target_id=product.id,
        relationship="existing_listing_basis",
        created_by="operator-1",
    )
    payload = offers()[0]

    record = intake.capture_quote_source(
        product_id=product.id,
        document_kind="supplier_confirmed_quote",
        offer_data=payload.offer_data,
        content=payload.content,
        filename=payload.filename,
        content_type=payload.content_type,
        effective_at="2026-07-16T00:00:00+08:00",
        effective_until="2027-07-16T00:00:00+08:00",
        created_by="operator-1",
    )

    assert record.metadata["product_id"] == product.id
    assert store.offers == {}


def test_supplier_response_preserves_rfq_package_lineage():
    product, store, intake = make_intake()
    rfq_record = intake.evidence.capture(
        content=b'{"contract_version":"supplier-rfq-package-v1"}',
        filename="supplier-rfq.json",
        content_type="application/json",
        source="supplier_rfq_package",
        source_ref=f"supplier-rfq://{product.id}/rfq-1",
        grade=EvidenceGrade.C,
        effective_at="2026-07-16T00:00:00+08:00",
        effective_until="2026-07-23T00:00:00+08:00",
        created_by="operator-1",
        metadata={"product_id": product.id},
    )

    class RfqPackages:
        def require_for_product(self, evidence_id, *, product_id):
            if evidence_id != rfq_record.id or product_id != product.id:
                raise ValueError("RFQ package does not belong to the selected product")
            return rfq_record

    dispatch_record = intake.evidence.capture(
        content=b"accepted supplier dispatch proof",
        filename="supplier-dispatch.png",
        content_type="image/png",
        source="supplier_rfq_dispatch",
        source_ref=f"supplier-rfq-dispatch://{rfq_record.id}/supplier-1/dispatch-1",
        grade=EvidenceGrade.B,
        effective_at="2026-07-16T01:00:00+08:00",
        effective_until=None,
        created_by="operator-1",
        metadata={
            "dispatch": {
                "rfq": {
                    "evidence_id": rfq_record.id,
                    "product_id": product.id,
                }
            }
        },
    )

    class RfqDispatches:
        def require_for_response(
            self,
            evidence_id,
            *,
            product_id,
            supplier_ref,
            supplier_platform,
            rfq_package_evidence_id,
        ):
            if (
                evidence_id != dispatch_record.id
                or product_id != product.id
                or supplier_ref != offers()[0].offer_data["supplier_ref"]
                or supplier_platform != "1688"
                or rfq_package_evidence_id
                not in {None, rfq_record.id}
            ):
                raise ValueError("Supplier dispatch does not match the response")
            return dispatch_record

    intake.rfq_packages = RfqPackages()
    intake.rfq_dispatches = RfqDispatches()
    payload = offers()[0]
    quote_record = intake.capture_quote_source(
        product_id=product.id,
        document_kind="supplier_confirmed_quote",
        offer_data=payload.offer_data,
        content=payload.content,
        filename=payload.filename,
        content_type=payload.content_type,
        effective_at="2026-07-16T00:00:00+08:00",
        effective_until="2027-07-16T00:00:00+08:00",
        created_by="operator-1",
        rfq_dispatch_evidence_id=dispatch_record.id,
    )

    assert quote_record.metadata["rfq_package_evidence_id"] == rfq_record.id
    assert (
        quote_record.metadata["rfq_dispatch_evidence_id"]
        == dispatch_record.id
    )
    assert intake.evidence.target_evidence_ids(
        target_type="evidence",
        target_id=quote_record.id,
        relationship="supplier_response_context_for",
    ) == [rfq_record.id]
    assert intake.evidence.target_evidence_ids(
        target_type="evidence",
        target_id=quote_record.id,
        relationship="supplier_response_to_dispatch",
    ) == [dispatch_record.id]
    assert store.offers == {}


def test_supplier_response_rejects_rfq_package_from_another_product():
    product, _, intake = make_intake()

    class RfqPackages:
        def require_for_product(self, _evidence_id, *, product_id):
            raise ValueError(
                f"RFQ package does not belong to the selected product {product_id}"
            )

    intake.rfq_packages = RfqPackages()
    payload = offers()[0]
    with pytest.raises(ValueError, match="does not belong"):
        intake.capture_quote_source(
            product_id=product.id,
            document_kind="supplier_confirmed_quote",
            offer_data=payload.offer_data,
            content=payload.content,
            filename=payload.filename,
            content_type=payload.content_type,
            effective_at="2026-07-16T00:00:00+08:00",
            effective_until="2027-07-16T00:00:00+08:00",
            created_by="operator-1",
            rfq_package_evidence_id="evd_another_product",
        )
    assert intake.quote_authority.evidence.list_by_source(
        "supplier_quote_source"
    ) == []


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


def test_supplier_comparison_preserves_unknown_cost_state_and_blocks_procurement():
    product, _, intake = make_intake()
    states = {key: "estimate" for key in REQUIRED_COST_EVIDENCE_KEYS}
    states["tax"] = "unknown"
    result = intake.finalize(
        product_id=product.id,
        effective_at="2026-07-16T00:00:00+08:00",
        quote_evidence_ids=accepted_quote_ids(product, intake),
        profit_inputs=profit_inputs(),
        cost_states=states,
        assumption_content=b"approved assumptions except unknown tax",
        assumption_filename="assumptions.txt",
        assumption_content_type="text/plain",
        created_by="operator-1",
    )

    assert result["comparison"]["ready_for_procurement_review"] is False
    assert all(item.cost_states["tax"] == "unknown" for item in result["scenarios"])
    assert all("tax" not in item.cost_evidence for item in result["scenarios"])
