from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..api_contracts import (
    ApprovedListingExecutionPlanInput,
    ListingRussianNativeReviewInput,
    OzonExecutionIdentityAuthorityReviewInput,
    OzonListingDraftInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..ozon_contracts import contract_catalog
from ..runtime import runtime
from ..security import Principal
from ..sourcing import listing_approval_payload

router = APIRouter()


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


def _scope_context(
    principal: Principal,
    *,
    store_ref: str,
    as_of: str | None,
) -> tuple[datetime, dict]:
    ensure_store_scope(principal, store_ref)
    cutoff = datetime.now(UTC)
    if as_of is not None:
        try:
            cutoff = datetime.fromisoformat(
                as_of.replace("Z", "+00:00")
            )
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
    return cutoff, runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )


@router.post("/v1/listings/ozon/approval-plan")
def plan_ozon_listing_approval(
    body: OzonListingDraftInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    store = _store_ref(principal, body.store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=body.as_of,
    )
    values = body.model_dump(exclude={"store_ref", "as_of"})
    return run(
        lambda: runtime.scoped_product_content.listing_approval_plan(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            **values,
        )
    )


@router.post("/v1/listings/ozon/drafts", status_code=201)
def create_ozon_listing_draft(body: OzonListingDraftInput, principal: Annotated[Principal, Depends(current_principal)]):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, body.store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )
    values = body.model_dump(exclude={"store_ref", "as_of"})

    def create():
        plan = runtime.scoped_product_content.listing_approval_plan(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
            **values,
        )
        if not plan["allowed"]:
            raise ValueError(
                "Listing approval plan is blocked: "
                + ", ".join(plan["reasons"])
            )
        draft = runtime.sourcing.create_ozon_listing_draft(
            **values,
            requested_by=principal.actor_id,
            scope_authority={
                **plan["scope"],
                "scoped_product_content_sha256": plan[
                    "product_snapshot_sha256"
                ],
                "scope_as_of": plan["as_of"],
            },
            approval_plan_sha256=plan["approval_plan_sha256"],
            evidence_ids=plan["evidence_ids"],
        )
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
        return {
            "draft": asdict(draft),
            "approval": asdict(approval),
            "approval_plan": plan,
        }

    return run(create)


@router.get("/v1/listings/ozon/drafts")
def list_ozon_listing_drafts(
    principal: Annotated[Principal, Depends(current_principal)],
    limit: int = 100,
    store_ref: str | None = None,
    as_of: str | None = None,
):
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=as_of,
    )
    if (
        entity_scope.get("status") != "ready"
        or not entity_scope.get("entity_ref")
    ):
        return {
            "status": entity_scope.get("status", "no_data"),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": None,
                "store_ref": store,
            },
            "items": [],
            "source_gaps": [
                entity_scope.get(
                    "reason",
                    "entity_scope_authority_missing",
                )
            ],
            "external_write_allowed": False,
        }
    return run(
        lambda: runtime.sourcing_store.list_listing_drafts_scoped(
            tenant_ref=principal.tenant_ref,
            entity_ref=str(entity_scope["entity_ref"]),
            store_ref=store,
            as_of=cutoff,
            limit=min(max(limit, 1), 500),
        )
    )


@router.post(
    "/v1/listings/ozon/drafts/{draft_id}/russian-native-review",
    status_code=201,
)
def review_ozon_listing_russian_native(
    draft_id: str,
    body: ListingRussianNativeReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
):
    ensure_role(principal, "reviewer", "compliance", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def review():
        if (
            entity_scope.get("status") != "ready"
            or not entity_scope.get("entity_ref")
        ):
            raise ValueError(
                entity_scope.get(
                    "reason",
                    "entity_scope_authority_missing",
                )
            )
        runtime.sourcing_store.get_listing_draft_scoped(
            draft_id=draft_id,
            tenant_ref=principal.tenant_ref,
            entity_ref=str(entity_scope["entity_ref"]),
            store_ref=store,
            as_of=cutoff,
        )
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
    store_ref: str | None = None,
):
    ensure_role(principal, "operator", "admin")
    store = _store_ref(principal, store_ref)
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store,
        as_of=None,
    )

    def create():
        if (
            entity_scope.get("status") != "ready"
            or not entity_scope.get("entity_ref")
        ):
            raise ValueError(
                entity_scope.get(
                    "reason",
                    "entity_scope_authority_missing",
                )
            )
        runtime.sourcing_store.get_listing_draft_scoped(
            draft_id=draft_id,
            tenant_ref=principal.tenant_ref,
            entity_ref=str(entity_scope["entity_ref"]),
            store_ref=store,
            as_of=cutoff,
        )
        return runtime.execution_plans.create_from_approved_listing(
            draft_id,
            **body.model_dump(),
            created_by=principal.actor_id,
        )

    return run(create)


@router.get("/v1/contracts/ozon")
def ozon_contracts():
    return contract_catalog()
