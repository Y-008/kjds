from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from ..api_contracts import (
    CommercialInvoiceInput,
    CommercialPaymentAttemptInput,
    CommercialPlanInput,
    CommercialRefundInput,
    CommercialScopeInput,
    CommercialSubscriptionInput,
    CommercialTaxEvidenceInput,
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
        raise HTTPException(status_code=422, detail="as_of must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed > datetime.now(UTC):
        raise HTTPException(status_code=422, detail="as_of cannot be in the future")
    return parsed


def _scope(body: CommercialScopeInput) -> dict[str, str]:
    return body.model_dump()


@router.post("/v1/commercial-lifecycle/plans")
def record_plan(
    body: CommercialPlanInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    ensure_store_scope(principal, body.scope.store_ref)
    return run(lambda: runtime.commercial_lifecycle.record_plan(**body.model_dump()))


@router.post("/v1/commercial-lifecycle/subscriptions")
def record_subscription(
    body: CommercialSubscriptionInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    ensure_store_scope(principal, body.scope.store_ref)
    return run(lambda: runtime.commercial_lifecycle.record_subscription(**body.model_dump()))


@router.post("/v1/commercial-lifecycle/invoices")
def record_invoice(
    body: CommercialInvoiceInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    ensure_store_scope(principal, body.scope.store_ref)
    return run(lambda: runtime.commercial_lifecycle.record_invoice(**body.model_dump()))


@router.post("/v1/commercial-lifecycle/payment-attempts")
def record_payment_attempt(
    body: CommercialPaymentAttemptInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    ensure_store_scope(principal, body.scope.store_ref)
    return run(lambda: runtime.commercial_lifecycle.record_payment_attempt(**body.model_dump()))


@router.post("/v1/commercial-lifecycle/refunds")
def record_refund(
    body: CommercialRefundInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    ensure_store_scope(principal, body.scope.store_ref)
    return run(lambda: runtime.commercial_lifecycle.record_refund(**body.model_dump()))


@router.post("/v1/commercial-lifecycle/tax-evidence")
def record_tax_evidence(
    body: CommercialTaxEvidenceInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    ensure_store_scope(principal, body.scope.store_ref)
    return run(lambda: runtime.commercial_lifecycle.record_tax_evidence(**body.model_dump()))


@router.get("/v1/commercial-lifecycle/snapshot")
def commercial_lifecycle_snapshot(
    principal: Annotated[Principal, Depends(current_principal)],
    customer_ref: str,
    deployment_ref: str,
    tenant_ref: str,
    entity_ref: str,
    store_ref: str,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "approver", "risk", "monitor", "admin")
    ensure_store_scope(principal, store_ref)
    cutoff = _cutoff(as_of)
    return run(
        lambda: runtime.commercial_lifecycle.snapshot(
            customer_ref=customer_ref,
            deployment_ref=deployment_ref,
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            as_of=cutoff,
        )
    )
