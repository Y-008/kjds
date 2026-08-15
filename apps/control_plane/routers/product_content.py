from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel, ConfigDict, field_validator

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
    MediaBatchExecutionInput,
    MediaExecutionInput,
    ObservationInput,
    OpportunityInput,
    OrderInput,
    OzonCatalogEvidenceImportInput,
    OzonCatalogReadRunImportInput,
    PassportInput,
    PassportReviewInput,
    ProductInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..cost_evidence_review import ACTUAL_COST_AUTHORITIES, ACTUAL_COST_AUTHORITY_LABELS
from ..domain import PassportType
from ..evidence import EvidenceGrade
from ..intake import PassportEvidencePayload
from ..research_inbox import ResearchInboxService
from ..runtime import runtime
from ..security import Principal
from ..sourcing import PROFIT_TEMPLATE_FIELDS

router = APIRouter()


class ResearchSignalMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_role: str
    provider: str
    provider_record_id: str
    source_url: str
    captured_at: str
    raw_fields: dict[str, Any]
    license_status: str
    review_status: str
    declared_grade: str
    promotion_status: str

    @field_validator("raw_fields")
    @classmethod
    def validate_public_raw_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        normalized = ResearchInboxService._raw_fields(value)
        if normalized != value:
            raise ValueError("Research raw fields are not canonical")
        return normalized


class ResearchSignalEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    sha256: str
    byte_size: int
    filename: str
    content_type: str
    source: str
    source_ref: str
    grade: EvidenceGrade
    effective_at: str
    effective_until: str | None
    recorded_at: str
    created_by: str
    metadata: ResearchSignalMetadataResponse


class ResearchSignalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: ResearchSignalEvidenceResponse
    candidate_refs: list[str]
    integrity_valid: bool
    decision_use: Literal[
        "auxiliary_only_pending_independent_authority_review"
    ]
    automatic_listing: Literal[False]
    automatic_procurement: Literal[False]


def _store_ref(principal: Principal, requested: str | None) -> str:
    if requested:
        ensure_store_scope(principal, requested)
        return requested
    if len(principal.store_refs) != 1:
        raise HTTPException(
            status_code=422,
            detail="store_ref is required when identity has multiple stores",
        )
    return next(iter(principal.store_refs))


def _catalog_scope_context(
    principal: Principal,
    *,
    store_ref: str,
    as_of: str | None,
) -> tuple[datetime, dict]:
    ensure_store_scope(principal, store_ref)
    if as_of is None:
        cutoff = datetime.now(UTC)
    else:
        try:
            cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="as_of must be an ISO-8601 timestamp",
            ) from exc
        if cutoff.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="as_of must include a timezone",
            )
        cutoff = cutoff.astimezone(UTC)
        if cutoff > datetime.now(UTC):
            raise HTTPException(
                status_code=422,
                detail="as_of cannot be in the future",
            )
    return cutoff, runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )


def _research_scope_context(
    principal: Principal,
    *,
    store_ref: str,
) -> dict[str, str] | None:
    """Resolve the current research scope without trusting a client cutoff."""

    ensure_store_scope(principal, store_ref)
    authority = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=datetime.now(UTC),
    )
    if authority.get("status") == "no_data":
        return None
    if (
        authority.get("status") != "ready"
        or authority.get("tenant_ref") != principal.tenant_ref
        or authority.get("store_ref") != store_ref
        or not authority.get("entity_ref")
        or not authority.get("authority_sha256")
    ):
        raise HTTPException(
            status_code=409,
            detail=authority.get("reason", "entity_scope_authority_invalid"),
        )
    return {
        "tenant_ref": principal.tenant_ref,
        "entity_ref": str(authority["entity_ref"]),
        "store_ref": store_ref,
        "scope_grant_authority_sha256": str(authority["authority_sha256"]),
    }


