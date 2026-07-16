from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .evidence import EvidenceGrade
from .sourcing import ProfitInputs, SupplierOffer


@dataclass(frozen=True, slots=True)
class OfferEvidencePayload:
    offer_data: dict
    content: bytes
    filename: str
    content_type: str


class SupplierComparisonIntakeService:
    def __init__(self, *, sourcing, evidence) -> None:
        self.sourcing = sourcing
        self.evidence = evidence

    def ingest(
        self,
        *,
        product_id: str,
        effective_at: str,
        offers: list[OfferEvidencePayload],
        profit_inputs: ProfitInputs,
        assumption_content: bytes,
        assumption_filename: str,
        assumption_content_type: str,
        created_by: str,
    ) -> dict:
        if len(offers) != 3:
            raise ValueError("Supplier comparison intake requires exactly three offers")
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
            scenario = self.sourcing.calculate_profit(offer.id, profit_inputs, [assumption.id])
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
