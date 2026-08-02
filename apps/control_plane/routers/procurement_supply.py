from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)

from ..api_contracts import (
    LogisticsCalculationInput,
    LogisticsRateCardInput,
    ProcurementCandidateInput,
    ProfitScenarioInput,
    SampleOrderInput,
    SupplierOfferInput,
    SupplierQuoteAuthorityReviewInput,
    SupplierRfqDispatchAuthorityReviewInput,
    SupplierRfqDispatchInput,
    SupplierRfqPackageInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..evidence import EvidenceGrade
from ..logistics import LogisticsRateCard
from ..runtime import runtime
from ..security import Principal
from ..sourcing import ProfitInputs, SupplierOffer, profit_template_contract

router = APIRouter()


def _cutoff(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="as_of must be an ISO-8601 timestamp",
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(
            status_code=422,
            detail="as_of must include a timezone",
        )
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC):
        raise HTTPException(
            status_code=422,
            detail="as_of cannot be in the future",
        )
    return parsed


@router.get("/v1/procurement/workspace")
def procurement_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    query: str | None = None,
    stage: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    ensure_store_scope(principal, store_ref)
    cutoff = _cutoff(as_of)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.scoped_procurement_receiving.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff.isoformat(),
            query=query,
            stage=stage,
            page_size=page_size,
            cursor=cursor,
        )
    )


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


@router.post("/v1/sourcing/rfq-packages", status_code=201)
def create_supplier_rfq_package(
    body: SupplierRfqPackageInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    ensure_store_scope(principal, body.store_ref)
    cutoff = datetime.now(UTC)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=body.store_ref,
        as_of=cutoff,
    )

    def create():
        runtime.scoped_marketplace_catalog.require_current_item(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            as_of=cutoff,
            offer_id=body.offer_id,
            expected_item_hash=body.expected_item_hash,
        )
        result = runtime.supplier_rfq.create(
            **body.model_dump(),
            created_by=principal.actor_id,
        )
        return {
            **result,
            "evidence": asdict(result["evidence"]),
        }

    return run(create)


