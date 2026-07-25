from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..api_contracts import (
    AssetAttachInput,
    AssetReviewInput,
    CandidateEvidenceAuthorityReviewInput,
    CandidateResearchInput,
    CandidateResearchSubmissionInput,
    CandidateSourcingHandoffInput,
    ChargeInput,
    ContentBriefInput,
    CostEvidenceAuthorityReviewInput,
    ExistingOzonListingBindingInput,
    MarketplaceGrowthSnapshotInput,
    MarketplaceLatestGrowthPlanInput,
    MarketplacePortfolioGrowthPlanInput,
    ObservationInput,
    OpportunityInput,
    OrderInput,
    OzonCatalogEvidenceImportInput,
    PassportInput,
    PassportReviewInput,
    ProductInput,
    current_principal,
    ensure_role,
    run,
)
from ..cost_evidence_review import ACTUAL_COST_AUTHORITIES, ACTUAL_COST_AUTHORITY_LABELS
from ..domain import PassportType
from ..evidence import EvidenceGrade
from ..intake import PassportEvidencePayload
from ..runtime import runtime
from ..security import Principal
from ..sourcing import PROFIT_TEMPLATE_FIELDS

router = APIRouter()


@router.post("/v1/products", status_code=201)
def create_product(body: ProductInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.commerce.create_product(**body.model_dump()))


@router.post("/v1/intake/sku-episodes", status_code=201)
async def intake_sku_episode(
    sku: Annotated[str, Form()],
    name: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    product_facts_json: Annotated[str, Form()],
    compliance_facts_json: Annotated[str, Form()],
    quality_facts_json: Annotated[str, Form()],
    product_evidence: Annotated[UploadFile, File()],
    compliance_evidence: Annotated[UploadFile, File()],
    quality_evidence: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    facts_by_kind: dict[PassportType, dict] = {}
    for kind, raw in (
        (PassportType.PRODUCT, product_facts_json),
        (PassportType.COMPLIANCE, compliance_facts_json),
        (PassportType.QUALITY, quality_facts_json),
    ):
        try:
            facts = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"{kind.value}_facts_json must be valid JSON") from exc
        if not isinstance(facts, dict):
            raise HTTPException(status_code=422, detail=f"{kind.value}_facts_json must be a JSON object")
        facts_by_kind[kind] = facts
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    uploads = {
        PassportType.PRODUCT: product_evidence,
        PassportType.COMPLIANCE: compliance_evidence,
        PassportType.QUALITY: quality_evidence,
    }
    payloads = []
    for kind, upload in uploads.items():
        content = await upload.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise HTTPException(status_code=413, detail=f"{kind.value} evidence exceeds {max_bytes} bytes")
        payloads.append(
            PassportEvidencePayload(
                kind=kind,
                facts=facts_by_kind[kind],
                content=content,
                filename=upload.filename or f"{kind.value}-evidence.bin",
                content_type=upload.content_type or "application/octet-stream",
            )
        )
    return run(
        lambda: runtime.intake.ingest(
            sku=sku, name=name, effective_at=effective_at, payloads=payloads, created_by=principal.actor_id
        )
    )


@router.get("/v1/products")
def list_products():
    return run(runtime.commerce.list_products)


@router.get("/v1/products/{product_id}/readiness")
def product_readiness(product_id: str):
    return run(lambda: runtime.commerce.product_readiness(product_id))


