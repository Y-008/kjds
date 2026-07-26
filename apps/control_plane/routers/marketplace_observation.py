from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..api_contracts import (
    MarketplaceObservationCaptureInput,
    PortfolioPilotPrepareInput,
    current_principal,
    ensure_role,
    run,
)
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


@router.post("/v1/marketplace-observations", status_code=201)
def capture_marketplace_observation(
    body: MarketplaceObservationCaptureInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    return run(
        lambda: runtime.marketplace_observation.capture(
            body.model_dump(mode="json"),
            actor_id=principal.actor_id,
        )
    )


@router.get("/v1/marketplace-observations")
def list_marketplace_observations(
    principal: Annotated[Principal, Depends(current_principal)],
    marketplace: str | None = None,
    source_profile: str | None = None,
    target_product_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    return run(
        lambda: runtime.marketplace_observation.latest(
            marketplace=marketplace,
            source_profile=source_profile,
            target_product_id=target_product_id,
            limit=limit,
        )
    )


@router.post("/v1/portfolio-pilot/prepare")
def prepare_portfolio_pilot(
    body: PortfolioPilotPrepareInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    values = body.model_dump()
    values["max_loss_cny"] = Decimal(str(values["max_loss_cny"]))
    values["cm3_floor_cny"] = Decimal(str(values["cm3_floor_cny"]))
    return run(
        lambda: runtime.portfolio_pilot.prepare(
            **values,
            actor_id=principal.actor_id,
        )
    )