def _research_cursor(
    recorded_at: str | None,
    evidence_id: str | None,
) -> tuple[datetime | None, str | None]:
    if (recorded_at is None) != (evidence_id is None):
        raise HTTPException(
            status_code=422,
            detail="cursor_recorded_at and cursor_id must be supplied together",
        )
    if recorded_at is None or evidence_id is None:
        return None, None
    try:
        parsed = datetime.fromisoformat(recorded_at)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="cursor_recorded_at must be a canonical ISO-8601 timestamp",
        ) from exc
    if (
        parsed.tzinfo is None
        or parsed.astimezone(UTC).isoformat() != recorded_at
        or not evidence_id.strip()
    ):
        raise HTTPException(
            status_code=422,
            detail="Research cursor is not canonical",
        )
    return parsed.astimezone(UTC), evidence_id.strip()


@router.post("/v1/products", status_code=201)
def create_product(body: ProductInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, body.store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )
    if (
        entity_scope.get("status") != "ready"
        or not entity_scope.get("entity_ref")
    ):
        raise HTTPException(
            status_code=409,
            detail=entity_scope.get(
                "reason",
                "entity_scope_authority_missing",
            ),
        )
    return run(
        lambda: runtime.commerce.create_product(
            sku=body.sku,
            name=body.name,
            tenant_ref=principal.tenant_ref,
            entity_ref=str(entity_scope["entity_ref"]),
            store_ref=store,
            scope_grant_authority_sha256=entity_scope[
                "authority_sha256"
            ],
            scope_as_of=cutoff.isoformat(),
            created_by=principal.actor_id,
        )
    )


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
    store_ref: Annotated[str | None, Form()] = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )
    if (
        entity_scope.get("status") != "ready"
        or not entity_scope.get("entity_ref")
    ):
        raise HTTPException(
            status_code=409,
            detail=entity_scope.get(
                "reason",
                "entity_scope_authority_missing",
            ),
        )
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
            sku=sku,
            name=name,
            effective_at=effective_at,
            payloads=payloads,
            created_by=principal.actor_id,
            scope_authority={
                "tenant_ref": principal.tenant_ref,
                "entity_ref": str(entity_scope["entity_ref"]),
                "store_ref": store,
                "scope_grant_authority_sha256": entity_scope[
                    "authority_sha256"
                ],
                "as_of": cutoff,
            },
        )
    )


@router.get("/v1/products")
def list_products(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
    )


@router.get("/v1/product-content/workspace")
def product_content_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    product_id: str | None = None,
    as_of: str | None = None,
):
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=product_id,
        )
    )


@router.get("/v1/products/{product_id}/readiness")
def product_readiness(
    product_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=product_id,
        )
    )


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
    store_ref: Annotated[str | None, Form()] = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )
    authorized_product, _ = run(
        lambda: runtime.scoped_product_content.require_product(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=product_id,
        )
    )
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
            authorized_product=authorized_product,
        )
    )


@router.get("/v1/products/{product_id}/media-readiness")
def product_media_readiness(
    product_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )

    def readiness():
        runtime.scoped_product_content.require_product(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=product_id,
        )
        return runtime.product_media.readiness(product_id)

    return run(readiness)


@router.get("/v1/passport-reviews")
def passport_review_queue(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )

    def queue():
        projection = runtime.scoped_product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
        items = [
            {
                "product": product["product"],
                "passport": passport,
            }
            for product in projection["products"]
            for passport in product["passports"]
            if passport["id"] and not passport["approved_by"]
        ]
        return {**projection, "review_queue": items}

    return run(queue)


@router.post("/v1/products/{product_id}/passports/{kind}/review", status_code=201)
def review_passport(
    product_id: str,
    kind: PassportType,
    body: PassportReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )

    def review():
        projection = runtime.scoped_product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=product_id,
        )
        if not projection["products"]:
            raise KeyError(
                "Unknown product in authorized operating scope"
            )
        passport = next(
            (
                item
                for item in projection["products"][0]["passports"]
                if item["kind"] == kind.value
            ),
            None,
        )
        if passport is None or not passport["evidence_ready"]:
            raise ValueError(
                "Passport review requires current scoped Evidence"
            )
        return runtime.commerce.review_passport(
            product_id=product_id,
            kind=kind,
            reviewed_by=principal.actor_id,
            **body.model_dump(),
        )

    return run(review)