@router.post("/v1/products/{product_id}/media-evidence", status_code=201)
async def capture_product_media(
    product_id: str,
    variant_id: Annotated[str, Form()],
    asset_role: Annotated[str, Form()],
    source_kind: Annotated[str, Form()],
    source_ref: Annotated[str, Form()],
    effective_at: Annotated[str, Form()],
    image: Annotated[UploadFile, File()],
    rights_file: Annotated[UploadFile, File()],
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    image_content = await image.read(max_bytes + 1)
    rights_content = await rights_file.read(max_bytes + 1)
    if len(image_content) > max_bytes or len(rights_content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Product media file exceeds {max_bytes} bytes")
    return run(
        lambda: runtime.product_media.ingest(
            product_id=product_id,
            variant_id=variant_id,
            asset_role=asset_role,
            source_kind=source_kind,
            source_ref=source_ref,
            effective_at=effective_at,
            image_content=image_content,
            image_filename=image.filename or "product-image.bin",
            image_content_type=image.content_type or "application/octet-stream",
            rights_content=rights_content,
            rights_filename=rights_file.filename or "product-rights.bin",
            rights_content_type=rights_file.content_type or "application/octet-stream",
            created_by=principal.actor_id,
        )
    )


@router.get("/v1/products/{product_id}/media-readiness")
def product_media_readiness(product_id: str):
    return run(lambda: runtime.product_media.readiness(product_id))


@router.get("/v1/passport-reviews")
def passport_review_queue(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(runtime.commerce.passport_review_queue)


@router.post("/v1/products/{product_id}/passports/{kind}/review", status_code=201)
def review_passport(
    product_id: str,
    kind: PassportType,
    body: PassportReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: runtime.commerce.review_passport(
            product_id=product_id, kind=kind, reviewed_by=principal.actor_id, **body.model_dump()
        )
    )


@router.post("/v1/products/{product_id}/passports", status_code=201)
def add_passport(product_id: str, body: PassportInput, principal: Annotated[Principal, Depends(current_principal)]):
    decision = body.facts.get("decision")
    reviewed = decision in {"approved", "rejected", "blocked"}
    if reviewed:
        ensure_role(principal, "reviewer", "compliance", "admin")

    def create_and_link():
        passport = runtime.commerce.add_passport(
            product_id=product_id, **body.model_dump(), approved_by=principal.actor_id if reviewed else None
        )
        for evidence_id in passport.evidence:
            runtime.evidence.link(
                evidence_id=evidence_id,
                target_type="passport",
                target_id=passport.id,
                relationship="supports",
                created_by=principal.actor_id,
            )
        return passport

    return run(create_and_link)


@router.post("/v1/products/{product_id}/validate")
def validate_product(product_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(lambda: runtime.commerce.validate_product(product_id))


@router.post("/v1/market/observations", status_code=201)
def ingest_observation(body: ObservationInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(lambda: runtime.market.ingest(**body.model_dump()))


@router.post("/v1/market/opportunities", status_code=201)
def score_opportunity(body: OpportunityInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.market.score_opportunity(**body.model_dump()))


@router.post("/v1/market/research-signals", status_code=201)
async def capture_research_signal(
    file: Annotated[UploadFile, File()],
    provider: Annotated[str, Form()],
    provider_record_id: Annotated[str, Form()],
    source_url: Annotated[str, Form()],
    observed_at: Annotated[str, Form()],
    declared_grade: Annotated[EvidenceGrade, Form()],
    license_status: Annotated[str, Form()],
    principal: Annotated[Principal, Depends(current_principal)],
    raw_fields_json: Annotated[str, Form()] = "{}",
    candidate_refs_json: Annotated[str, Form()] = "[]",
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    max_bytes = int(os.getenv("KJDS_EVIDENCE_MAX_BYTES", str(10 * 1024 * 1024)))
    content_bytes = await file.read(max_bytes + 1)
    if len(content_bytes) > max_bytes:
        raise HTTPException(status_code=413, detail=f"Research file exceeds {max_bytes} bytes")
    try:
        raw_fields = json.loads(raw_fields_json)
        candidate_refs = json.loads(candidate_refs_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Research JSON fields must be valid JSON") from exc
    if not isinstance(raw_fields, dict) or not isinstance(candidate_refs, list):
        raise HTTPException(status_code=422, detail="raw_fields_json must be an object and candidate_refs_json a list")
    return run(
        lambda: runtime.research_inbox.capture(
            content=content_bytes,
            filename=file.filename or "research-signal.bin",
            content_type=file.content_type or "application/octet-stream",
            provider=provider,
            provider_record_id=provider_record_id,
            source_url=source_url,
            observed_at=observed_at,
            declared_grade=declared_grade,
            license_status=license_status,
            raw_fields=raw_fields,
            candidate_refs=candidate_refs,
            created_by=principal.actor_id,
        )
    )


@router.get("/v1/market/research-signals")
def list_research_signals(
    principal: Annotated[Principal, Depends(current_principal)], candidate_ref: str | None = None, limit: int = 100
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: runtime.research_inbox.list(candidate_ref=candidate_ref, limit=limit))


@router.post("/v1/market/candidates/assess")
def assess_candidate_research(
    body: CandidateResearchInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(lambda: runtime.market.assess_candidate_research(**body.model_dump()))


@router.get("/v1/market/candidate-evidence/{evidence_id}/authority-review")
def candidate_evidence_authority_status(
    evidence_id: str, metric: str, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: runtime.candidate_evidence_authority.status(evidence_id, metric))


@router.get("/v1/finance/cost-evidence/{evidence_id}/authority-review")
def cost_evidence_authority_status(
    evidence_id: str, cost_type: str, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: runtime.cost_evidence_authority.status(evidence_id, cost_type))


@router.get("/v1/finance/cost-authorities")
def cost_authority_catalog(principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    labels = {key: label for key, label, *_ in PROFIT_TEMPLATE_FIELDS}
    return {
        "schema_version": "cost-actual-authority-v1",
        "items": [
            {
                "cost_type": cost_type,
                "label": labels[cost_type],
                "authorities": [
                    {"id": authority_id, "label": ACTUAL_COST_AUTHORITY_LABELS[authority_id]}
                    for authority_id in sorted(authority_ids)
                ],
            }
            for cost_type, authority_ids in ACTUAL_COST_AUTHORITIES.items()
        ],
        "automatic_state_change": False,
        "automatic_finance_posting": False,
        "automatic_procurement": False,
        "automatic_listing": False,
    }


@router.post("/v1/finance/cost-evidence/{evidence_id}/authority-review", status_code=201)
def review_cost_evidence_authority(
    evidence_id: str,
    body: CostEvidenceAuthorityReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = runtime.cost_evidence_authority.review(
            evidence_id=evidence_id, **body.model_dump(), reviewed_by=principal.actor_id
        )
        return {
            "evidence": asdict(result["evidence"]),
            "review": asdict(result["review"]),
            "lineage": asdict(result["lineage"]) if result.get("lineage") else None,
            "idempotent": result["idempotent"],
        }

    return run(review)


@router.post("/v1/market/candidate-evidence/{evidence_id}/authority-review", status_code=201)
def review_candidate_evidence_authority(
    evidence_id: str,
    body: CandidateEvidenceAuthorityReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = runtime.candidate_evidence_authority.review(
            evidence_id=evidence_id, **body.model_dump(), reviewed_by=principal.actor_id
        )
        return {
            "evidence": asdict(result["evidence"]),
            "review": asdict(result["review"]),
            "lineage": asdict(result["lineage"]) if result.get("lineage") else None,
            "idempotent": result["idempotent"],
        }

    return run(review)


@router.post("/v1/market/candidates/intake", status_code=201)
def submit_candidate_research(
    body: CandidateResearchSubmissionInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: runtime.market.submit_candidate_research(
            **body.model_dump(exclude={"observations"}), observations=[item.model_dump() for item in body.observations]
        )
    )


@router.post("/v1/market/candidates/sourcing-handoff", status_code=201)
def handoff_candidate_to_sourcing(
    body: CandidateSourcingHandoffInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")

    def handoff():
        result = runtime.market.handoff_candidate_to_sourcing(**body.model_dump(), confirmed_by=principal.actor_id)
        for evidence_id in result["evidence_ids"]:
            runtime.evidence.link(
                evidence_id=evidence_id,
                target_type="product",
                target_id=result["product"].id,
                relationship="candidate_basis",
                created_by=principal.actor_id,
            )
        runtime.evidence.link(
            evidence_id=result["demand_report_evidence_id"],
            target_type="product",
            target_id=result["product"].id,
            relationship="demand_report_basis",
            created_by=principal.actor_id,
        )
        return result

    return run(handoff)


@router.post("/v1/marketplace-growth/portfolio-plan")
def plan_marketplace_portfolio_growth(
    body: MarketplacePortfolioGrowthPlanInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: runtime.marketplace_growth.plan_portfolio(
            observations=[
                observation.model_dump() for observation in body.observations
            ],
            target_cm3_rate=body.target_cm3_rate,
            created_by=principal.actor_id,
            as_of=body.as_of,
        )
    )


@router.post("/v1/marketplace-catalog/ozon/import-evidence", status_code=201)
def import_ozon_catalog_evidence(
    body: OzonCatalogEvidenceImportInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.marketplace_catalog.import_ozon_evidence(
            **body.model_dump(),
            imported_by=principal.actor_id,
        )
    )


@router.get("/v1/marketplace-catalog/items/latest")
def list_latest_marketplace_catalog_items(
    store_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 100,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(
        lambda: runtime.marketplace_catalog.latest_items(
            store_ref=store_ref,
            limit=limit,
        )
    )


@router.post("/v1/marketplace-catalog/items/bind-existing", status_code=201)
def bind_existing_marketplace_listing(
    body: ExistingOzonListingBindingInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.marketplace_catalog.bind_existing_listing(
            **body.model_dump(),
            bound_by=principal.actor_id,
        )
    )


@router.post("/v1/marketplace-growth/snapshots", status_code=201)
def capture_marketplace_growth_snapshot(
    body: MarketplaceGrowthSnapshotInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.marketplace_growth.capture_snapshot(
            source=body.source,
            idempotency_key=body.idempotency_key,
            observations=[
                observation.model_dump() for observation in body.observations
            ],
            captured_by=principal.actor_id,
        )
    )


@router.get("/v1/marketplace-growth/observations/latest")
def list_latest_marketplace_growth_observations(
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 100,
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(lambda: runtime.marketplace_growth.latest_observations(limit=limit))


@router.post("/v1/marketplace-growth/portfolio-plan/latest")
def plan_latest_marketplace_portfolio_growth(
    body: MarketplaceLatestGrowthPlanInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(
        lambda: runtime.marketplace_growth.plan_latest(
            target_cm3_rate=body.target_cm3_rate,
            created_by=principal.actor_id,
            as_of=body.as_of,
        )
    )


@router.post("/v1/content/assets", status_code=201)
def create_content_asset(body: ContentBriefInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.content.create_content_brief(**body.model_dump()))


@router.get("/v1/products/{product_id}/content-assets")
def list_product_content_assets(product_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "compliance", "monitor", "admin")
    return run(lambda: runtime.content.repo.content_assets_for_product(product_id))


@router.post("/v1/content/assets/{asset_id}/generation", status_code=202)
def queue_content_asset_generation(asset_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.image_execution.queue(asset_id, requested_by=principal.actor_id))


@router.post("/v1/content/assets/{asset_id}/generation/sync")
def sync_content_asset_generation(asset_id: str, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.image_execution.sync(asset_id, requested_by=principal.actor_id))


@router.post("/v1/content/assets/{asset_id}/generated")
def attach_content_asset(
    asset_id: str, body: AssetAttachInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.content.attach_generated_asset(asset_id, **body.model_dump()))


@router.post("/v1/content/assets/{asset_id}/review")
def review_content_asset(
    asset_id: str, body: AssetReviewInput, principal: Annotated[Principal, Depends(current_principal)]
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    return run(
        lambda: runtime.content.review_asset(
            asset_id, checks=[item.model_dump() for item in body.checks], reviewed_by=principal.actor_id
        )
    )


@router.post("/v1/orders", status_code=201)
def create_order(body: OrderInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.commerce.create_order(**body.model_dump()))


@router.post("/v1/orders/{order_id}/charges", status_code=201)
def add_charge(order_id: str, body: ChargeInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    return run(lambda: runtime.commerce.add_charge(order_id=order_id, **body.model_dump()))


@router.get("/v1/orders/{order_id}/profit")
def profit(order_id: str):
    return run(lambda: runtime.commerce.calculate_profit(order_id))
