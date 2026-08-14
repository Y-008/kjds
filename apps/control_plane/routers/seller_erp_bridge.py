from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)

from ..api_contracts import (
    SellerErpBridgeBindingInput,
    SellerErpBridgeReviewInput,
    SellerErpBridgeRevocationInput,
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
            422, "as_of/effective_at must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(
            422, "as_of/effective_at must include a timezone"
        )
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC):
        raise HTTPException(422, "as_of/effective_at cannot be in the future")
    return parsed


def _entity_scope(
    *,
    principal: Principal,
    store_ref: str,
    as_of: datetime,
) -> dict:
    ensure_store_scope(principal, store_ref)
    return runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=as_of,
    )


def _require_entity_before_upload(entity_scope: dict) -> None:
    if (
        entity_scope.get("status") != "ready"
        or not entity_scope.get("entity_ref")
        or len(str(entity_scope.get("authority_sha256") or "")) != 64
    ):
        raise HTTPException(
            422,
            "Current exact entity/store authority is required before "
            "reading a Seller ERP source file",
        )


@router.post("/v1/seller-erp-bridge/sources", status_code=201)
async def submit_seller_erp_bridge_source(
    file: Annotated[UploadFile, File()],
    provider: Annotated[str, Form()],
    source_kind: Annotated[str, Form()],
    domain: Annotated[str, Form()],
    schema_version: Annotated[str, Form()],
    column_map_json: Annotated[str, Form()],
    exported_at: Annotated[str, Form()],
    authorization_mode: Annotated[str, Form()],
    idempotency_key: Annotated[str, Form()],
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: Annotated[str, Form()] = "ozon-primary",
    authorization_evidence_id: Annotated[str | None, Form()] = None,
    effective_until: Annotated[str | None, Form()] = None,
    worksheet: Annotated[str | None, Form()] = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    cutoff = datetime.now(UTC)
    entity_scope = _entity_scope(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    _require_entity_before_upload(entity_scope)
    try:
        column_map = json.loads(column_map_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            422, "column_map_json must be valid JSON"
        ) from exc
    if not isinstance(column_map, dict):
        raise HTTPException(
            422, "column_map_json must be a JSON object"
        )
    max_bytes = int(
        os.getenv(
            "KJDS_SELLER_ERP_BRIDGE_MAX_BYTES",
            str(10 * 1024 * 1024),
        )
    )
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise HTTPException(
            413, f"Seller ERP source file exceeds {max_bytes} bytes"
        )
    return run(
        lambda: runtime.scoped_seller_erp_bridge.submit_source(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            provider=provider,
            source_kind=source_kind,
            domain=domain,
            schema_version=schema_version,
            column_map=column_map,
            exported_at=exported_at,
            authorization_mode=authorization_mode,
            authorization_evidence_id=authorization_evidence_id,
            effective_until=effective_until,
            idempotency_key=idempotency_key,
            content=content,
            filename=file.filename or "seller-erp-source.bin",
            content_type=(
                file.content_type or "application/octet-stream"
            ),
            worksheet=worksheet,
        )
    )


@router.post("/v1/seller-erp-bridge/reviews", status_code=201)
def review_seller_erp_bridge_source(
    body: SellerErpBridgeReviewInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "reviewer", "compliance", "risk", "admin")
    cutoff = _cutoff(body.effective_at)
    entity_scope = _entity_scope(
        principal=principal,
        store_ref=body.store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.scoped_seller_erp_bridge.review_source(
            principal=principal,
            entity_scope=entity_scope,
            **body.model_dump(),
        )
    )


@router.post("/v1/seller-erp-bridge/bindings", status_code=201)
def bind_seller_erp_bridge_source(
    body: SellerErpBridgeBindingInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "compliance", "admin")
    cutoff = _cutoff(body.effective_at)
    entity_scope = _entity_scope(
        principal=principal,
        store_ref=body.store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.scoped_seller_erp_bridge.bind_source(
            principal=principal,
            entity_scope=entity_scope,
            **body.model_dump(),
        )
    )


@router.post("/v1/seller-erp-bridge/revocations", status_code=201)
def revoke_seller_erp_bridge_source(
    body: SellerErpBridgeRevocationInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "compliance", "admin")
    cutoff = _cutoff(body.effective_at)
    entity_scope = _entity_scope(
        principal=principal,
        store_ref=body.store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.scoped_seller_erp_bridge.revoke_source(
            principal=principal,
            entity_scope=entity_scope,
            **body.model_dump(),
        )
    )


@router.get("/v1/seller-erp-bridge/reconcile")
def reconcile_seller_erp_bridge(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    source_evidence_id: str | None = None,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: str | None = None,
    query: str | None = None,
    state: (
        Literal[
            "matched",
            "source_only",
            "canonical_only",
            "conflict",
            "blocked",
        ]
        | None
    ) = None,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "risk",
        "admin",
    )
    cutoff = _cutoff(as_of)
    entity_scope = _entity_scope(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    return run(
        lambda: runtime.scoped_seller_erp_bridge.reconcile(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
            source_evidence_id=source_evidence_id,
            page_size=page_size,
            cursor=cursor,
            query=query,
            state=state,
        )
    )
