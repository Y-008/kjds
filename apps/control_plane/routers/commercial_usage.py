from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..commercial_entitlement_authority import (
    CommercialEntitlementAdmissionError,
    CommercialEntitlementAuthority,
)
from ..runtime import runtime
from ..security import Principal
from ..skill_usage_ledger import SkillUsageEvent

router = APIRouter()


class UsageEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=300)
    customer_id: str = Field(min_length=1, max_length=200)
    skill_id: str = Field(min_length=1, max_length=200)
    units: Decimal = Field(ge=0)
    unit_cost: Decimal = Field(ge=0)
    currency: str = Field(
        default="USD",
        min_length=3,
        max_length=3,
        pattern=r"^[A-Za-z]{3}$",
    )
    asset_ref: str | None = Field(default=None, max_length=300)
    resource_type: str = Field(default="skill", min_length=1, max_length=80)
    provider_ref: str | None = Field(default=None, max_length=160)
    model_ref: str | None = Field(default=None, max_length=200)
    cost_center: str | None = Field(default=None, max_length=160)
    input_units: Decimal | None = Field(default=None, ge=0)
    output_units: Decimal | None = Field(default=None, ge=0)
    # Optional during migration from the legacy metering endpoint.  A
    # declared entitlement activates strict server-side scope resolution.
    entitlement_id: str | None = Field(default=None, min_length=1, max_length=240)
    deployment_ref: str | None = Field(default=None, min_length=1, max_length=160)
    entity_ref: str | None = Field(default=None, min_length=1, max_length=160)
    store_ref: str | None = Field(default=None, min_length=1, max_length=160)
    metric: str | None = Field(default=None, min_length=1, max_length=80)
    occurred_at: datetime | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        """Reject ambiguous billing times before they enter the ledger.

        A naive timestamp would be interpreted using whichever host timezone
        happens to run the API.  Usage events are immutable billing facts, so
        silently choosing that timezone would make retries and invoices
        non-reproducible.
        """

        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)


def _currency_code(value: str) -> str:
    """Normalize and validate an ISO-style three-letter currency code."""

    normalized = str(value).strip().upper()
    if (
        len(normalized) != 3
        or not normalized.isascii()
        or not normalized.isalpha()
    ):
        raise HTTPException(
            status_code=422,
            detail="currency must be a three-letter ASCII code",
        )
    return normalized


def _entitlement_admission(
    *,
    principal: Principal,
    customer_id: str,
    entitlement_id: str | None,
    deployment_ref: str | None,
    entity_ref: str | None,
    store_ref: str | None,
    metric: str | None,
    occurred_at: datetime | None,
    as_of: datetime | None = None,
) -> dict[str, object] | None:
    """Resolve an explicitly declared entitlement before metering.

    Requests that declare none of the entitlement fields retain the legacy
    behavior.  Partial declarations fail closed so a typo cannot silently
    fall back to an unbound customer or store.
    """

    declared = {
        "entitlement_id": entitlement_id,
        "deployment_ref": deployment_ref,
        "entity_ref": entity_ref,
        "store_ref": store_ref,
        "metric": metric,
    }
    if not any(value is not None for value in declared.values()):
        return None
    # ``metric`` is part of the declaration too: accepting it without an
    # entitlement would make the request look metered while remaining
    # completely unbound.
    missing = [
        name for name, value in declared.items() if value is None and name != "metric"
    ]
    if entitlement_id is None and metric is not None:
        raise HTTPException(status_code=422, detail="metric requires an entitlement scope")
    if missing:
        raise HTTPException(
            status_code=422,
            detail="entitlement scope requires: " + ", ".join(sorted(missing)),
        )
    assert entitlement_id is not None
    assert deployment_ref is not None
    assert entity_ref is not None
    assert store_ref is not None
    ensure_store_scope(principal, store_ref)
    authority = getattr(runtime, "commercial_entitlement_authority", None)
    if authority is None:
        # Test and migration runtimes created before the explicit composition
        # field remain safe while production uses the injected authority.
        authority = CommercialEntitlementAuthority(runtime.commercial_lifecycle)
    try:
        return authority.resolve(
            tenant_id=principal.tenant_ref,
            customer_id=customer_id,
            entitlement_id=entitlement_id,
            deployment_ref=deployment_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            metric=metric,
            occurred_at=occurred_at,
            as_of=as_of,
        )
    except CommercialEntitlementAdmissionError as exc:
        # Route helpers run before the normal ``run`` wrapper, so translate
        # the authority's typed domain error explicitly for HTTP callers.
        raise HTTPException(status_code=exc.http_status_code, detail=str(exc)) from exc


