from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from .evidence import EvidenceGrade
from .logistics import LogisticsScopeContext
from .sourcing import (
    PROFIT_TEMPLATE_ID,
    REQUIRED_COST_EVIDENCE_KEYS,
    ProfitInputs,
    SourcePlatform,
    SupplierOffer,
)


@dataclass(frozen=True, slots=True)
class OfferEvidencePayload:
    offer_data: dict
    content: bytes
    filename: str
    content_type: str


class SupplierComparisonIntakeService:
    def __init__(
        self,
        *,
        sourcing,
        evidence,
        quote_authority,
        logistics=None,
        rfq_packages=None,
        rfq_dispatches=None,
    ) -> None:
        self.sourcing = sourcing
        self.evidence = evidence
        self.quote_authority = quote_authority
        self.logistics = logistics
        self.rfq_packages = rfq_packages
        self.rfq_dispatches = rfq_dispatches

    def capture_quote_source(
        self,
        *,
        product_id: str,
        document_kind: str,
        offer_data: dict,
        content: bytes,
        filename: str,
        content_type: str,
        effective_at: str,
        effective_until: str | None,
        created_by: str,
        rfq_package_evidence_id: str | None = None,
        rfq_dispatch_evidence_id: str | None = None,
    ):
        self._require_sourcing_handoff(product_id)
        supplier_ref = str(offer_data.get("supplier_ref", "")).strip()
        supplier_platform = str(offer_data.get("platform", "")).strip().lower()
        rfq_record = None
        dispatch_record = None
        if rfq_dispatch_evidence_id:
            if self.rfq_dispatches is None:
                raise ValueError(
                    "Supplier RFQ dispatch workspace is not configured"
                )
            dispatch_record = self.rfq_dispatches.require_for_response(
                rfq_dispatch_evidence_id,
                product_id=product_id,
                supplier_ref=supplier_ref,
                supplier_platform=supplier_platform,
                rfq_package_evidence_id=rfq_package_evidence_id,
            )
            dispatch_rfq_id = dispatch_record.metadata["dispatch"]["rfq"][
                "evidence_id"
            ]
            rfq_package_evidence_id = (
                rfq_package_evidence_id or dispatch_rfq_id
            )
        if rfq_package_evidence_id:
            if self.rfq_packages is None:
                raise ValueError("Supplier RFQ package workspace is not configured")
            rfq_record = self.rfq_packages.require_for_product(
                rfq_package_evidence_id,
                product_id=product_id,
            )
        values = dict(offer_data)
        values["product_id"] = product_id
        record = self.quote_authority.capture(
            product_id=product_id,
            document_kind=document_kind,
            offer_data=values,
            content=content,
            filename=filename,
            content_type=content_type,
            effective_at=effective_at,
            effective_until=effective_until,
            created_by=created_by,
            rfq_package_evidence_id=(
                rfq_record.id if rfq_record is not None else None
            ),
            rfq_dispatch_evidence_id=(
                dispatch_record.id
                if dispatch_record is not None
                else None
            ),
        )
        if rfq_record is not None:
            self.evidence.link(
                evidence_id=rfq_record.id,
                target_type="evidence",
                target_id=record.id,
                relationship="supplier_response_context_for",
                created_by=created_by,
            )
        if dispatch_record is not None:
            self.evidence.link(
                evidence_id=dispatch_record.id,
                target_type="evidence",
                target_id=record.id,
                relationship="supplier_response_to_dispatch",
                created_by=created_by,
            )
        return record

    def ingest(
        self,
        *,
        product_id: str,
        effective_at: str,
        offers: list[OfferEvidencePayload],
        profit_inputs: ProfitInputs,
        cost_states: dict[str, str] | None = None,
        template_id: str = PROFIT_TEMPLATE_ID,
        assumption_content: bytes,
        assumption_filename: str,
        assumption_content_type: str,
        created_by: str,
        logistics_rate_card_id: str | None = None,
        logistics_currency_to_cny_rate: Decimal | None = None,
        logistics_fx_evidence_id: str | None = None,
    ) -> dict:
        raise ValueError(
            "Direct comparison intake is retired; capture and independently review "
            "three supplier quote sources before finalization"
        )

    def finalize(
        self,
        *,
        product_id: str,
        quote_evidence_ids: list[str],
        effective_at: str,
        profit_inputs: ProfitInputs,
        assumption_content: bytes,
        assumption_filename: str,
        assumption_content_type: str,
        created_by: str,
        cost_states: dict[str, str] | None = None,
        template_id: str = PROFIT_TEMPLATE_ID,
        logistics_rate_card_id: str | None = None,
        logistics_currency_to_cny_rate: Decimal | None = None,
        logistics_fx_evidence_id: str | None = None,
        logistics_context: LogisticsScopeContext | None = None,
    ) -> dict:
        self._require_sourcing_handoff(product_id)
        normalized_quote_ids = [item.strip() for item in quote_evidence_ids if item.strip()]
        if len(normalized_quote_ids) != 3 or len(set(normalized_quote_ids)) != 3:
            raise ValueError("Supplier comparison requires exactly three distinct quote evidence records")
        if logistics_fx_evidence_id and not logistics_rate_card_id:
            raise ValueError("FX evidence requires a selected logistics rate card")
        if logistics_context is not None and not logistics_rate_card_id:
            raise ValueError("Logistics scope context requires a selected rate card")
        selected_rate_card = None
        if logistics_rate_card_id:
            if self.logistics is None:
                raise ValueError("Logistics calculation workspace is not configured")
            if logistics_context is None:
                raise ValueError("Logistics rate card requires exact scope context")
            if logistics_context.principal.actor_id != created_by:
                raise PermissionError(
                    "Logistics scope identity must match comparison creator"
                )
            if profit_inputs.international_freight_cny_per_kg != 0:
                raise ValueError(
                    "Manual international freight must be zero when a logistics "
                    "rate card is selected"
                )
            if logistics_currency_to_cny_rate is None:
                raise ValueError("Logistics currency-to-CNY rate is required")
            selected_rate_card = self.logistics.get_rate_card(
                logistics_context,
                logistics_rate_card_id,
            )
            if selected_rate_card.declared_value_currency != "RUB":
                raise ValueError(
                    "Supplier comparison currently requires a RUB "
                    "declared-value logistics tier"
                )
        if not assumption_content:
            raise ValueError("Profit assumptions evidence cannot be empty")
        normalized_states = cost_states or {
            key: "estimate" for key in REQUIRED_COST_EVIDENCE_KEYS
        }
        if normalized_states.get("product_cost", "estimate") != "estimate":
            raise ValueError("Confirmed supplier quotes are estimates until invoice payment authority")
        if normalized_states.get("domestic_logistics", "estimate") != "estimate":
            raise ValueError("Quoted domestic logistics remains estimate until a final carrier bill")

        source_records = [
            self.quote_authority.require_accepted(evidence_id)
            for evidence_id in normalized_quote_ids
        ]
        if any(record.metadata["product_id"] != product_id for record in source_records):
            raise ValueError("All supplier quotes must belong to the selected candidate product")
        supplier_refs = {
            str(record.metadata.get("supplier_ref", "")).strip()
            for record in source_records
        }
        if "" in supplier_refs or len(supplier_refs) != 3:
            raise ValueError("Supplier comparison requires three distinct supplier references")
        selected_quantities = [
            self.quote_authority.offer_data(record)
            .get("attributes", {})
            .get("selected_quantity")
            for record in source_records
        ]
        comparison_quantity = None
        if any(value is not None for value in selected_quantities):
            if any(value is None for value in selected_quantities):
                raise ValueError(
                    "Tiered supplier comparison requires a selected quantity "
                    "for every quote"
                )
            normalized_quantities = {int(value) for value in selected_quantities}
            if len(normalized_quantities) != 1:
                raise ValueError(
                    "Tiered supplier comparison requires the same selected "
                    "quantity for all quotes"
                )
            comparison_quantity = normalized_quantities.pop()

        assumption_digest = hashlib.sha256(assumption_content).hexdigest()
        quote_set_digest = hashlib.sha256(
            "|".join(sorted(normalized_quote_ids)).encode()
        ).hexdigest()
        assumption = self.evidence.capture(
            content=assumption_content,
            filename=assumption_filename,
            content_type=assumption_content_type,
            source="supplier_comparison_assumptions",
            source_ref=(
                f"supplier-comparison://{product_id}/{quote_set_digest}"
                f"/assumptions/sha256/{assumption_digest}"
            ),
            grade=EvidenceGrade.B,
            effective_at=effective_at,
            effective_until=None,
            created_by=created_by,
            metadata={
                "product_id": product_id,
                "evidence_role": "profit_assumptions",
                "quote_evidence_ids": sorted(normalized_quote_ids),
                "fact_status": "estimate",
            },
        )

        captured_offers = []
        scenarios = []
        for record in source_records:
            raw = self.quote_authority.offer_data(record)
            raw.pop("product_id", None)
            raw.pop("evidence_ref", None)
            raw["platform"] = SourcePlatform(raw["platform"])
            for key in (
                "unit_price",
                "source_to_cny_rate",
                "weight_kg",
                "length_cm",
                "width_cm",
                "height_cm",
                "domestic_logistics_per_unit",
            ):
                raw[key] = Decimal(str(raw[key]))
            raw["min_order_quantity"] = int(raw["min_order_quantity"])
            offer = self.sourcing.capture_offer(
                SupplierOffer(product_id=product_id, evidence_ref=record.id, **raw)
            )
            self.evidence.link(
                evidence_id=record.id,
                target_type="supplier_offer",
                target_id=offer.id,
                relationship="source_for",
                created_by=created_by,
            )
            assumption_cost_evidence = {
                key: assumption.id
                for key in REQUIRED_COST_EVIDENCE_KEYS
                if key not in {"product_cost", "domestic_logistics"}
                and normalized_states.get(key, "unknown") != "unknown"
            }
            logistics_calculation_id = None
            if logistics_rate_card_id:
                if logistics_context is None or selected_rate_card is None:
                    raise RuntimeError("Logistics preflight invariant was not established")
                logistics_calculation = self.logistics.calculate(
                    logistics_context,
                    rate_card_id=logistics_rate_card_id,
                    physical_weight_kg=offer.weight_kg,
                    length_cm=offer.length_cm,
                    width_cm=offer.width_cm,
                    height_cm=offer.height_cm,
                    declared_value=profit_inputs.sale_price_rub,
                    quantity=1,
                    currency_to_cny_rate=logistics_currency_to_cny_rate,
                    idempotency_key=(
                        f"comparison:{product_id}:{offer.id}:{assumption_digest}"
                    ),
                    calculated_by=created_by,
                    evaluated_at=effective_at,
                    fx_evidence_id=logistics_fx_evidence_id,
                )
                logistics_calculation_id = logistics_calculation.id
            scenario = self.sourcing.calculate_profit(
                offer.id,
                profit_inputs,
                [assumption.id],
                assumption_cost_evidence,
                normalized_states,
                template_id or PROFIT_TEMPLATE_ID,
                logistics_calculation_id,
                logistics_context,
            )
            for evidence_id in scenario.evidence:
                self.evidence.link(
                    evidence_id=evidence_id,
                    target_type="profit_scenario",
                    target_id=scenario.id,
                    relationship="supports",
                    created_by=created_by,
                )
            captured_offers.append(offer)
            scenarios.append(scenario)
        comparison = self.sourcing.compare_product_offers(product_id)
        if comparison_quantity is not None:
            comparison["comparison_quantity"] = comparison_quantity
        return {
            "offers": captured_offers,
            "scenarios": scenarios,
            "evidence": [assumption, *source_records],
            "comparison": comparison,
            "authority": {
                "quote_evidence_ids": normalized_quote_ids,
                "all_independently_accepted": True,
                "product_cost_state": "estimate",
                "automatic_procurement": False,
                "automatic_listing": False,
            },
        }

    def _require_sourcing_handoff(self, product_id: str) -> None:
        repository = self.sourcing.repository
        repository.get_product(product_id)
        events = repository.events_after(0)
        allowed_handoffs = (
            (
                "product.candidate_sourcing_workspace_created",
                "candidate_basis",
            ),
            (
                "product.existing_listing_growth_workspace_created",
                "existing_listing_basis",
            ),
        )
        for event_type, relationship in allowed_handoffs:
            if not any(
                event["type"] == event_type
                and event["aggregate_id"] == product_id
                for event in events
            ):
                continue
            evidence_ids = self.evidence.target_evidence_ids(
                target_type="product",
                target_id=product_id,
                relationship=relationship,
            )
            if not evidence_ids:
                raise ValueError(
                    "Supplier comparison requires sourcing handoff basis evidence"
                )
            self.evidence.require_valid(evidence_ids)
            return
        raise ValueError(
            "Supplier comparison requires a candidate or existing-listing sourcing handoff"
        )
