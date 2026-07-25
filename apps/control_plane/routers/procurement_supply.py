from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..api_contracts import (
    LogisticsCalculationInput,
    LogisticsRateCardInput,
    ProcurementCandidateInput,
    ProfitScenarioInput,
    SampleOrderInput,
    SupplierOfferInput,
    current_principal,
    ensure_role,
    run,
)
from ..evidence import EvidenceGrade
from ..logistics import LogisticsRateCard
from ..runtime import runtime
from ..security import Principal
from ..sourcing import ProfitInputs, SupplierOffer, profit_template_contract
from ..sourcing_intake import OfferEvidencePayload

router = APIRouter()


@router.post("/v1/sourcing/offers", status_code=201)
def capture_supplier_offer(body: SupplierOfferInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "admin")
    offer = SupplierOffer(**body.model_dump())

    def capture():
        result = runtime.sourcing.capture_offer(offer)
        runtime.evidence.link(
            evidence_id=result.evidence_ref,
            target_type="supplier_offer",
            target_id=result.id,
            relationship="source_for",
            created_by=principal.actor_id,
        )
        return result

    return run(capture)


@router.get("/v1/sourcing/offers")
def list_supplier_offers(limit: int = 100):
    return run(lambda: runtime.sourcing_store.list_offers(min(max(limit, 1), 500)))


@router.post("/v1/sourcing/comparison-intake", status_code=201)
async def capture_supplier_comparison(
    product_id: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    offers_json: Annotated[str, Form()],
    profit_inputs_json: Annotated[str, Form()],
    offer_evidence_1: Annotated[UploadFile, File()],
    offer_evidence_2: Annotated[UploadFile, File()],
    offer_evidence_3: Annotated[UploadFile, File()],
    assumption_evidence: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    logistics_rate_card_id: Annotated[str, Form()] = "",
    logistics_currency_to_cny_rate: Annotated[Decimal, Form()] = Decimal("1"),
    logistics_fx_evidence_id: Annotated[str, Form()] = "",
):
    ensure_role(principal, "operator", "reviewer", "admin")
    try:
        raw_offers = json.loads(offers_json)
        raw_inputs = json.loads(profit_inputs_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Offer and profit input payloads must be valid JSON") from exc
    if not isinstance(raw_offers, list) or len(raw_offers) != 3 or (not isinstance(raw_inputs, dict)):
        raise HTTPException(status_code=422, detail="Exactly three offers and one profit input object are required")
    offer_values = []
    for raw_offer in raw_offers:
        if not isinstance(raw_offer, dict):
            raise HTTPException(status_code=422, detail="Every supplier offer must be an object")
        validated = SupplierOfferInput(**raw_offer, product_id=product_id, evidence_ref="pending-capture").model_dump()
        validated.pop("product_id")
        validated.pop("evidence_ref")
        offer_values.append(validated)
    validated_inputs = ProfitScenarioInput(
        **raw_inputs, offer_id="pending-capture", evidence=["pending-capture"]
    ).model_dump()
    validated_inputs.pop("offer_id")
    validated_inputs.pop("evidence")
    validated_inputs.pop("cost_evidence")
    template_id = validated_inputs.pop("template_id")
    cost_states = validated_inputs.pop("cost_states")
    validated_inputs.pop("logistics_calculation_id")
    uploads = [offer_evidence_1, offer_evidence_2, offer_evidence_3]
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    payloads = []
    for values, upload in zip(offer_values, uploads, strict=True):
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail="Supplier offer evidence exceeds size limit")
        payloads.append(
            OfferEvidencePayload(
                offer_data=values,
                content=content,
                filename=upload.filename or "supplier-offer.bin",
                content_type=upload.content_type or "application/octet-stream",
            )
        )
    assumption_content = await assumption_evidence.read(max_bytes + 1)
    if len(assumption_content) > max_bytes:
        raise HTTPException(status_code=413, detail="Profit assumption evidence exceeds size limit")
    return run(
        lambda: runtime.sourcing_intake.ingest(
            product_id=product_id,
            effective_at=effective_at,
            offers=payloads,
            profit_inputs=ProfitInputs(**validated_inputs),
            cost_states=cost_states,
            template_id=template_id,
            assumption_content=assumption_content,
            assumption_filename=assumption_evidence.filename or "profit-assumptions.bin",
            assumption_content_type=assumption_evidence.content_type or "application/octet-stream",
            created_by=principal.actor_id,
            logistics_rate_card_id=logistics_rate_card_id.strip() or None,
            logistics_currency_to_cny_rate=(
                logistics_currency_to_cny_rate if logistics_rate_card_id.strip() else None
            ),
            logistics_fx_evidence_id=logistics_fx_evidence_id.strip() or None,
        )
    )


@router.get("/v1/sourcing/comparisons/{product_id}")
def compare_supplier_offers(product_id: str):
    return run(lambda: runtime.sourcing.compare_product_offers(product_id))


