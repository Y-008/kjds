from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..api_contracts import (
    CustomerServiceCaseInput,
    CustomerServiceEventInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..runtime import runtime
from ..security import Principal

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


@router.get("/v1/customer-service/workspace")
def customer_service_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    query: str | None = None,
    stage: str | None = None,
    channel: str | None = None,
    priority: str | None = None,
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
        lambda: runtime.scoped_customer_service.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff.isoformat(),
            query=query,
            stage=stage,
            channel=channel,
            priority=priority,
            page_size=page_size,
            cursor=cursor,
        )
    )


@router.post("/v1/customer-service/cases", status_code=201)
def capture_customer_service_case(
    body: CustomerServiceCaseInput,
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
        lambda: runtime.customer_service.capture_case(
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff.isoformat(),
            **body.model_dump(),
        )
    )


@router.post(
    "/v1/customer-service/cases/{case_id}/events",
    status_code=201,
)
def capture_customer_service_event(
    case_id: str,
    body: CustomerServiceEventInput,
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
        lambda: runtime.customer_service.append_event(
            principal=principal,
            entity_scope=entity_scope,
            case_id=case_id,
            as_of=cutoff.isoformat(),
            **body.model_dump(),
        )
    )
