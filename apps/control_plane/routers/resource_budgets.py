from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..api_contracts import current_principal, ensure_role, run
from ..resource_budget_ledger import ResourceBudget, ResourceBudgetEvent
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


class BudgetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: str = Field(min_length=1, max_length=80)
    cost_center: str = Field(min_length=1, max_length=160)
    limit_amount: Decimal = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")


class BudgetEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=300)
    state: Literal["reserved", "consumed", "released", "overrun"]
    amount: Decimal = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    parent_event_id: str | None = Field(default=None, max_length=200)
    occurred_at: datetime | None = None
    metadata: dict[str, str] | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(UTC)


def _currency(value: str) -> str:
    return value.strip().upper()


def _budget_dict(budget: ResourceBudget) -> dict[str, object]:
    return {
        "budget_id": budget.budget_id,
        "tenant_id": budget.tenant_id,
        "resource_type": budget.resource_type,
        "cost_center": budget.cost_center,
        "limit_amount": str(budget.limit_amount),
        "currency": budget.currency,
        "external_write_allowed": False,
    }


@router.post("/v1/economics/budgets/{budget_id}")
def create_budget(
    budget_id: str,
    body: BudgetInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin", "compliance")
    return run(lambda: _budget_dict(runtime.resource_budget_ledger.create_budget(ResourceBudget(
        budget_id=budget_id,
        tenant_id=principal.tenant_ref,
        resource_type=body.resource_type,
        cost_center=body.cost_center,
        limit_amount=body.limit_amount,
        currency=_currency(body.currency),
    ))))


@router.post("/v1/economics/budgets/{budget_id}/events")
def record_budget_event(
    budget_id: str,
    body: BudgetEventInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "executor", "admin")
    def record():
        event = ResourceBudgetEvent(
            event_id=body.event_id,
            idempotency_key=body.idempotency_key,
            budget_id=budget_id,
            tenant_id=principal.tenant_ref,
            state=body.state,
            amount=body.amount,
            currency=_currency(body.currency),
            parent_event_id=body.parent_event_id,
            occurred_at=(body.occurred_at or datetime.now(UTC)).astimezone(UTC),
            metadata=body.metadata,
        )
        persisted = runtime.resource_budget_ledger.record(event)
        return {
            "event_id": persisted.event_id,
            "budget_id": persisted.budget_id,
            "state": persisted.state,
            "amount": str(persisted.amount),
            "currency": persisted.currency,
            "external_write_allowed": False,
        }
    return run(record)


@router.get("/v1/economics/budgets/{budget_id}")
def budget_snapshot(
    budget_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor", "executor")
    return run(lambda: runtime.resource_budget_ledger.snapshot(
        tenant_id=principal.tenant_ref,
        budget_id=budget_id,
    ))
