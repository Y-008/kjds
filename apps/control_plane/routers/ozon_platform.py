from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends

from ..api_contracts import (
    ApprovedListingExecutionPlanInput,
    ListingRussianNativeReviewInput,
    OzonExecutionIdentityAuthorityReviewInput,
    OzonListingDraftInput,
    current_principal,
    ensure_role,
    run,
)
from ..ozon_contracts import contract_catalog
from ..runtime import runtime
from ..security import Principal
from ..sourcing import listing_approval_payload

router = APIRouter()


@router.post("/v1/listings/ozon/drafts", status_code=201)
def create_ozon_listing_draft(body: OzonListingDraftInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")

    def create():
        draft = runtime.sourcing.create_ozon_listing_draft(**body.model_dump(), requested_by=principal.actor_id)
        scenario = runtime.sourcing_store.get_scenario(draft.scenario_id)
        approval = runtime.commerce.request_approval(
            action="listing.publish",
            resource_type="listing_draft",
            resource_id=draft.id,
            requested_by=principal.actor_id,
            payload=listing_approval_payload(draft, scenario),
        )
        draft.approval_id = approval.id
        runtime.sourcing_store.attach_listing_approval(draft)
        return {"draft": asdict(draft), "approval": asdict(approval)}

    return run(create)


@router.get("/v1/listings/ozon/drafts")
def list_ozon_listing_drafts(limit: int = 100):
    return run(lambda: runtime.sourcing_store.list_listing_drafts(min(max(limit, 1), 500)))


@router.post(
    "/v1/listings/ozon/drafts/{draft_id}/russian-native-review",
    status_code=201,
)
def review_ozon_listing_russian_native(
    draft_id: str,
    body: ListingRussianNativeReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = runtime.listing_execution_authority.review_listing(
            draft_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
        return {
            "draft": asdict(result["draft"]),
            "review": asdict(result["review"]),
            "lineage": asdict(result["lineage"]) if result.get("lineage") else None,
            "idempotent": result["idempotent"],
        }

    return run(review)


@router.post(
    "/v1/operations/ozon/execution-identities/{evidence_id}/authority-review",
    status_code=201,
)
def review_ozon_execution_identity(
    evidence_id: str,
    body: OzonExecutionIdentityAuthorityReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "admin")

    def review():
        result = runtime.listing_execution_authority.review_execution_identity(
            evidence_id,
            **body.model_dump(),
            reviewed_by=principal.actor_id,
        )
        return {
            "evidence": asdict(result["evidence"]),
            "review": asdict(result["review"]),
            "lineage": [asdict(item) for item in result.get("lineage", [])],
            "idempotent": result["idempotent"],
        }

    return run(review)


@router.post("/v1/listings/ozon/drafts/{draft_id}/execution-plan", status_code=201)
def prepare_ozon_listing_execution_plan(
    draft_id: str,
    body: ApprovedListingExecutionPlanInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.execution_plans.create_from_approved_listing(
            draft_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )
    )


@router.get("/v1/contracts/ozon")
def ozon_contracts():
    return contract_catalog()
