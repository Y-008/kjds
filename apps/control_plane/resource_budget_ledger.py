"""Durable resource budget reservations and consumption accounting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from threading import RLock
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sql_repository import Base

BudgetState = Literal["reserved", "consumed", "released", "overrun"]
STATES = frozenset({"reserved", "consumed", "released", "overrun"})


def _text(value: str, name: str, maximum: int = 240) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is required and bounded")
    value = str(value).strip()
    if not value or len(value) > maximum:
        raise ValueError(f"{name} is required and bounded")
    return value


def _amount(value: Decimal | str | int | float, name: str = "amount") -> Decimal:
    try:
        value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite non-negative decimal") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{name} must be a finite non-negative decimal")
    if value == 0:
        return Decimal("0")
    # Inspect the raw tuple instead of Decimal.normalize(), which is governed
    # by the process decimal context and can silently round large values.
    digits = list(value.as_tuple().digits)
    exponent = value.as_tuple().exponent
    while digits and digits[-1] == 0 and exponent < 0:
        digits.pop()
        exponent += 1
    fractional_digits = max(-exponent, 0)
    integer_digits = max(len(digits) + exponent, 0)
    if fractional_digits > 18 or integer_digits > 20:
        raise ValueError(f"{name} exceeds NUMERIC(38,18) precision")
    if len(str(value)) > 100:
        raise ValueError(f"{name} exceeds bounded text precision")
    return value


def _currency(value: str) -> str:
    value = str(value).strip().upper()
    if len(value) != 3 or not value.isascii() or not value.isalpha():
        raise ValueError("currency must be a three-letter ASCII code")
    return value


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    budget_id: str
    tenant_id: str
    resource_type: str
    cost_center: str
    limit_amount: Decimal
    currency: str = "USD"

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_id", _text(self.budget_id, "budget_id", 200))
        object.__setattr__(self, "tenant_id", _text(self.tenant_id, "tenant_id", 160))
        object.__setattr__(self, "resource_type", _text(self.resource_type, "resource_type", 80))
        object.__setattr__(self, "cost_center", _text(self.cost_center, "cost_center", 160))
        object.__setattr__(self, "limit_amount", _amount(self.limit_amount, "limit_amount"))
        object.__setattr__(self, "currency", _currency(self.currency))


@dataclass(frozen=True, slots=True)
class ResourceBudgetEvent:
    event_id: str
    idempotency_key: str
    budget_id: str
    tenant_id: str
    state: BudgetState
    amount: Decimal
    currency: str = "USD"
    parent_event_id: str | None = None
    occurred_at: datetime = datetime.min.replace(tzinfo=UTC)
    metadata: dict[str, str] | None = None

    def __post_init__(self) -> None:
        limits = {"event_id": 200, "idempotency_key": 300, "budget_id": 200, "tenant_id": 160}
        for field, maximum in limits.items():
            object.__setattr__(self, field, _text(getattr(self, field), field, maximum))
        if self.state not in STATES:
            raise ValueError("state is not allowlisted")
        object.__setattr__(self, "amount", _amount(self.amount))
        object.__setattr__(self, "currency", _currency(self.currency))
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))


def _fingerprint(event: ResourceBudgetEvent) -> str:
    return hashlib.sha256(json.dumps({
        "budget_id": event.budget_id, "tenant_id": event.tenant_id,
        "state": event.state, "amount": str(event.amount), "currency": event.currency,
        "parent_event_id": event.parent_event_id, "occurred_at": event.occurred_at.isoformat(),
        "metadata": event.metadata,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ResourceBudgetRow(Base):
    __tablename__ = "resource_budgets"
    __table_args__ = (
        CheckConstraint("limit_amount >= 0", name="ck_resource_budget_limit_nonnegative"),
        CheckConstraint("length(currency) = 3", name="ck_resource_budget_currency_shape"),
        UniqueConstraint("tenant_id", "budget_id", name="uq_resource_budget_tenant_id"),
        Index("ix_resource_budget_scope", "tenant_id", "resource_type", "cost_center"),
    )

    budget_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    cost_center: Mapped[str] = mapped_column(String(160), nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    limit_amount_text: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourceBudgetEventRow(Base):
    __tablename__ = "resource_budget_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_resource_budget_event_tenant_idempotency"),
        UniqueConstraint("tenant_id", "budget_id", "event_id", name="uq_resource_budget_event_scope_id"),
        CheckConstraint("state IN ('reserved', 'consumed', 'released', 'overrun')", name="ck_resource_budget_event_state"),
        CheckConstraint(
            "(state = 'reserved' AND parent_event_id IS NULL) OR "
            "(state IN ('consumed', 'released') AND parent_event_id IS NOT NULL) OR "
            "(state = 'overrun' AND parent_event_id IS NULL)",
            name="ck_resource_budget_event_parent_shape",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "budget_id"],
            ["resource_budgets.tenant_id", "resource_budgets.budget_id"],
            name="fk_resource_budget_event_budget",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "budget_id", "parent_event_id"],
            [
                "resource_budget_events.tenant_id",
                "resource_budget_events.budget_id",
                "resource_budget_events.event_id",
            ],
            name="fk_resource_budget_event_parent",
        ),
        CheckConstraint("amount >= 0", name="ck_resource_budget_event_amount_nonnegative"),
        CheckConstraint("length(currency) = 3", name="ck_resource_budget_event_currency_shape"),
        Index("ix_resource_budget_event_scope", "tenant_id", "budget_id", "occurred_at", "event_id"),
    )

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    budget_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    amount_text: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    parent_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResourceBudgetLedger:
    def __init__(self, engine):
        self.engine = engine
        self._lock = RLock()

    def create_budget(self, budget: ResourceBudget) -> ResourceBudget:
        now = datetime.now(UTC)
        try:
            with Session(self.engine) as session, session.begin():
                if session.get(ResourceBudgetRow, budget.budget_id) is not None:
                    raise ValueError("budget already exists")
                session.add(ResourceBudgetRow(
                    budget_id=budget.budget_id, tenant_id=budget.tenant_id,
                    resource_type=budget.resource_type, cost_center=budget.cost_center,
                    limit_amount=budget.limit_amount, limit_amount_text=str(budget.limit_amount),
                    currency=budget.currency, created_at=now,
                ))
        except IntegrityError as exc:
            raise ValueError("budget already exists") from exc
        return budget

    def _budget(self, session: Session, *, tenant_id: str, budget_id: str) -> ResourceBudgetRow:
        row = session.scalar(select(ResourceBudgetRow).where(
            ResourceBudgetRow.tenant_id == tenant_id, ResourceBudgetRow.budget_id == budget_id))
        if row is None:
            raise KeyError("resource budget not found for exact tenant scope")
        return row

    def snapshot(self, *, tenant_id: str, budget_id: str) -> dict[str, Any]:
        tenant_id, budget_id = _text(tenant_id, "tenant_id"), _text(budget_id, "budget_id")
        with Session(self.engine) as session:
            budget = self._budget(session, tenant_id=tenant_id, budget_id=budget_id)
            rows = session.scalars(select(ResourceBudgetEventRow).where(
                ResourceBudgetEventRow.tenant_id == tenant_id,
                ResourceBudgetEventRow.budget_id == budget_id)).all()
            totals = self._totals(rows)
            self._assert_numeric_integrity(budget, rows)
        available = self._available(budget, rows, totals)
        return {
            "tenant_id": tenant_id, "budget_id": budget_id, "resource_type": budget.resource_type,
            "cost_center": budget.cost_center, "currency": budget.currency,
            "limit": budget.limit_amount_text, "reserved": str(totals["reserved"]),
            "consumed": str(totals["consumed"]), "released": str(totals["released"]),
            "overrun": str(totals["overrun"]), "available": str(available),
            "event_count": len(rows), "external_write_allowed": False,
        }

    @staticmethod
    def _totals(rows: list[ResourceBudgetEventRow]) -> dict[str, Decimal]:
        with localcontext() as context:
            context.prec = 60
            totals = {state: Decimal("0") for state in sorted(STATES)}
            for row in rows:
                if row.state not in STATES:
                    raise ValueError("resource budget contains an unknown event state")
                totals[row.state] += Decimal(row.amount_text)
        return totals

    def _assert_numeric_integrity(
        self, budget: ResourceBudgetRow, rows: list[ResourceBudgetEventRow]
    ) -> None:
        # SQLite's SQLAlchemy Numeric adapter round-trips through a binary
        # float. The text columns remain canonical for the test adapter;
        # production PostgreSQL keeps the exact Numeric/Text parity check.
        exact_numeric = self.engine.dialect.name != "sqlite"
        try:
            if exact_numeric and Decimal(str(budget.limit_amount)) != Decimal(budget.limit_amount_text):
                raise ValueError("resource budget numeric integrity check failed")
            Decimal(budget.limit_amount_text)
        except (ArithmeticError, TypeError, ValueError) as exc:
            raise ValueError("resource budget numeric integrity check failed") from exc
        for row in rows:
            try:
                if exact_numeric and Decimal(str(row.amount)) != Decimal(row.amount_text):
                    raise ValueError("resource budget event numeric integrity check failed")
                Decimal(row.amount_text)
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise ValueError("resource budget event numeric integrity check failed") from exc
            if row.currency != budget.currency:
                raise ValueError("resource budget event currency integrity check failed")

    @staticmethod
    def _available(
        budget: ResourceBudgetRow,
        rows: list[ResourceBudgetEventRow],
        totals: dict[str, Decimal],
    ) -> Decimal:
        # A consumed or released child settles its parent reservation.  This
        # avoids charging the same amount twice while retaining gross counters.
        with localcontext() as context:
            context.prec = 60
            settled_by_parent: dict[str, Decimal] = {}
            for row in rows:
                if row.parent_event_id and row.state in {"consumed", "released"}:
                    settled_by_parent[row.parent_event_id] = (
                        settled_by_parent.get(row.parent_event_id, Decimal("0"))
                        + Decimal(row.amount_text)
                    )
            outstanding = Decimal("0")
            for row in rows:
                if row.state == "reserved":
                    outstanding += max(
                        Decimal("0"),
                        Decimal(row.amount_text) - settled_by_parent.get(row.event_id, Decimal("0")),
                    )
            return Decimal(budget.limit_amount_text) - totals["consumed"] - totals["overrun"] - outstanding

    @staticmethod
    def _event_from_row(row: ResourceBudgetEventRow) -> ResourceBudgetEvent:
        occurred = row.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)
        return ResourceBudgetEvent(
            event_id=row.event_id,
            idempotency_key=row.idempotency_key,
            budget_id=row.budget_id,
            tenant_id=row.tenant_id,
            state=row.state,
            amount=Decimal(row.amount_text),
            currency=row.currency,
            parent_event_id=row.parent_event_id,
            occurred_at=occurred,
            metadata=row.metadata_json,
        )

    def record(self, event: ResourceBudgetEvent) -> ResourceBudgetEvent:
        fingerprint = _fingerprint(event)
        try:
            with self._lock, Session(self.engine) as session, session.begin():
                # Locking the budget row makes the reservation check and insert
                # one atomic operation across worker processes on PostgreSQL.
                budget = session.scalar(select(ResourceBudgetRow).where(
                    ResourceBudgetRow.tenant_id == event.tenant_id,
                    ResourceBudgetRow.budget_id == event.budget_id,
                ).with_for_update())
                if budget is None:
                    raise KeyError("resource budget not found for exact tenant scope")
                if budget.currency != event.currency:
                    raise ValueError("budget currency does not match event currency")
                existing = session.scalar(select(ResourceBudgetEventRow).where(
                    ResourceBudgetEventRow.tenant_id == event.tenant_id,
                    ResourceBudgetEventRow.idempotency_key == event.idempotency_key))
                if existing is not None:
                    if existing.fingerprint_sha256 != fingerprint:
                        raise ValueError("resource budget idempotency key conflicts")
                    return self._event_from_row(existing)
                rows = session.scalars(select(ResourceBudgetEventRow).where(
                    ResourceBudgetEventRow.tenant_id == event.tenant_id,
                    ResourceBudgetEventRow.budget_id == event.budget_id)).all()
                self._assert_numeric_integrity(budget, rows)
                if event.parent_event_id is not None:
                    if event.state == "reserved":
                        raise ValueError("reserved event cannot have a parent reservation")
                    if event.state == "overrun":
                        raise ValueError("overrun event must be standalone")
                    parent = session.scalar(select(ResourceBudgetEventRow).where(
                        ResourceBudgetEventRow.tenant_id == event.tenant_id,
                        ResourceBudgetEventRow.budget_id == event.budget_id,
                        ResourceBudgetEventRow.event_id == event.parent_event_id,
                    ))
                    if parent is None:
                        raise KeyError("parent resource budget event not found for exact scope")
                elif event.state in {"consumed", "released"}:
                    raise ValueError(f"{event.state} event requires a parent reservation")
                if event.state in {"consumed", "released"}:
                    assert event.parent_event_id is not None
                    if parent.state != "reserved":
                        raise ValueError(f"{event.state} event parent must be reserved")
                    settled = session.scalars(select(ResourceBudgetEventRow).where(
                        ResourceBudgetEventRow.tenant_id == event.tenant_id,
                        ResourceBudgetEventRow.budget_id == event.budget_id,
                        ResourceBudgetEventRow.parent_event_id == event.parent_event_id,
                        ResourceBudgetEventRow.state.in_(("consumed", "released")),
                    )).all()
                    with localcontext() as context:
                        context.prec = 60
                        settled_amount = sum(
                            (Decimal(row.amount_text) for row in settled), Decimal("0")
                        )
                    if settled_amount + event.amount > Decimal(parent.amount_text):
                        raise ValueError("resource budget parent reservation already settled")
                if event.state == "reserved":
                    totals = self._totals(rows)
                    available = self._available(budget, rows, totals)
                    if available < event.amount:
                        raise ValueError("resource budget exceeded")
                session.add(ResourceBudgetEventRow(
                    event_id=event.event_id, idempotency_key=event.idempotency_key,
                    budget_id=event.budget_id, tenant_id=event.tenant_id, state=event.state,
                    amount=event.amount, amount_text=str(event.amount), currency=event.currency,
                    parent_event_id=event.parent_event_id, occurred_at=event.occurred_at,
                    metadata_json=event.metadata, fingerprint_sha256=fingerprint,
                    recorded_at=datetime.now(UTC)))
        except IntegrityError as exc:
            raise ValueError("resource budget event already exists or idempotency key conflicts") from exc
        return event


__all__ = ["ResourceBudget", "ResourceBudgetEvent", "ResourceBudgetEventRow", "ResourceBudgetLedger", "ResourceBudgetRow"]