@router.post("/v1/products/{product_id}/passports", status_code=201)
def add_passport(
    product_id: str,
    body: PassportInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    decision = body.facts.get("decision")
    reviewed = decision in {"approved", "rejected", "blocked"}
    if reviewed:
        ensure_role(principal, "reviewer", "compliance", "admin")
    else:
        ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )

    def create_and_link():
        runtime.scoped_product_content.require_product(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=product_id,
        )
        if reviewed:
            runtime.scoped_product_content.require_evidence(
                evidence_ids=body.evidence,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
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
def validate_product(
    product_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )

    def validate():
        projection = runtime.scoped_product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=product_id,
        )
        if (
            not projection["products"]
            or not projection["products"][0]["readiness"][
                "passport_approved"
            ]
        ):
            raise ValueError(
                "Product validation requires three approved scoped Passports"
            )
        return runtime.commerce.validate_product(product_id)

    return run(validate)


@router.post("/v1/market/observations", status_code=201)
def ingest_observation(body: ObservationInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "reviewer", "admin")
    return run(lambda: runtime.market.ingest(**body.model_dump()))


@router.post("/v1/market/opportunities", status_code=201)
def score_opportunity(body: OpportunityInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    return run(lambda: runtime.market.score_opportunity(**body.model_dump()))


@router.post(
    "/v1/market/research-signals",
    status_code=201,
    response_model=ResearchSignalResponse,
)
async def capture_research_signal(
    file: Annotated[UploadFile, File()],
    provider: Annotated[str, Form()],
    provider_record_id: Annotated[str, Form()],
    source_url: Annotated[str, Form()],
    observed_at: Annotated[str, Form()],
    declared_grade: Annotated[EvidenceGrade, Form()],
    license_status: Annotated[str, Form()],
    store_ref: Annotated[str, Form()],
    principal: Annotated[Principal, Depends(current_principal)],
    raw_fields_json: Annotated[str, Form()] = "{}",
    candidate_refs_json: Annotated[str, Form()] = "[]",
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    scope = _research_scope_context(principal, store_ref=store_ref)
    if scope is None:
        raise HTTPException(status_code=409, detail="entity_scope_authority_missing")
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

    def require_current_scope() -> dict[str, str]:
        current = _research_scope_context(principal, store_ref=store_ref)
        if current != scope:
            raise HTTPException(
                status_code=409,
                detail="entity_scope_authority_changed_during_capture",
            )
        return current

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
            scope=scope,
            authority_subject_actor_id=principal.actor_id,
            authority_guard=require_current_scope,
        )
    )


@router.get(
    "/v1/market/research-signals",
    response_model=list[ResearchSignalResponse],
)
def list_research_signals(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str,
    candidate_ref: str | None = None,
    limit: int = 100,
    cursor_recorded_at: str | None = None,
    cursor_id: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    scope = _research_scope_context(principal, store_ref=store_ref)
    if scope is None:
        return []
    cursor_time, normalized_cursor_id = _research_cursor(
        cursor_recorded_at,
        cursor_id,
    )
    result = run(
        lambda: runtime.research_inbox.list(
            scope=scope,
            candidate_ref=candidate_ref,
            limit=limit,
            cursor_recorded_at=cursor_time,
            cursor_id=normalized_cursor_id,
        )
    )
    if _research_scope_context(principal, store_ref=store_ref) != scope:
        return []
    return result


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
    store = _store_ref(principal, body.store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )
    if (
        entity_scope.get("status") != "ready"
        or not entity_scope.get("entity_ref")
        or not entity_scope.get("authority_sha256")
        or not entity_scope.get("grant_effective_at")
    ):
        raise HTTPException(
            status_code=409,
            detail=entity_scope.get(
                "reason",
                "entity_scope_authority_missing",
            ),
        )

    def handoff():
        result = runtime.market.handoff_candidate_to_sourcing(
            **body.model_dump(exclude={"store_ref"}),
            tenant_ref=principal.tenant_ref,
            entity_ref=str(entity_scope["entity_ref"]),
            store_ref=store,
            scope_grant_authority_sha256=str(
                entity_scope["authority_sha256"]
            ),
            scope_as_of=str(entity_scope["grant_effective_at"]),
            confirmed_by=principal.actor_id,
        )
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
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )

    def scoped_import():
        evidence_authority = (
            runtime.scoped_marketplace_catalog.require_import_evidence(
                evidence_ids=body.evidence_ids,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=body.store_ref,
                as_of=cutoff,
            )
        )
        source_contract = (
            runtime.intelligence_source_adapters.catalog_contract(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=body.store_ref,
                as_of=cutoff,
                marketplace="ozon",
            )
        )
        return runtime.marketplace_catalog.import_ozon_evidence(
            **body.model_dump(),
            imported_by=principal.actor_id,
            scope_authority={
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope["entity_ref"],
                "store_ref": body.store_ref,
                "scope_grant_authority_sha256": entity_scope[
                    "authority_sha256"
                ],
                "scope_evidence_authority_sha256": evidence_authority[
                    "evidence_authority_sha256"
                ],
                "scope_as_of": cutoff.isoformat(),
            },
            source_contract=source_contract,
        )

    return run(scoped_import)