@router.get("/v1/sourcing/rfq-packages")
def list_supplier_rfq_packages(
    principal: Annotated[Principal, Depends(current_principal)],
    product_id: str | None = None,
    limit: int = 100,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(
        lambda: [
            {**item, "evidence": asdict(item["evidence"])}
            for item in runtime.supplier_rfq.list(
                product_id=product_id,
                limit=min(max(limit, 1), 500),
            )
        ]
    )


@router.get("/v1/sourcing/rfq-packages/{evidence_id}")
def get_supplier_rfq_package(
    evidence_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")

    def get():
        result = runtime.supplier_rfq.get(evidence_id)
        return {
            **result,
            "evidence": asdict(result["evidence"]),
        }

    return run(get)


@router.post("/v1/sourcing/rfq-dispatches", status_code=201)
async def capture_supplier_rfq_dispatch(
    rfq_package_evidence_id: Annotated[str, Form()],
    supplier_ref: Annotated[str, Form()],
    supplier_platform: Annotated[str, Form()],
    supplier_locator: Annotated[str, Form()],
    conversation_ref: Annotated[str, Form()],
    sent_at: Annotated[str, Form()],
    sent_message_text: Annotated[str, Form()],
    idempotency_key: Annotated[str, Form()],
    confirmed: Annotated[bool, Form()],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    body = SupplierRfqDispatchInput(
        rfq_package_evidence_id=rfq_package_evidence_id,
        supplier_ref=supplier_ref,
        supplier_platform=supplier_platform,
        supplier_locator=supplier_locator,
        conversation_ref=conversation_ref,
        sent_at=sent_at,
        sent_message_text=sent_message_text,
        idempotency_key=idempotency_key,
        confirmed=confirmed,
    )
    max_bytes = int(
        os.getenv(
            "KJDS_EVIDENCE_MAX_BYTES",
            str(10 * 1024 * 1024),
        )
    )
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail="Supplier RFQ dispatch proof exceeds size limit",
        )

    def capture():
        result = runtime.supplier_rfq_dispatch.capture(
            **body.model_dump(),
            content=content,
            filename=file.filename or "supplier-rfq-dispatch.bin",
            content_type=file.content_type or "application/octet-stream",
            created_by=principal.actor_id,
        )
        return {
            **result,
            "evidence": asdict(result["evidence"]),
            **(
                {"review": asdict(result["review"])}
                if result.get("review")
                else {}
            ),
        }

    return run(capture)


@router.get("/v1/sourcing/rfq-dispatches")
def list_supplier_rfq_dispatches(
    principal: Annotated[Principal, Depends(current_principal)],
    product_id: str | None = None,
    rfq_package_evidence_id: str | None = None,
    limit: int = 100,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    return run(
        lambda: [
            {**item, "evidence": asdict(item["evidence"])}
            for item in runtime.supplier_rfq_dispatch.list(
                product_id=product_id,
                rfq_package_evidence_id=rfq_package_evidence_id,
                limit=min(max(limit, 1), 500),
            )
        ]
    )


@router.get("/v1/sourcing/rfq-dispatches/{evidence_id}")
def get_supplier_rfq_dispatch(
    evidence_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )

    def get():
        result = runtime.supplier_rfq_dispatch.status(evidence_id)
        return {
            **result,
            "evidence": asdict(result["evidence"]),
        }

    return run(get)


@router.post(
    "/v1/sourcing/rfq-dispatches/{evidence_id}/authority-review",
    status_code=201,
)
def review_supplier_rfq_dispatch(
    evidence_id: str,
    body: SupplierRfqDispatchAuthorityReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = runtime.supplier_rfq_dispatch.review(
            evidence_id=evidence_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
        return {
            **result,
            "evidence": asdict(result["evidence"]),
            "review": asdict(result["review"]),
            **(
                {"lineage": asdict(result["lineage"])}
                if result.get("lineage")
                else {}
            ),
        }

    return run(review)


@router.post("/v1/sourcing/quote-evidence", status_code=201)
async def capture_supplier_quote_evidence(
    product_id: Annotated[str, Form()],
    document_kind: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    effective_until: Annotated[str, Form()],
    offer_json: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    rfq_package_evidence_id: Annotated[str, Form()] = "",
    rfq_dispatch_evidence_id: Annotated[str, Form()] = "",
):
    ensure_role(principal, "operator", "reviewer", "admin")
    try:
        raw_offer = json.loads(offer_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="offer_json must be valid JSON") from exc
    if not isinstance(raw_offer, dict):
        raise HTTPException(status_code=422, detail="offer_json must be an object")
    validated = SupplierOfferInput(
        **raw_offer,
        product_id=product_id,
        evidence_ref="pending-capture",
    ).model_dump()
    validated.pop("evidence_ref")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail="Supplier quote evidence exceeds size limit")
    return run(
        lambda: runtime.sourcing_intake.capture_quote_source(
            product_id=product_id,
            document_kind=document_kind,
            offer_data=validated,
            content=content,
            filename=file.filename or "supplier-quote.bin",
            content_type=file.content_type or "application/octet-stream",
            effective_at=effective_at,
            effective_until=effective_until.strip() or None,
            created_by=principal.actor_id,
            rfq_package_evidence_id=rfq_package_evidence_id.strip() or None,
            rfq_dispatch_evidence_id=(
                rfq_dispatch_evidence_id.strip() or None
            ),
        )
    )


@router.get("/v1/sourcing/quote-evidence")
def list_supplier_quote_evidence(
    principal: Annotated[Principal, Depends(current_principal)],
    product_id: str | None = None,
    limit: int = 100,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")

    def list_records():
        return [
            {**item, "evidence": asdict(item["evidence"])}
            for item in runtime.supplier_quote_authority.list(
                product_id=product_id,
                limit=min(max(limit, 1), 500),
            )
        ]

    return run(list_records)


@router.get("/v1/sourcing/quote-evidence/{evidence_id}/authority-review")
def supplier_quote_authority_status(
    evidence_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")

    def status():
        result = runtime.supplier_quote_authority.status(evidence_id)
        return {**result, "evidence": asdict(result["evidence"])}

    return run(status)


@router.post(
    "/v1/sourcing/quote-evidence/{evidence_id}/authority-review",
    status_code=201,
)
def review_supplier_quote_authority(
    evidence_id: str,
    body: SupplierQuoteAuthorityReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = runtime.supplier_quote_authority.review(
            evidence_id=evidence_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
        return {
            "evidence": asdict(result["evidence"]),
            "review": asdict(result["review"]),
            "lineage": (
                asdict(result["lineage"]) if result.get("lineage") else None
            ),
            "idempotent": result["idempotent"],
        }

    return run(review)


@router.post("/v1/sourcing/comparison-intake", status_code=201)
async def capture_supplier_comparison(
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    raise HTTPException(
        status_code=409,
        detail=(
            "Direct comparison intake is retired. Capture three quote evidence "
            "records, obtain independent reviews, then call comparison-finalize."
        ),
    )


@router.post("/v1/sourcing/comparison-finalize", status_code=201)
async def finalize_supplier_comparison(
    product_id: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    quote_evidence_ids_json: Annotated[str, Form()],
    profit_inputs_json: Annotated[str, Form()],
    assumption_evidence: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
    logistics_rate_card_id: Annotated[str, Form()] = "",
    logistics_currency_to_cny_rate: Annotated[Decimal, Form()] = Decimal("1"),
    logistics_fx_evidence_id: Annotated[str, Form()] = "",
):
    ensure_role(principal, "operator", "reviewer", "admin")
    try:
        quote_evidence_ids = json.loads(quote_evidence_ids_json)
        raw_inputs = json.loads(profit_inputs_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="Quote evidence and profit input payloads must be valid JSON",
        ) from exc
    if (
        not isinstance(quote_evidence_ids, list)
        or len(quote_evidence_ids) != 3
        or not all(isinstance(item, str) for item in quote_evidence_ids)
        or not isinstance(raw_inputs, dict)
    ):
        raise HTTPException(
            status_code=422,
            detail="Exactly three quote evidence IDs and one profit input object are required",
        )
    validated_inputs = ProfitScenarioInput(
        **raw_inputs,
        offer_id="pending-capture",
        evidence=["pending-capture"],
    ).model_dump()
    validated_inputs.pop("offer_id")
    validated_inputs.pop("evidence")
    validated_inputs.pop("cost_evidence")
    template_id = validated_inputs.pop("template_id")
    cost_states = validated_inputs.pop("cost_states")
    validated_inputs.pop("logistics_calculation_id")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    assumption_content = await assumption_evidence.read(max_bytes + 1)
    if len(assumption_content) > max_bytes:
        raise HTTPException(status_code=413, detail="Profit assumption evidence exceeds size limit")
    return run(
        lambda: runtime.sourcing_intake.finalize(
            product_id=product_id,
            quote_evidence_ids=quote_evidence_ids,
            effective_at=effective_at,
            profit_inputs=ProfitInputs(**validated_inputs),
            cost_states=cost_states,
            template_id=template_id,
            assumption_content=assumption_content,
            assumption_filename=assumption_evidence.filename
            or "profit-assumptions.bin",
            assumption_content_type=assumption_evidence.content_type
            or "application/octet-stream",
            created_by=principal.actor_id,
            logistics_rate_card_id=logistics_rate_card_id.strip() or None,
            logistics_currency_to_cny_rate=(
                logistics_currency_to_cny_rate
                if logistics_rate_card_id.strip()
                else None
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
