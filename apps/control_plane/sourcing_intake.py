from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from .evidence import EvidenceGrade
from .sourcing import PROFIT_TEMPLATE_ID, REQUIRED_COST_EVIDENCE_KEYS, ProfitInputs, SupplierOffer


@dataclass(frozen=True, slots=True)
class OfferEvidencePayload:
    offer_data: dict
    content: bytes
    filename: str
    content_type: str


class SupplierComparisonIntakeService:
    def __init__(self, *, sourcing, evidence, logistics=None) -> None:
        self.sourcing = sourcing
        self.evidence = evidence
        self.logistics = logistics

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
        self._require_candidate_handoff(product_id)
        if len(offers) != 3:
            raise ValueError("Supplier comparison intake requires exactly three offers")
        if logistics_fx_evidence_id and not logistics_rate_card_id:
            raise ValueError("FX evidence requires a selected logistics rate card")
        supplier_refs = {str(item.offer_data.get("supplier_ref", "")).strip() for item in offers}
        if "" in supplier_refs or len(supplier_refs) != 3:
            raise ValueError("Supplier comparison requires three distinct supplier references")
        if not assumption_content:
            raise ValueError("Profit assumptions evidence cannot be empty")

        assumption_digest = hashlib.sha256(assumption_content).hexdigest()
        assumption = self.evidence.capture(
            content=assumption_content,
            filename=assumption_filename,
            content_type=assumption_content_type,
            source="supplier_comparison_intake",
            source_ref=f"supplier-comparison://{product_id}/assumptions/sha256/{assumption_digest}",
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=None,
            created_by=created_by,
            metadata={"product_id": product_id, "evidence_role": "profit_assumptions"},
        )

        captured_offers = []
        scenarios = []
        evidence_records = [assumption]
        for payload in offers:
            if not payload.content:
                raise ValueError("Supplier offer evidence cannot be empty")
            digest = hashlib.sha256(payload.content).hexdigest()
            external_id = str(payload.offer_data["external_id"])
            record = self.evidence.capture(
                content=payload.content,
                filename=payload.filename,
                content_type=payload.content_type,
                source="supplier_comparison_intake",
                source_ref=f"supplier-comparison://{product_id}/{external_id}/sha256/{digest}",
                grade=EvidenceGrade.A,
                effective_at=effective_at,
                effective_until=None,
                created_by=created_by,
                metadata={"product_id": product_id, "supplier_ref": payload.offer_data["supplier_ref"]},
            )
            offer = self.sourcing.capture_offer(
                SupplierOffer(product_id=product_id, evidence_ref=record.id, **payload.offer_data)
            )
            self.evidence.link(
                evidence_id=record.id,
                target_type="supplier_offer",
                target_id=offer.id,
                relationship="source_for",
                created_by=created_by,
            )
            normalized_states = cost_states or {
                key: "estimate" for key in REQUIRED_COST_EVIDENCE_KEYS
            }
            assumption_cost_evidence = {
                key: assumption.id
                for key in REQUIRED_COST_EVIDENCE_KEYS
                if key not in {"product_cost", "domestic_logistics"}
                and normalized_states.get(key, "unknown") != "unknown"
            }
            logistics_calculation_id = None
            if logistics_rate_card_id:
                if self.logistics is None:
                    raise ValueError("Logistics calculation workspace is not configured")
                if profit_inputs.international_freight_cny_per_kg != 0:
                    raise ValueError(
                        "Manual international freight must be zero when a logistics rate card is selected"
                    )
                if logistics_currency_to_cny_rate is None:
                    raise ValueError("Logistics currency-to-CNY rate is required")
                selected_rate_card = self.logistics.get_rate_card(
                    logistics_rate_card_id
                )
                if selected_rate_card.declared_value_currency != "RUB":
                    raise ValueError(
                        "Supplier comparison currently requires a RUB declared-value logistics tier"
                    )
                logistics_calculation = self.logistics.calculate(
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
            evidence_records.append(record)
        return {
            "offers": captured_offers,
            "scenarios": scenarios,
            "evidence": evidence_records,
            "comparison": self.sourcing.compare_product_offers(product_id),
        }

    def _require_candidate_handoff(self, product_id: str) -> None:
        repository = self.sourcing.repository
        repository.get_product(product_id)
        handoff_recorded = any(
            event["type"] == "product.candidate_sourcing_workspace_created"
            and event["aggregate_id"] == product_id
            for event in repository.events_after(0)
        )
        if not handoff_recorded:
            raise ValueError("Supplier comparison requires the candidate sourcing handoff")
        evidence_ids = self.evidence.target_evidence_ids(
            target_type="product",
            target_id=product_id,
            relationship="candidate_basis",
        )
        if not evidence_ids:
            raise ValueError("Supplier comparison requires candidate basis evidence")
        self.evidence.require_valid(evidence_ids)