@router.post(
    "/v1/marketplace-catalog/ozon/import-read-run",
    status_code=201,
)
def import_ozon_catalog_read_run(
    body: OzonCatalogReadRunImportInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.catalog_read_run_handoffs.import_run(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            as_of=cutoff,
            run_id=body.run_id,
            idempotency_key=body.idempotency_key,
            imported_by=principal.actor_id,
        )
    )


@router.get("/v1/marketplace-catalog/ozon/read-run-handoffs")
def list_ozon_catalog_read_run_handoffs(
    store_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 100,
    as_of: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.catalog_read_run_handoffs.list_scoped(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            limit=limit,
        )
    )


@router.get(
    "/v1/marketplace-catalog/ozon/read-run-handoffs/{handoff_id}"
)
def get_ozon_catalog_read_run_handoff(
    handoff_id: str,
    store_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
    as_of: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.catalog_read_run_handoffs.get_scoped(
            handoff_id=handoff_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


@router.get("/v1/marketplace-catalog/items/latest")
def list_latest_marketplace_catalog_items(
    store_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 100,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_marketplace_catalog.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            limit=limit,
            as_of=cutoff,
        )
    )


@router.post("/v1/marketplace-catalog/items/bind-existing", status_code=201)
def bind_existing_marketplace_listing(
    body: ExistingOzonListingBindingInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )

    def scoped_binding():
        runtime.scoped_marketplace_catalog.require_current_item(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            as_of=cutoff,
            offer_id=body.offer_id,
            expected_item_hash=body.expected_item_hash,
        )
        return runtime.marketplace_catalog.bind_existing_listing(
            **body.model_dump(),
            bound_by=principal.actor_id,
        )

    return run(scoped_binding)


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
    store = _store_ref(principal, body.store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def create():
        projection = runtime.scoped_product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=body.product_id,
        )
        if (
            not projection["products"]
            or not projection["products"][0]["readiness"][
                "content_draft_allowed"
            ]
        ):
            raise ValueError(
                "Content brief requires three approved scoped Passports"
            )
        values = body.model_dump(exclude={"store_ref", "as_of"})
        return runtime.content.create_content_brief(**values)

    return run(create)


@router.get("/v1/products/{product_id}/content-assets")
def list_product_content_assets(
    product_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "monitor", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_product_content.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            product_id=product_id,
        )
    )


