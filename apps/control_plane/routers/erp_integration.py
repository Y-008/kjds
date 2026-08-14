from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..api_contracts import (
    ProfitErpItemSyncPrepareInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


@router.get("/v1/erp/profit-items")
def profit_item_sync_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    ensure_store_scope(principal, store_ref)
    return run(
        lambda: runtime.profit_erp_sync.workspace(
            tenant_ref=principal.tenant_ref,
            store_ref=store_ref,
        )
    )


@router.post("/v1/erp/profit-items/syncs", status_code=201)
def prepare_profit_item_sync(
    body: ProfitErpItemSyncPrepareInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    ensure_store_scope(principal, body.store_ref)
    if body.tenant_ref != principal.tenant_ref:
        raise HTTPException(status_code=403, detail="Authenticated identity is not authorized for tenant_ref")
    return run(
        lambda: runtime.profit_erp_sync.prepare(
            **body.model_dump(),
            actor_id=principal.actor_id,
        )
    )


@router.post("/v1/erp/profit-items/syncs/{sync_id}/dispatch")
def dispatch_profit_item_sync(
    sync_id: str,
    store_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    ensure_store_scope(principal, store_ref)
    return run(
        lambda: runtime.profit_erp_sync.dispatch(
            sync_id=sync_id,
            tenant_ref=principal.tenant_ref,
            store_ref=store_ref,
            actor_id=principal.actor_id,
        )
    )
