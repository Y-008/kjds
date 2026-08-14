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
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            422, "as_of must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(422, "as_of must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC):
        raise HTTPException(422, "as_of cannot be in the future")
    return parsed


@router.get("/v1/sourcing-intelligence/workspace")
def sourcing_intelligence_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: str | None = None,
    query: str | None = None,
    readiness: (
        Literal[
            "research",
            "rfq",
            "three_quotes",
            "downside",
            "blocked",
        ]
        | None
    ) = None,
    target_purchase_quantity: Annotated[
        int, Query(ge=1, le=1_000_000)
    ] = 3,
    max_age_hours: Annotated[int, Query(ge=1, le=24 * 365)] = 168,
    source_grades: str = "A,B,C",
    timezone: str = "UTC",
    display_currency: str = "CNY",
):
    ensure_role(
        principal, "operator", "reviewer", "compliance", "admin"
    )
    ensure_store_scope(principal, store_ref)
    cutoff = _cutoff(as_of)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    grades = tuple(
        item.strip() for item in source_grades.split(",") if item.strip()
    )
    return run(
        lambda: runtime.scoped_sourcing_intelligence.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            page_size=page_size,
            cursor=cursor,
            query=query,
            readiness=readiness,
            target_purchase_quantity=target_purchase_quantity,
            max_age_hours=max_age_hours,
            source_grades=grades,
            timezone=timezone,
            display_currency=display_currency,
        )
    )
