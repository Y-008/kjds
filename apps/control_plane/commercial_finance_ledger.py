"""Append-only commercial cost and revenue-share ledger.

Skill usage is a metered operational fact.  This ledger records the financial
consequence of that usage (token cost, media asset cost, revenue share, or a
later adjustment) and binds it to the customer contract and entitlement that
authorized the work.  It is tenant-scoped and deliberately provider-neutral.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sql_repository import Base

FinanceEventKind = Literal["token_cost", "asset_cost", "revenue_share", "refund_adjustment"]
EVENT_KINDS = frozenset({"token_cost", "asset_cost", "revenue_share", "refund_adjustment"})


def _required(value: str, name: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class CommercialFinanceEvent:
    event_id: str
    idempotency_key: str
    tenant_id: str
    customer_id: str
    contract_id: str
    entitlement_id: str
    event_kind: FinanceEventKind
    amount: Decimal
    currency: str = "USD"
    occurred_at: datetime = datetime.min.replace(tzinfo=UTC)
    source_ref: str | None = None
    usage_event_id: str | None = None
    asset_ref: str | None = None
    cost_center: str | None = None
    metadata: dict[str, str] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _required(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "customer_id", _required(self.customer_id, "customer_id"))
        object.__setattr__(self, "contract_id", _required(self.contract_id, "contract_id"))
        object.__setattr__(self, "entitlement_id", _required(self.entitlement_id, "entitlement_id"))
        object.__setattr__(self, "event_id", _required(self.event_id, "event_id"))
        object.__setattr__(self, "idempotency_key", _required(self.idempotency_key, "idempotency_key"))
        if self.event_kind not in EVENT_KINDS:
            raise ValueError("event_kind is not allowlisted")
        amount = self.amount if isinstance(self.amount, Decimal) else Decimal(str(self.amount))
        if not amount.is_finite() or amount < 0:
            raise ValueError("amount must be finite and non-negative")
        object.__setattr__(self, "amount", amount)
        currency = str(self.currency).strip().upper()
        if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise ValueError("currency must be a three-letter ASCII code")
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "occurred_at", _aware(self.occurred_at))
        if self.metadata is not None:
            if any(not str(k).strip() or not isinstance(v, str) for k, v in self.metadata.items()):
                raise ValueError("metadata keys and values must be non-empty strings")
            object.__setattr__(self, "metadata", dict(sorted(self.metadata.items())))


def _fingerprint(event: CommercialFinanceEvent) -> str:
    payload = {
        "tenant_id": event.tenant_id, "customer_id": event.customer_id,
        "contract_id": event.contract_id, "entitlement_id": event.entitlement_id,
        "event_kind": event.event_kind, "amount": str(event.amount),
        "currency": event.currency, "occurred_at": event.occurred_at.isoformat(),
        "source_ref": event.source_ref, "usage_event_id": event.usage_event_id,
        "asset_ref": event.asset_ref, "cost_center": event.cost_center,
        "metadata": event.metadata,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class CommercialFinanceEventRow(Base):
    __tablename__ = "commercial_finance_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_commercial_finance_tenant_idempotency"),
        CheckConstraint("amount >= 0", name="ck_commercial_finance_amount_nonnegative"),
        CheckConstraint("length(currency) = 3", name="ck_commercial_finance_currency_shape"),
        Index("ix_commercial_finance_scope_occurred", "tenant_id", "customer_id", "occurred_at", "event_id"),
        Index("ix_commercial_finance_entitlement", "tenant_id", "entitlement_id", "occurred_at"),
    )

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(240), nullable=False)
    entitlement_id: Mapped[str] = mapped_column(String(240), nullable=False)
    event_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    amount_text: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    usage_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    asset_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(160), nullable=True)
    metadata_json: Mapped[dict[str, str] | None] = mapped_column(JSON, nullable=True)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CommercialFinanceLedger:
    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _from_row(row: CommercialFinanceEventRow) -> CommercialFinanceEvent:
        metadata = row.metadata_json or None
        return CommercialFinanceEvent(
            event_id=row.event_id, idempotency_key=row.idempotency_key,
            tenant_id=row.tenant_id, customer_id=row.customer_id,
            contract_id=row.contract_id, entitlement_id=row.entitlement_id,
            event_kind=row.event_kind, amount=Decimal(row.amount_text), currency=row.currency,
            occurred_at=row.occurred_at.replace(tzinfo=UTC) if row.occurred_at.tzinfo is None else row.occurred_at,
            source_ref=row.source_ref, usage_event_id=row.usage_event_id,
            asset_ref=row.asset_ref, cost_center=row.cost_center, metadata=metadata,
        )

    def record(self, event: CommercialFinanceEvent) -> CommercialFinanceEvent:
        fingerprint = _fingerprint(event)
        now = datetime.now(UTC)
        row = CommercialFinanceEventRow(
            event_id=event.event_id, idempotency_key=event.idempotency_key,
            tenant_id=event.tenant_id, customer_id=event.customer_id,
            contract_id=event.contract_id, entitlement_id=event.entitlement_id,
            event_kind=event.event_kind, amount=event.amount, amount_text=str(event.amount),
            currency=event.currency, occurred_at=event.occurred_at,
            source_ref=event.source_ref, usage_event_id=event.usage_event_id,
            asset_ref=event.asset_ref, cost_center=event.cost_center,
            metadata_json=event.metadata,
            fingerprint_sha256=fingerprint, recorded_at=now,
        )
        try:
            with Session(self.engine) as session, session.begin():
                existing = session.scalar(select(CommercialFinanceEventRow).where(
                    CommercialFinanceEventRow.tenant_id == event.tenant_id,
                    CommercialFinanceEventRow.idempotency_key == event.idempotency_key,
                ))
                if existing is not None:
                    if existing.fingerprint_sha256 != fingerprint:
                        raise ValueError("commercial finance idempotency key conflicts")
                    return self._from_row(existing)
                session.add(row)
        except IntegrityError:
            with Session(self.engine) as session:
                existing = session.scalar(select(CommercialFinanceEventRow).where(
                    CommercialFinanceEventRow.tenant_id == event.tenant_id,
                    CommercialFinanceEventRow.idempotency_key == event.idempotency_key,
                ))
                if existing is None or existing.fingerprint_sha256 != fingerprint:
                    raise
                return self._from_row(existing)
        return event

    def events_for(self, *, tenant_id: str, customer_id: str | None = None,
                   entitlement_id: str | None = None) -> tuple[CommercialFinanceEvent, ...]:
        tenant_id = _required(tenant_id, "tenant_id")
        with Session(self.engine) as session:
            query = select(CommercialFinanceEventRow).where(CommercialFinanceEventRow.tenant_id == tenant_id)
            if customer_id is not None:
                query = query.where(CommercialFinanceEventRow.customer_id == _required(customer_id, "customer_id"))
            if entitlement_id is not None:
                query = query.where(CommercialFinanceEventRow.entitlement_id == _required(entitlement_id, "entitlement_id"))
            rows = session.scalars(query.order_by(CommercialFinanceEventRow.occurred_at, CommercialFinanceEventRow.event_id)).all()
        return tuple(self._from_row(row) for row in rows)

    def summary(self, *, tenant_id: str, customer_id: str | None = None,
                entitlement_id: str | None = None, currency: str = "USD") -> dict[str, Any]:
        events = self.events_for(tenant_id=tenant_id, customer_id=customer_id, entitlement_id=entitlement_id)
        currency = str(currency).strip().upper()
        if any(event.currency != currency for event in events):
            raise ValueError("mixed currencies require an explicit FX snapshot")
        totals = {kind: Decimal("0") for kind in sorted(EVENT_KINDS)}
        for event in events:
            totals[event.event_kind] += event.amount
        return {
            "tenant_id": tenant_id, "customer_id": customer_id,
            "entitlement_id": entitlement_id, "currency": currency,
            "event_count": len(events), "totals": {key: str(value) for key, value in totals.items()},
            "total": str(sum(totals.values(), Decimal("0"))),
            "event_ids": [event.event_id for event in events],
            "external_write_allowed": False,
        }


__all__ = ["CommercialFinanceEvent", "CommercialFinanceEventRow", "CommercialFinanceLedger", "EVENT_KINDS"]
