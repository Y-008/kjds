from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ..api_contracts import (
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
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise HTTPException(
            422, "as_of must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(
            422, "as_of must include a timezone"
        )
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC):
        raise HTTPException(422, "as_of cannot be in the future")
    return parsed


@router.get("/v1/listing-lifecycle/workspace")
def listing_lifecycle_workspace(
    principal: Annotated[
        Principal, Depends(current_principal)
    ],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
    query: str | None = None,
    stage: Literal[
        "draft_pending_review",
        "review_rejected",
        "approval_pending",
        "approval_rejected",
        "approved",
        "plan_created",
        "plan_approval_pending",
        "dry_run_failed",
        "dry_run_verified_external_gate",
        "blocked",
    ]
    | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
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
        lambda: runtime.scoped_listing_lifecycle.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            page_size=page_size,
            cursor=cursor,
            query=query,
            stage=stage,
        )
    )
