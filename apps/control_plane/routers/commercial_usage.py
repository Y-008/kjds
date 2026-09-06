from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..api_contracts import current_principal, ensure_role, run
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


@router.post("/v1/commercial/usage")
def record_usage(
    body: UsageEventInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin", "executor")
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
    )
    return run(lambda: runtime.skill_usage_ledger.record(event))


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
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    return run(lambda: runtime.skill_usage_ledger.invoice_preview(
        tenant_id=principal.tenant_ref,
        customer_id=customer_id,
        currency=_currency_code(currency),
        as_of=as_of.astimezone(UTC) if as_of is not None else None,
    ))