def _entitlement_receipt_ref(admission: dict[str, object] | None) -> str | None:
    """Extract the immutable server-issued receipt reference.

    The client never supplies this value.  It is derived from the authority's
    admission receipt and copied into the usage event before the ledger write;
    malformed authority output therefore cannot produce an apparently bound
    event.  ``None`` preserves the legacy unbound metering contract.
    """

    if admission is None:
        return None
    value = admission.get("receipt_sha256")
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 300:
        raise HTTPException(
            status_code=403,
            detail="entitlement admission receipt is malformed",
        )
    return value.strip()


@router.post("/v1/commercial/usage")
def record_usage(
    body: UsageEventInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin", "executor")
    admission = _entitlement_admission(
        principal=principal,
        customer_id=body.customer_id,
        entitlement_id=body.entitlement_id,
        deployment_ref=body.deployment_ref,
        entity_ref=body.entity_ref,
        store_ref=body.store_ref,
        metric=body.metric,
        occurred_at=body.occurred_at,
    )
    receipt_ref = _entitlement_receipt_ref(admission)
    event = SkillUsageEvent(
        event_id=body.event_id,
        idempotency_key=body.idempotency_key,
        tenant_id=principal.tenant_ref,
        customer_id=body.customer_id,
        skill_id=body.skill_id,
        units=body.units,
        unit_cost=body.unit_cost,
        currency=_currency_code(body.currency),
        occurred_at=(body.occurred_at or datetime.now(UTC)).astimezone(UTC),
        asset_ref=body.asset_ref,
        resource_type=body.resource_type,
        provider_ref=body.provider_ref,
        model_ref=body.model_ref,
        cost_center=body.cost_center,
        input_units=body.input_units,
        output_units=body.output_units,
        entitlement_receipt_ref=receipt_ref,
    )
    result = run(lambda: runtime.skill_usage_ledger.record(event))
    if admission is not None and isinstance(result, dict):
        result["entitlement_admission"] = admission
    return result


@router.get("/v1/commercial/usage-preview")
def usage_preview(
    customer_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    currency: Annotated[
        str,
        Query(
            min_length=3,
            max_length=3,
            pattern=r"^[A-Za-z]{3}$",
            description="Three-letter ASCII currency code",
        ),
    ] = "USD",
    as_of: datetime | None = None,
    entitlement_id: str | None = None,
    deployment_ref: str | None = None,
    entity_ref: str | None = None,
    store_ref: str | None = None,
    metric: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    admission = _entitlement_admission(
        principal=principal,
        customer_id=customer_id,
        entitlement_id=entitlement_id,
        deployment_ref=deployment_ref,
        entity_ref=entity_ref,
        store_ref=store_ref,
        metric=metric,
        occurred_at=as_of,
        as_of=as_of,
    )
    result = run(lambda: runtime.skill_usage_ledger.invoice_preview(
        tenant_id=principal.tenant_ref,
        customer_id=customer_id,
        currency=_currency_code(currency),
        as_of=as_of.astimezone(UTC) if as_of is not None else None,
    ))
    if admission is not None and isinstance(result, dict):
        result["entitlement_admission"] = admission
    return result
