from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from ..api_contracts import (
    BatchOpportunityPrepareInput,
    BrowserCaptureEnvelopeInput,
    MarketplaceObservationCaptureInput,
    OzonGlobalRuleEvaluationInput,
    OzonGlobalRuleImpactInput,
    PortfolioPilotPrepareInput,
    SellerOperatingSystemInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..market_recon_bundle import BundleContentConflict
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


@router.post("/v1/intelligence-ingestion/bundles/preflight")
async def preflight_market_recon_bundle(
    principal: Annotated[Principal, Depends(current_principal)],
    bundle: Annotated[UploadFile, File(description="Market recon ZIP bundle")],
    store_ref: Annotated[str, Form(min_length=1, max_length=160)] = "ozon-primary",
):
    ensure_role(principal, "operator", "reviewer", "admin")
    cutoff, entity_scope = _scope_context(principal, store_ref=store_ref, as_of=None)
    content = await bundle.read()
    return run(
        lambda: runtime.market_recon_bundles.preflight(
            content,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


@router.post("/v1/intelligence-ingestion/bundles", status_code=201)
async def ingest_market_recon_bundle(
    principal: Annotated[Principal, Depends(current_principal)],
    bundle: Annotated[UploadFile, File(description="Market recon ZIP bundle")],
    idempotency_key: Annotated[str, Form(min_length=1, max_length=180)],
    store_ref: Annotated[str, Form(min_length=1, max_length=160)] = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _scope_context(principal, store_ref=store_ref, as_of=None)
    content = await bundle.read()
    try:
        return runtime.market_recon_bundles.ingest(
            content,
            filename=bundle.filename or "market-recon-bundle.zip",
            idempotency_key=idempotency_key,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    except BundleContentConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/v1/intelligence-ingestion/bundles/{bundle_id}")
def get_market_recon_bundle(
    bundle_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    cutoff, entity_scope = _scope_context(principal, store_ref=store_ref, as_of=as_of)
    return run(
        lambda: runtime.market_recon_bundles.get(
            bundle_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


@router.get("/v1/intelligence-ingestion/bundles/{bundle_id}/quality")
def get_market_recon_bundle_quality(
    bundle_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    cutoff, entity_scope = _scope_context(principal, store_ref=store_ref, as_of=as_of)
    return run(
        lambda: runtime.market_recon_bundles.quality(
            bundle_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


def _scope_context(
    principal: Principal,
    *,
    store_ref: str,
    as_of: str | None,
) -> tuple[datetime, dict]:
    ensure_store_scope(principal, store_ref)
    if as_of is None:
        cutoff = datetime.now(UTC)
    else:
        try:
            cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail="as_of must be an ISO-8601 timestamp",
            ) from exc
        if cutoff.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="as_of must include a timezone",
            )
        cutoff = cutoff.astimezone(UTC)
        if cutoff > datetime.now(UTC):
            raise HTTPException(
                status_code=422,
                detail="as_of cannot be in the future",
            )
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return cutoff, entity_scope


@router.get("/v1/intelligence-ingestion/adapters")
def intelligence_ingestion_adapters(
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
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.intelligence_source_adapters.snapshot(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


@router.post("/v1/browser-capture-inbox/preflight")
def preflight_browser_capture(
    body: BrowserCaptureEnvelopeInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.browser_capture_inbox.preflight(
            body.model_dump(mode="json"),
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff,
        )
    )


@router.post("/v1/browser-capture-inbox/submissions", status_code=201)
def submit_browser_capture(
    body: BrowserCaptureEnvelopeInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    return run(
        lambda: runtime.browser_capture_inbox.submit(
            body.model_dump(mode="json"),
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff,
        )
    )


@router.get("/v1/browser-capture-inbox/submissions")
def list_browser_captures(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.browser_capture_inbox.list(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            limit=limit,
        )
    )


@router.post("/v1/marketplace-observations", status_code=201)
def capture_marketplace_observation(
    body: MarketplaceObservationCaptureInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=None,
    )
    if entity_scope.get("status") != "ready":
        raise HTTPException(
            status_code=409,
            detail=(
                "Marketplace observation capture requires one current "
                "entity scope grant; capture remains unbound until "
                "independent Evidence review."
            ),
        )
    def capture():
        source_contract = (
            runtime.intelligence_source_adapters.observation_contract(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=body.store_ref,
                as_of=cutoff,
                source_profile=body.source_profile,
                marketplace=body.marketplace,
            )
        )
        return runtime.marketplace_observation.capture(
            body.model_dump(mode="json"),
            actor_id=principal.actor_id,
            scope_authority={
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope["entity_ref"],
                "store_ref": body.store_ref,
                "scope_grant_authority_sha256": entity_scope[
                    "authority_sha256"
                ],
                "scope_as_of": cutoff.isoformat(),
            },
            source_contract=source_contract,
        )

    return run(capture)


@router.get("/v1/marketplace-observations")
def list_marketplace_observations(
    principal: Annotated[Principal, Depends(current_principal)],
    marketplace: str | None = None,
    source_profile: str | None = None,
    target_product_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
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
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_marketplace_observation.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            marketplace=marketplace,
            source_profile=source_profile,
            target_product_id=target_product_id,
            limit=limit,
        )
    )


@router.get("/v1/marketplace-observations/page")
def page_marketplace_observations(
    principal: Annotated[Principal, Depends(current_principal)],
    marketplace: str,
    cursor: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 500,
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
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_marketplace_observation.page(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            marketplace=marketplace,
            cursor=cursor,
            page_size=page_size,
        )
    )


@router.get("/v1/market-radar")
def get_market_radar(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    timezone: str = "UTC",
    display_currency: str = "CNY",
    source_grades: str = "A,B,C",
    max_age_hours: Annotated[int, Query(ge=1, le=8760)] = 168,
    target_purchase_quantity: Annotated[int, Query(ge=1, le=10000)] = 3,
    page_size: Annotated[int, Query(ge=1, le=1000)] = 500,
    max_rows: Annotated[int, Query(ge=1, le=50000)] = 50000,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    grades = tuple(
        item.strip()
        for item in source_grades.split(",")
        if item.strip()
    )
    return run(
        lambda: runtime.scoped_batch_opportunity.market_radar(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            timezone=timezone,
            display_currency=display_currency,
            source_grades=grades,
            max_age_hours=max_age_hours,
            target_purchase_quantity=target_purchase_quantity,
            page_size=page_size,
            max_rows=max_rows,
        )
    )


@router.post("/v1/portfolio-pilot/prepare")
def prepare_portfolio_pilot(
    body: PortfolioPilotPrepareInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    _, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=body.as_of,
    )
    if entity_scope.get("status") != "ready":
        raise HTTPException(
            status_code=409,
            detail=(
                "Portfolio Pilot requires one current entity scope grant."
            ),
        )
    raise HTTPException(
        status_code=409,
        detail=(
            "Portfolio Pilot is fail-closed until both Observation and "
            "Marketplace Catalog expose the accepted scoped authority."
        ),
    )


@router.post("/v1/batch-market-scans")
def prepare_batch_market_scan(
    body: BatchOpportunityPrepareInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "admin")
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=body.store_ref,
        as_of=body.as_of,
    )
    if entity_scope.get("status") != "ready":
        raise HTTPException(
            status_code=409,
            detail=(
                "Batch Opportunity requires one current entity scope grant."
            ),
        )
    values = body.model_dump(exclude={"as_of"})
    return run(
        lambda: runtime.scoped_batch_opportunity.prepare(
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff,
            actor_id=principal.actor_id,
            **values,
        )
    )


@router.get("/v1/batch-opportunities/latest")
def latest_batch_opportunities(
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
    cutoff, entity_scope = _scope_context(
        principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.scoped_batch_opportunity.latest(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )


@router.get("/v1/ozon-global-rules")
def get_ozon_global_rules(
    principal: Annotated[Principal, Depends(current_principal)],
    country: str = "CN",
    locale: str = "zh",
    as_of: str | None = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    return run(
        lambda: runtime.ozon_global_rules.snapshot(
            country=country,
            locale=locale,
            as_of=as_of,
        )
    )


@router.post("/v1/ozon-global-rules/evaluate")
def evaluate_ozon_global_rules(
    body: OzonGlobalRuleEvaluationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    values = body.model_dump(mode="json")
    as_of = values.pop("as_of")
    return run(
        lambda: runtime.ozon_global_rules.evaluate(values, as_of=as_of)
    )


@router.post("/v1/ozon-global-rules/impact")
def evaluate_ozon_global_rule_impact(
    body: OzonGlobalRuleImpactInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    values = body.model_dump(mode="json")
    return run(lambda: runtime.ozon_global_rules.impact(**values))


@router.get("/v1/seller-os/strategy-packs")
def get_seller_os_strategy_packs(
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "admin",
    )
    return {
        **runtime.seller_os.packs(),
        "authorized_scope": {
            "tenant_ref": principal.tenant_ref,
            "store_refs": sorted(principal.store_refs),
        },
    }


@router.post("/v1/seller-os/evaluate")
def evaluate_seller_operating_system(
    body: SellerOperatingSystemInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    ensure_store_scope(principal, body.store_ref)
    if body.tenant_ref != principal.tenant_ref:
        raise HTTPException(
            status_code=403,
            detail="Authenticated identity is not authorized for tenant_ref",
        )
    return run(
        lambda: runtime.seller_os.evaluate(body.model_dump(mode="json"))
    )