@router.post("/v1/content/assets/{asset_id}/generation", status_code=202)
def queue_content_asset_generation(
    asset_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def queue():
        runtime.scoped_product_content.require_asset(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            asset_id=asset_id,
        )
        return runtime.image_execution.queue(
            asset_id,
            requested_by=principal.actor_id,
        )

    return run(queue)


@router.post("/v1/content/assets/{asset_id}/generation/sync")
def sync_content_asset_generation(
    asset_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def sync():
        runtime.scoped_product_content.require_asset(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            asset_id=asset_id,
        )
        return runtime.image_execution.sync(
            asset_id,
            requested_by=principal.actor_id,
        )

    return run(sync)


@router.get("/v1/media-factory/workspace")
@router.get("/v1/media/workbench")
def media_workbench(
    principal: Annotated[Principal, Depends(current_principal)],
    product_id: str | None = None,
    store_ref: str | None = None,
    as_of: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
    query: str | None = None,
    stage: Literal[
        "brief",
        "source_rights_ready",
        "queued",
        "executing",
        "generated",
        "qa_pending",
        "qa_failed",
        "delivery_ready",
        "blocked",
    ]
    | None = None,
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
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )

    return run(
        lambda: runtime.scoped_media_factory.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            page_size=page_size,
            cursor=cursor,
            query=query,
            stage=stage,
            product_id=product_id,
        )
    )


@router.post("/v1/content/assets/{asset_id}/execution", status_code=202)
def execute_content_asset(
    asset_id: str,
    body: MediaExecutionInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def queue():
        runtime.scoped_product_content.require_asset(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            asset_id=asset_id,
        )
        return runtime.media_workbench.queue(
            asset_id,
            idempotency_key=body.idempotency_key,
            requested_by=principal.actor_id,
            retry=body.retry,
        )

    return run(queue)


@router.post("/v1/media/executions/batch", status_code=202)
def execute_content_asset_batch(
    body: MediaBatchExecutionInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def queue():
        for item in body.items:
            runtime.scoped_product_content.require_asset(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
                asset_id=item.asset_id,
            )
        return runtime.media_workbench.queue_batch(
            idempotency_key=body.idempotency_key,
            items=[item.model_dump() for item in body.items],
            requested_by=principal.actor_id,
        )

    return run(queue)


@router.post("/v1/content/assets/{asset_id}/execution/sync")
def sync_content_asset_execution(
    asset_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def sync():
        runtime.scoped_product_content.require_asset(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            asset_id=asset_id,
        )
        return runtime.media_workbench.sync(
            asset_id, requested_by=principal.actor_id
        )

    return run(sync)


@router.get("/v1/content/assets/{asset_id}/delivery-manifest")
def content_asset_delivery_manifest(
    asset_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "admin",
    )
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )

    def manifest():
        runtime.scoped_product_content.require_asset(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            asset_id=asset_id,
        )
        return runtime.media_workbench.delivery_manifest(
            asset_id, requested_by=principal.actor_id
        )

    return run(manifest)


@router.post("/v1/content/assets/{asset_id}/generated")
def attach_content_asset(
    asset_id: str,
    body: AssetAttachInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def attach():
        runtime.scoped_product_content.require_asset(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            asset_id=asset_id,
        )
        runtime.scoped_product_content.require_evidence(
            evidence_ids=[body.artifact_ref],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
        return runtime.content.attach_generated_asset(
            asset_id,
            **body.model_dump(),
        )

    return run(attach)


@router.post("/v1/content/assets/{asset_id}/review")
def review_content_asset(
    asset_id: str,
    body: AssetReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _catalog_scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def review():
        _, product, _ = runtime.scoped_product_content.require_asset(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            asset_id=asset_id,
        )
        asset = next(
            item
            for item in product["content_assets"]
            if item["id"] == asset_id
        )
        if not asset["evidence_ready"]:
            raise ValueError(
                "Content review requires current scoped source and artifact "
                "Evidence"
            )
        qa_evidence = sorted(
            {
                evidence_id
                for item in body.checks
                for evidence_id in item.evidence_ids
            }
        )
        if qa_evidence:
            runtime.scoped_product_content.require_evidence(
                evidence_ids=qa_evidence,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
        return runtime.content.review_asset(
            asset_id, checks=[item.model_dump() for item in body.checks], reviewed_by=principal.actor_id
        )

    return run(review)


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
