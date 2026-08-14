from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..api_contracts import (
    StoreOperatingPlanFreezeInput,
    StoreOperatingProfileInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..runtime import runtime
from ..security import Principal
from ..store_category_strategy import StoreCategoryStrategyConflict

router = APIRouter()

READ_ROLES = (
    "operator",
    "reviewer",
    "compliance",
    "approver",
    "risk",
    "admin",
)


def _cutoff(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="as_of must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC):
        raise HTTPException(status_code=422, detail="as_of cannot be in the future")
    return parsed


def _context(
    principal: Principal,
    *,
    store_ref: str,
    as_of: str | None,
) -> tuple[datetime, dict]:
    ensure_store_scope(principal, store_ref)
    cutoff = _cutoff(as_of)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return cutoff, entity_scope


@router.get("/v1/seller-os/category-strategy-registry")
def category_strategy_registry(
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, *READ_ROLES)
    return runtime.store_category_strategy.registry.snapshot()


@router.post("/v1/seller-os/store-profiles", status_code=201)
def capture_store_operating_profile(
    body: StoreOperatingProfileInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _context(
        principal,
        store_ref=body.store_ref,
        as_of=body.effective_at,
    )
    values = body.model_dump(mode="json")
    store_ref = values.pop("store_ref")
    values.pop("effective_at")
    try:
        return runtime.store_category_strategy.capture_profile(
            values,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    except StoreCategoryStrategyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/seller-os/store-profiles/current")
def current_store_operating_profile(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(
        principal, store_ref=store_ref, as_of=as_of
    )


@router.get("/v1/seller-os/store-profile-proposal")
def evidence_backed_store_profile_proposal(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    seller_tier: str = "beginner",
    as_of: str | None = None,
    display_currency: str = "CNY",
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(
        principal, store_ref=store_ref, as_of=as_of
    )
    return run(
        lambda: runtime.profit_command.store_profile_proposal(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            seller_tier=seller_tier,
            as_of=cutoff,
            display_currency=display_currency,
        )
    )
    return run(
        lambda: runtime.store_category_strategy.current_profile(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


@router.get("/v1/seller-os/operating-plan")
def seller_operating_plan(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    display_currency: str = "CNY",
):
    ensure_role(principal, *READ_ROLES)
    cutoff, entity_scope = _context(
        principal, store_ref=store_ref, as_of=as_of
    )

    def project():
        workspace = runtime.profit_command.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
        )
        return runtime.store_category_strategy.compile_plan(
            workspace,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )

    return run(project)


@router.post("/v1/seller-os/operating-plans", status_code=201)
def freeze_seller_operating_plan(
    body: StoreOperatingPlanFreezeInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _context(
        principal, store_ref=body.store_ref, as_of=body.as_of
    )
    try:
        workspace = runtime.profit_command.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            as_of=cutoff,
            display_currency=body.display_currency,
        )
        plan = runtime.store_category_strategy.compile_plan(
            workspace,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            as_of=cutoff,
        )
        return runtime.store_category_strategy.freeze_plan(
            plan,
            idempotency_key=body.idempotency_key,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
            as_of=cutoff,
        )
    except StoreCategoryStrategyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/v1/seller-os/operating-plans/{snapshot_id}")
def get_seller_operating_plan_snapshot(
    snapshot_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    ensure_role(principal, *READ_ROLES)
    _, entity_scope = _context(principal, store_ref=store_ref, as_of=as_of)
    try:
        return runtime.store_category_strategy.get_plan_snapshot(
            snapshot_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/v1/seller-os/store-routing")
def seller_store_routing_matrix(
    principal: Annotated[Principal, Depends(current_principal)],
    as_of: str | None = None,
    display_currency: str = "CNY",
):
    ensure_role(principal, *READ_ROLES)
    cutoff = _cutoff(as_of)
    contexts = []
    for store_ref in sorted(principal.store_refs):
        entity_scope = runtime.scope_grants.current(
            principal=principal,
            store_ref=store_ref,
            as_of=cutoff,
        )
        if entity_scope.get("status") != "ready":
            contexts.append(
                {
                    "store_ref": store_ref,
                    "scope_status": entity_scope.get("status", "no_data"),
                    "profile_status": "not_read",
                    "profile": None,
                    "workspace": None,
                }
            )
            continue
        profile = runtime.store_category_strategy.current_profile(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
        workspace = runtime.profit_command.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            display_currency=display_currency,
        )
        contexts.append(
            {
                "store_ref": store_ref,
                "scope_status": "ready",
                "profile_status": profile.get("status", "no_data"),
                "profile": profile.get("profile"),
                "workspace": workspace,
            }
        )
    return runtime.store_category_strategy.compile_store_matrix(
        contexts,
        tenant_ref=principal.tenant_ref,
        as_of=cutoff,
    )
