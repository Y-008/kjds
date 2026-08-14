from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..evidence import parse_timestamp
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


@router.get("/v1/native-parity-acceptance/workspace")
def native_parity_acceptance_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    provider_id: str | None = None,
    capability_id: str | None = None,
    capability_version: str | None = None,
    status: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
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
    cutoff = parse_timestamp(as_of, "as_of") if as_of else datetime.now(UTC)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.native_parity_acceptance.project(
            principal=principal,
            entity_scope={
                **entity_scope,
                "tenant_ref": principal.tenant_ref,
                "store_ref": store_ref,
            },
            store_ref=store_ref,
            as_of=cutoff,
            provider_id=provider_id,
            capability_id=capability_id,
            capability_version=capability_version,
            status=status,
            page_size=page_size,
            cursor=cursor,
        )
    )
