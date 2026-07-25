from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..api_contracts import (
    SourceAcquisitionPullInput,
    current_principal,
    ensure_role,
    run,
)
from ..runtime import runtime
from ..security import Principal
from ..source_connector_adapters import ConnectorAdapterError
from ..source_connectors import source_connector_catalog

router = APIRouter()


@router.get("/v1/sourcing/connectors")
def sourcing_connectors():
    return source_connector_catalog(runtime.source_connectors)


@router.post("/v1/sourcing/acquisitions/pull")
def pull_source_acquisition(
    body: SourceAcquisitionPullInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    try:
        return run(
            lambda: runtime.source_acquisition.pull(
                connector_name=body.connector_name,
                cursor=body.cursor,
                actor_id=principal.actor_id,
            )
        )
    except ConnectorAdapterError as exc:
        raise HTTPException(
            status_code=409 if exc.human_action_required else 503,
            detail={
                "code": exc.code,
                "message": str(exc),
                "human_action_required": exc.human_action_required,
            },
        ) from exc


@router.get("/v1/sourcing/discoveries")
def sourcing_discoveries(
    candidate_ref: Annotated[str, Query(min_length=1, max_length=120)],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
):
    return run(
        lambda: runtime.source_acquisition.discoveries(
            candidate_ref=candidate_ref,
            limit=limit,
        )
    )


@router.get("/v1/workbench/skus/{product_or_candidate_ref:path}")
def sku_workbench(product_or_candidate_ref: str):
    return run(lambda: runtime.sku_workbench.snapshot(product_or_candidate_ref))