@router.post("/v1/sourcing/procurement-candidates", status_code=201)
def request_procurement_candidate(
    body: ProcurementCandidateInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")

    def request():
        comparison = runtime.sourcing.compare_product_offers(body.product_id)
        if not comparison["ready_for_procurement_review"]:
            raise ValueError("Three evidence-backed supplier offers and CM3 scenarios are required")
        selected = next(
            (
                item
                for item in comparison["rows"]
                if item["offer"].id == body.offer_id
                and item["scenario"] is not None
                and (item["scenario"].id == body.scenario_id)
            ),
            None,
        )
        if selected is None:
            raise ValueError("Selected offer and scenario are not part of this product comparison")
        if selected["scenario"].cm3_cny <= 0:
            raise ValueError("Procurement candidate requires positive expected CM3")
        if not selected["scenario"].cost_complete:
            raise ValueError("Procurement candidate requires complete, classified cost evidence")
        runtime.sourcing.require_release_ready(selected["scenario"])
        if body.quantity < selected["offer"].min_order_quantity:
            raise ValueError("Procurement quantity is below supplier MOQ")
        if not runtime.commerce.product_readiness(body.product_id)["ready_for_validation"]:
            raise ValueError("All three Passports must be approved before procurement review")
        payload = {
            **body.model_dump(),
            "supplier_ref": selected["offer"].supplier_ref,
            "expected_cm3_cny": str(selected["scenario"].cm3_cny),
            "expected_cm3_rate": str(selected["scenario"].cm3_rate),
            "cost_breakdown_cny": selected["scenario"].cost_breakdown(),
            "cost_evidence": selected["scenario"].cost_evidence,
            "cost_states": selected["scenario"].cost_states,
            "profit_template_id": selected["scenario"].template_id,
            "comparison_offer_ids": [item["offer"].id for item in comparison["rows"]],
            "evidence": selected["scenario"].evidence,
        }
        return runtime.commerce.request_approval(
            action="procurement.place_order",
            resource_type="profit_scenario",
            resource_id=body.scenario_id,
            requested_by=principal.actor_id,
            payload=payload,
        )

    return run(request)


@router.post("/v1/procurement/sample-orders", status_code=201)
def create_sample_purchase_order(body: SampleOrderInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.procurement.create_sample_order(body.approval_id, created_by=principal.actor_id))


@router.get("/v1/procurement/sample-orders")
def list_sample_purchase_orders(limit: int = 100):
    return run(lambda: runtime.procurement.list_orders(limit))


@router.get("/v1/procurement/sample-orders/{order_id}")
def get_sample_purchase_order(order_id: str):
    return run(lambda: runtime.procurement.get_order(order_id))


@router.post("/v1/procurement/sample-orders/{order_id}/events", status_code=201)
async def record_sample_procurement_event(
    order_id: str,
    event_type: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    facts_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    try:
        event_facts = json.loads(facts_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="facts_json must be valid JSON") from exc
    if not isinstance(event_facts, dict):
        raise HTTPException(status_code=422, detail="facts_json must be a JSON object")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Event evidence exceeds {max_bytes} bytes")
    digest = hashlib.sha256(content).hexdigest()

    def capture_and_record():
        record = runtime.evidence.capture(
            content=content,
            filename=file.filename or f"{event_type}-evidence.bin",
            content_type=file.content_type or "application/octet-stream",
            source="sample_procurement",
            source_ref=f"sample-procurement://{order_id}/{event_type}/sha256/{digest}",
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=None,
            created_by=principal.actor_id,
            metadata={"sample_order_id": order_id, "event_type": event_type},
        )
        return runtime.procurement.record_event(
            order_id,
            event_type=event_type,
            effective_at=effective_at,
            evidence_id=record.id,
            facts=event_facts,
            created_by=principal.actor_id,
        )

    return run(capture_and_record)


@router.get("/v1/procurement/suppliers/performance")
def supplier_performance():
    return run(runtime.procurement.supplier_performance)


@router.get("/v1/procurement/sample-orders/{order_id}/backup-options")
def sample_order_backup_options(order_id: str):
    return run(lambda: runtime.procurement.backup_options(order_id))


@router.post("/v1/sourcing/profit-scenarios", status_code=201)
def calculate_sourcing_profit(body: ProfitScenarioInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "admin")
    values = body.model_dump()
    offer_id = values.pop("offer_id")
    assumption_evidence = values.pop("evidence")
    cost_evidence = values.pop("cost_evidence")
    template_id = values.pop("template_id")
    cost_states = values.pop("cost_states")
    logistics_calculation_id = values.pop("logistics_calculation_id")

    def calculate():
        result = runtime.sourcing.calculate_profit(
            offer_id,
            ProfitInputs(**values),
            assumption_evidence,
            cost_evidence,
            cost_states,
            template_id,
            logistics_calculation_id,
        )
        for evidence_id in result.evidence:
            runtime.evidence.link(
                evidence_id=evidence_id,
                target_type="profit_scenario",
                target_id=result.id,
                relationship="supports",
                created_by=principal.actor_id,
            )
        return result

    return run(calculate)


@router.get("/v1/sourcing/profit-template")
def get_sourcing_profit_template():
    return profit_template_contract()


@router.get("/v1/sourcing/profit-scenarios/{scenario_id}/explain")
def explain_sourcing_profit_scenario(scenario_id: str):
    return run(lambda: runtime.sourcing_store.get_scenario(scenario_id).explain())


@router.post("/v1/logistics/rate-cards", status_code=201)
def capture_logistics_rate_card(
    body: LogisticsRateCardInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    values = body.model_dump()
    return run(
        lambda: runtime.logistics.capture_rate_card(
            LogisticsRateCard(**values, captured_by=principal.actor_id)
        )
    )


@router.get("/v1/logistics/rate-cards")
def list_logistics_rate_cards(limit: int = 100):
    return run(lambda: runtime.logistics_store.list_rate_cards(min(max(limit, 1), 500)))


@router.post("/v1/logistics/calculations", status_code=201)
def calculate_logistics_cost(
    body: LogisticsCalculationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: runtime.logistics.calculate(
            **body.model_dump(),
            calculated_by=principal.actor_id,
        )
    )


@router.get("/v1/logistics/calculations")
def list_logistics_calculations(limit: int = 100):
    return run(
        lambda: runtime.logistics_store.list_calculations(min(max(limit, 1), 500))
    )


@router.get("/v1/logistics/calculations/{calculation_id}/decision-support")
def logistics_decision_support(calculation_id: str):
    return run(lambda: runtime.logistics.decision_support(calculation_id))
