from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from ..api_contracts import (
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


@router.get("/v1/commerce-os/workspace")
def commerce_os_workspace(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    ensure_store_scope(principal, store_ref)
    return run(
        lambda: runtime.commerce_os.workspace(
            principal=principal,
            store_ref=store_ref,
            as_of=as_of,
        )
    )
