from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..api_contracts import current_principal, ensure_role, run
from ..commercial_finance_ledger import AS_OF_BASES, CommercialFinanceEvent
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


class FinanceEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=300)
    customer_id: str = Field(min_length=1, max_length=200)
    contract_id: str = Field(min_length=1, max_length=240)
    entitlement_id: str = Field(min_length=1, max_length=240)
    event_kind: Literal["token_cost", "asset_cost", "revenue_share", "refund_adjustment"]
    amount: Decimal = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    occurred_at: datetime | None = None
    settled_at: datetime | None = None
    source_ref: str | None = Field(default=None, max_length=300)
    usage_event_id: str | None = Field(default=None, max_length=200)
    asset_ref: str | None = Field(default=None, max_length=300)
    cost_center: str | None = Field(default=None, max_length=160)
    metadata: dict[str, str] | None = None

    @field_validator("occurred_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("settled_at")
    @classmethod
    def normalize_settlement_time(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("settled_at must include a timezone")
        return value.astimezone(UTC)


def _currency(value: str) -> str:
    return value.strip().upper()


def _event_dict(event: CommercialFinanceEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "idempotency_key": event.idempotency_key,
        "tenant_id": event.tenant_id,
        "customer_id": event.customer_id,
        "contract_id": event.contract_id,
        "entitlement_id": event.entitlement_id,
        "event_kind": event.event_kind,
        "amount": str(event.amount),
        "currency": event.currency,
        "occurred_at": event.occurred_at.isoformat(),
        # ``recorded_at`` is retained as a compatibility alias for clients
        # that consumed the pre-temporal ledger response.  New consumers
        # should use the explicit observed/settled names.
        "observed_at": event.observed_at.isoformat() if event.observed_at is not None else None,
        "recorded_at": event.observed_at.isoformat() if event.observed_at is not None else None,
        "settled_at": event.settled_at.isoformat() if event.settled_at is not None else None,
        "source_ref": event.source_ref,
        "usage_event_id": event.usage_event_id,
        "asset_ref": event.asset_ref,
        "cost_center": event.cost_center,
        "metadata": event.metadata,
        "external_write_allowed": False,
    }


@router.post("/v1/commercial/finance-events")
def record_finance_event(
    body: FinanceEventInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin", "executor")
    event = CommercialFinanceEvent(
        event_id=body.event_id,
        idempotency_key=body.idempotency_key,
        tenant_id=principal.tenant_ref,
        customer_id=body.customer_id,
        contract_id=body.contract_id,
        entitlement_id=body.entitlement_id,
        event_kind=body.event_kind,
        amount=body.amount,
        currency=_currency(body.currency),
        occurred_at=(body.occurred_at or datetime.now(UTC)).astimezone(UTC),
        settled_at=body.settled_at,
        source_ref=body.source_ref,
        usage_event_id=body.usage_event_id,
        asset_ref=body.asset_ref,
        cost_center=body.cost_center,
        metadata=body.metadata,
    )
    return run(lambda: _event_dict(runtime.commercial_finance_ledger.record(event)))


@router.get("/v1/commercial/finance-summary")
def finance_summary(
    customer_id: str | None = None,
    entitlement_id: str | None = None,
    currency: Annotated[str, Query(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")] = "USD",
    as_of: datetime | None = None,
    as_of_basis: Literal["observed", "event", "settled"] = "observed",
    principal: Annotated[Principal, Depends(current_principal)] = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    if as_of is not None and (as_of.tzinfo is None or as_of.utcoffset() is None):
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    if as_of_basis not in AS_OF_BASES:
        raise HTTPException(status_code=422, detail="as_of_basis must be one of observed, event, settled")
    return run(lambda: runtime.commercial_finance_ledger.summary(
        tenant_id=principal.tenant_ref,
        customer_id=customer_id,
        entitlement_id=entitlement_id,
        currency=_currency(currency),
        as_of=as_of.astimezone(UTC) if as_of is not None else None,
        as_of_basis=as_of_basis,
    ))
