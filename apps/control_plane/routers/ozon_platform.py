from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends

from ..api_contracts import (
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


@router.get("/v1/contracts/ozon")
def ozon_contracts():
    return contract_catalog()
