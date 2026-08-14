from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..api_contracts import (
    WarehouseExecutionEventInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..runtime import runtime
from ..security import Principal
from .customer_service import _cutoff

router = APIRouter()


@router.get("/v1/warehouse-fulfillment/workspace")
def warehouse_fulfillment_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    warehouse_ref: Annotated[str, Query(min_length=1, max_length=160)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    order_external_id: str | None = None,
    query: str | None = None,
    state: str | None = None,
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
    cutoff = _cutoff(as_of) if as_of else datetime.now(UTC)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.scoped_warehouse_fulfillment.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            warehouse_ref=warehouse_ref,
            as_of=cutoff,
            order_external_id=order_external_id,
            query=query,
            state=state,
            page_size=page_size,
            cursor=cursor,
        )
    )


@router.post("/v1/warehouse-fulfillment/events", status_code=201)
def append_warehouse_fulfillment_event(
    body: WarehouseExecutionEventInput,
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
    return run(
        lambda: runtime.warehouse_fulfillment.append_event(
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff.isoformat(),
            **body.model_dump(),
        )
    )
