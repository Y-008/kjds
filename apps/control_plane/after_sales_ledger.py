"""Append-only after-sales events and replayable risk-adjusted profit.

The native profit ledger already owns settled cash.  This module owns the
long-tail adjustments that arrive after settlement (returns, claims,
chargebacks, recoveries and reopened settlements).  It deliberately keeps
those events separate from cash so a late platform correction can be replayed
without mutating the original finance entry.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceBlobRow, EvidenceRecordRow, parse_timestamp
from .sql_repository import Base

ZERO = Decimal("0")


class AfterSalesEventKind(StrEnum):
    RETURN_ACCRUAL = "return_accrual"
    REFUND = "refund"
    CHARGEBACK = "chargeback"
    CLAIM = "claim"
    RECOVERY = "recovery"
    SETTLEMENT_REOPENED = "settlement_reopened"
    SETTLEMENT_CLOSED = "settlement_closed"


class AfterSalesImpact(StrEnum):
    EXPECTED_RETURN_COST = "expected_return_cost"
    CHARGEBACK_RESERVE = "chargeback_reserve"
    REALIZED_ADJUSTMENT = "realized_adjustment"
    RECOVERY_AMOUNT = "recovery_amount"
    REOPENED_SETTLEMENT = "reopened_settlement"
    NONE = "none"


class AfterSalesClaimStatus(StrEnum):
    NONE = "none"
    OPEN = "open"
    APPROVED = "approved"
    PAID = "paid"
    REJECTED = "rejected"
    REOPENED = "reopened"


class AfterSalesDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


EVENT_DEFAULT_IMPACT: dict[str, str] = {
    AfterSalesEventKind.RETURN_ACCRUAL.value: AfterSalesImpact.EXPECTED_RETURN_COST.value,
    AfterSalesEventKind.REFUND.value: AfterSalesImpact.REALIZED_ADJUSTMENT.value,
    AfterSalesEventKind.CHARGEBACK.value: AfterSalesImpact.CHARGEBACK_RESERVE.value,
    AfterSalesEventKind.CLAIM.value: AfterSalesImpact.CHARGEBACK_RESERVE.value,
    AfterSalesEventKind.RECOVERY.value: AfterSalesImpact.RECOVERY_AMOUNT.value,
    AfterSalesEventKind.SETTLEMENT_REOPENED.value: AfterSalesImpact.REOPENED_SETTLEMENT.value,
    AfterSalesEventKind.SETTLEMENT_CLOSED.value: AfterSalesImpact.NONE.value,
}
EVENT_DEFAULT_DIRECTION: dict[str, str] = {
    AfterSalesEventKind.RECOVERY.value: AfterSalesDirection.CREDIT.value,
}

EVENT_KINDS_SQL = ", ".join(
    f"'{item.value}'" for item in AfterSalesEventKind
)
IMPACTS_SQL = ", ".join(f"'{item.value}'" for item in AfterSalesImpact)
CLAIM_STATUSES_SQL = ", ".join(
    f"'{item.value}'" for item in AfterSalesClaimStatus
)
DIRECTIONS_SQL = ", ".join(f"'{item.value}'" for item in AfterSalesDirection)

# Native events must carry all scope material.  The all-null branch exists only
# so historical/legacy rows can remain physically isolated; the service below
# never writes that branch.
SCOPE_COMPLETE_SQL = (
    "((tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
    "AND scope_grant_authority_sha256 IS NULL AND source_evidence_sha256 IS NULL "
    "AND scope_as_of IS NULL) OR (tenant_ref IS NOT NULL "
    "AND length(tenant_ref) > 0 AND entity_ref IS NOT NULL "
    "AND length(entity_ref) > 0 AND store_ref IS NOT NULL "
    "AND length(store_ref) > 0 AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 AND scope_as_of IS NOT NULL))"
)


class AfterSalesEventRow(Base):
    """One immutable observation or restatement of an after-sales event."""

    __tablename__ = "after_sales_events"
    __table_args__ = (
        CheckConstraint(SCOPE_COMPLETE_SQL, name="ck_after_sales_scope_complete"),
        CheckConstraint(
            f"event_kind IN ({EVENT_KINDS_SQL})",
            name="ck_after_sales_event_kind",
        ),
        CheckConstraint(
            f"impact IN ({IMPACTS_SQL})",
            name="ck_after_sales_impact",
        ),
        CheckConstraint(
            f"claim_status IN ({CLAIM_STATUSES_SQL})",
            name="ck_after_sales_claim_status",
        ),
        CheckConstraint(
            f"direction IN ({DIRECTIONS_SQL})",
            name="ck_after_sales_direction",
        ),
        CheckConstraint("amount >= 0", name="ck_after_sales_amount_nonnegative"),
        CheckConstraint("length(currency) = 3", name="ck_after_sales_currency_shape"),
        CheckConstraint("version > 0", name="ck_after_sales_version_positive"),
        Index(
            "uq_after_sales_scope_idempotency",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "uq_after_sales_scope_logical_version",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "logical_event_id",
            "version",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "ix_after_sales_scope_order_effective",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "order_ref",
            "effective_time",
            "recorded_at",
        ),
        Index(
            "ix_after_sales_scope_source",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_system",
            "source_record_id",
            "source_version",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    logical_event_id: Mapped[str] = mapped_column(String(240), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    source_evidence_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    scope_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    order_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(240), nullable=True)
    event_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    impact: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    claim_status: Mapped[str] = mapped_column(String(24), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    amount_text: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_system: Mapped[str] = mapped_column(String(120), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(240), nullable=False)
    source_version: Mapped[str] = mapped_column(String(120), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(240), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(240), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey(EvidenceRecordRow.id), nullable=False
    )
    supersedes_event_id: Mapped[str | None] = mapped_column(
        ForeignKey("after_sales_events.event_id"), nullable=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class AfterSalesEvent:
    event_id: str
    logical_event_id: str
    version: int
    order_ref: str
    sku: str | None
    event_kind: str
    impact: str
    direction: str
    claim_status: str
    amount: str
    currency: str
    event_time: str
    observed_time: str
    effective_time: str
    settled_time: str | None
    source_system: str
    source_record_id: str
    source_version: str
    causation_id: str
    correlation_id: str
    idempotency_key: str
    evidence_id: str
    supersedes_event_id: str | None
    created_by: str
    recorded_at: str
    scope: dict[str, Any]


class AfterSalesLedgerError(ValueError):
    """Raised for invalid or conflicting append-only event submissions."""


class AfterSalesLedgerService:
    """Record and replay exact-scope after-sales events.

    All writes require a server-produced scope authority and Evidence.  A
    restatement is another row with a higher logical version; old rows remain
    available to historical snapshots.
    """

    CONTRACT_ID = "kjds-native-after-sales-ledger-v1"
    SNAPSHOT_CONTRACT_ID = "kjds-native-risk-adjusted-profit-v1"

    def __init__(self, engine) -> None:
        self.engine = engine

    def record_event(
        self,
        *,
        order_ref: str,
        event_kind: AfterSalesEventKind | str,
        amount: Decimal,
        currency: str,
        event_time: str,
        observed_time: str,
        effective_time: str,
        evidence_id: str,
        created_by: str,
        source_system: str,
        source_record_id: str,
        source_version: str = "1",
        claim_status: AfterSalesClaimStatus | str = AfterSalesClaimStatus.NONE,
        direction: AfterSalesDirection | str | None = None,
        impact: AfterSalesImpact | str | None = None,
        settled_time: str | None = None,
        sku: str | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str,
        logical_event_id: str | None = None,
        supersedes_event_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
        scope_authority: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> AfterSalesEvent:
        kind = self._enum(event_kind, AfterSalesEventKind, "event_kind")
        status = self._enum(claim_status, AfterSalesClaimStatus, "claim_status")
        normalized_direction = self._enum(
            direction
            if direction is not None
            else EVENT_DEFAULT_DIRECTION.get(
                kind.value, AfterSalesDirection.DEBIT.value
            ),
            AfterSalesDirection,
            "direction",
        )
        normalized_impact = (
            self._enum(impact, AfterSalesImpact, "impact")
            if impact is not None
            else AfterSalesImpact(EVENT_DEFAULT_IMPACT[kind.value])
        )
        key = self._required(idempotency_key, "idempotency_key", 300)
        order = self._required(order_ref, "order_ref", 240)
        source = self._required(source_system, "source_system", 120)
        source_id = self._required(source_record_id, "source_record_id", 240)
        source_ver = self._required(source_version, "source_version", 120)
        actor = self._required(created_by, "created_by", 160)
        logical = self._required(
            logical_event_id or f"{source}:{source_id}",
            "logical_event_id",
            240,
        )
        normalized_currency = self._currency(currency)
        normalized_amount = self._decimal(amount, "amount")
        if normalized_amount < ZERO:
            raise AfterSalesLedgerError("amount cannot be negative")
        event_dt = self._timestamp(event_time, "event_time")
        observed_dt = self._timestamp(observed_time, "observed_time")
        effective_dt = self._timestamp(effective_time, "effective_time")
        settled_dt = (
            self._timestamp(settled_time, "settled_time")
            if settled_time is not None
            else None
        )
        recorded_dt = (
            self._timestamp(recorded_at, "recorded_at")
            if recorded_at is not None
            else datetime.now(UTC)
        )
        now = datetime.now(UTC)
        for name, value in (
            ("event_time", event_dt),
            ("observed_time", observed_dt),
            ("effective_time", effective_dt),
            ("settled_time", settled_dt),
            ("recorded_at", recorded_dt),
        ):
            if value is not None and value > now:
                raise AfterSalesLedgerError(f"{name} cannot be in the future")
        if observed_dt > recorded_dt:
            raise AfterSalesLedgerError("observed_time cannot follow recorded_at")
        if settled_dt is not None and settled_dt < event_dt:
            raise AfterSalesLedgerError("settled_time cannot precede event_time")
        scope = self._scope(scope_authority, evidence_id=evidence_id)
        normalized_sku = self._optional(sku, "sku", 240)
        causation = self._required(causation_id or logical, "causation_id", 240)
        correlation = self._required(
            correlation_id or logical, "correlation_id", 240
        )
        payload_copy = self._json_mapping(payload)
        fingerprint_payload = {
            "logical_event_id": logical,
            "order_ref": order,
            "sku": normalized_sku,
            "event_kind": kind.value,
            "impact": normalized_impact.value,
            "direction": normalized_direction.value,
            "claim_status": status.value,
            "amount": self._decimal_text(normalized_amount),
            "currency": normalized_currency,
            "event_time": event_dt.isoformat(),
            "observed_time": observed_dt.isoformat(),
            "effective_time": effective_dt.isoformat(),
            "settled_time": settled_dt.isoformat() if settled_dt else None,
            "source_system": source,
            "source_record_id": source_id,
            "source_version": source_ver,
            "causation_id": causation,
            "correlation_id": correlation,
            "evidence_id": evidence_id,
            "supersedes_event_id": supersedes_event_id,
            "payload": payload_copy,
            "scope": scope,
        }
        fingerprint = self._hash(fingerprint_payload)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._require_evidence(session, evidence_id)
            existing = session.scalar(
                select(AfterSalesEventRow).where(
                    AfterSalesEventRow.tenant_ref == scope["tenant_ref"],
                    AfterSalesEventRow.entity_ref == scope["entity_ref"],
                    AfterSalesEventRow.store_ref == scope["store_ref"],
                    AfterSalesEventRow.idempotency_key == key,
                )
            )
            if existing is not None:
                if existing.fingerprint_sha256 != fingerprint:
                    raise AfterSalesLedgerError(
                        "idempotency_key conflicts with immutable event content"
                    )
                return self._event(existing)
            latest = session.scalar(
                select(AfterSalesEventRow)
                .where(
                    AfterSalesEventRow.tenant_ref == scope["tenant_ref"],
                    AfterSalesEventRow.entity_ref == scope["entity_ref"],
                    AfterSalesEventRow.store_ref == scope["store_ref"],
                    AfterSalesEventRow.logical_event_id == logical,
                )
                .order_by(
                    AfterSalesEventRow.version.desc(),
                    AfterSalesEventRow.recorded_at.desc(),
                    AfterSalesEventRow.event_id.desc(),
                )
                .limit(1)
            )
            version = 1 if latest is None else latest.version + 1
            if supersedes_event_id is not None:
                supersedes = session.get(AfterSalesEventRow, supersedes_event_id)
                if supersedes is None:
                    raise AfterSalesLedgerError(
                        "supersedes_event_id references an unknown event"
                    )
                if not self._same_scope(supersedes, scope):
                    raise AfterSalesLedgerError(
                        "supersedes_event_id crosses the exact scope"
                    )
                if supersedes.logical_event_id != logical:
                    raise AfterSalesLedgerError(
                        "supersedes_event_id has a different logical event"
                    )
            row = AfterSalesEventRow(
                event_id=new_id("after_sales"),
                logical_event_id=logical,
                version=version,
                order_ref=order,
                sku=normalized_sku,
                event_kind=kind.value,
                impact=normalized_impact.value,
                direction=normalized_direction.value,
                claim_status=status.value,
                amount=normalized_amount,
                amount_text=self._decimal_text(normalized_amount),
                currency=normalized_currency,
                event_time=event_dt,
                observed_time=observed_dt,
                effective_time=effective_dt,
                settled_time=settled_dt,
                source_system=source,
                source_record_id=source_id,
                source_version=source_ver,
                causation_id=causation,
                correlation_id=correlation,
                idempotency_key=key,
                evidence_id=evidence_id,
                supersedes_event_id=supersedes_event_id,
                payload_json=payload_copy,
                fingerprint_sha256=fingerprint,
                created_by=actor,
                recorded_at=recorded_dt,
                **self._scope_columns(scope),
            )
            session.add(row)
            session.flush()
            return self._event(row)

    def restate_event(self, event_id: str, **changes: Any) -> AfterSalesEvent:
        """Append a new version while retaining the original event row."""

        requested_id = self._required(event_id, "event_id", 200)
        with Session(self.engine) as session:
            original = session.get(AfterSalesEventRow, requested_id)
            if original is None:
                raise KeyError(f"Unknown after-sales event: {requested_id}")
            if original.tenant_ref is None:
                raise AfterSalesLedgerError("Legacy after-sales rows are not restatable")
            scope = self._scope_from_row(original)
            evidence_id = str(changes.pop("evidence_id", original.evidence_id))
            values: dict[str, Any] = {
                "order_ref": original.order_ref,
                "event_kind": original.event_kind,
                "amount": Decimal(str(original.amount)),
                "currency": original.currency,
                "event_time": original.event_time.isoformat(),
                "observed_time": original.observed_time.isoformat(),
                "effective_time": original.effective_time.isoformat(),
                "settled_time": (
                    original.settled_time.isoformat()
                    if original.settled_time
                    else None
                ),
                "evidence_id": evidence_id,
                "created_by": original.created_by,
                "source_system": original.source_system,
                "source_record_id": original.source_record_id,
                "source_version": original.source_version,
                "claim_status": original.claim_status,
                "direction": original.direction,
                "impact": original.impact,
                "sku": original.sku,
                "causation_id": original.causation_id,
                "correlation_id": original.correlation_id,
                "idempotency_key": changes.pop(
                    "idempotency_key", f"restate:{requested_id}:{new_id('key')}"
                ),
                "logical_event_id": original.logical_event_id,
                "supersedes_event_id": requested_id,
                "payload": original.payload_json,
                "scope_authority": scope,
            }
            values.update(changes)
        return self.record_event(**values)

    def snapshot(
        self,
        *,
        scope_authority: Mapping[str, Any],
        as_of: str,
        realized_profit: Decimal | None = None,
        order_ref: str | None = None,
        sku: str | None = None,
        currency: str = "CNY",
    ) -> dict[str, Any]:
        cutoff = self._timestamp(as_of, "as_of")
        if cutoff > datetime.now(UTC):
            raise AfterSalesLedgerError("as_of cannot be in the future")
        scope = self._scope(scope_authority, evidence_id=None)
        quote = self._currency(currency)
        order_filter = self._optional(order_ref, "order_ref", 240)
        sku_filter = self._optional(sku, "sku", 240)
        baseline = (
            None
            if realized_profit is None
            else self._decimal(realized_profit, "realized_profit")
        )
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(AfterSalesEventRow)
                    .where(
                        AfterSalesEventRow.tenant_ref == scope["tenant_ref"],
                        AfterSalesEventRow.entity_ref == scope["entity_ref"],
                        AfterSalesEventRow.store_ref == scope["store_ref"],
                        AfterSalesEventRow.scope_grant_authority_sha256
                        == scope["scope_grant_authority_sha256"],
                        AfterSalesEventRow.source_evidence_sha256
                        == scope["source_evidence_sha256"],
                        AfterSalesEventRow.scope_as_of
                        <= cutoff,
                        AfterSalesEventRow.recorded_at <= cutoff,
                        AfterSalesEventRow.observed_time <= cutoff,
                        AfterSalesEventRow.effective_time <= cutoff,
                    )
                    .order_by(
                        AfterSalesEventRow.logical_event_id,
                        AfterSalesEventRow.version,
                        AfterSalesEventRow.recorded_at,
                        AfterSalesEventRow.event_id,
                    )
                )
            )
            evidence_rows = {
                row.id: row
                for row in session.scalars(
                    select(EvidenceRecordRow).where(
                        EvidenceRecordRow.recorded_at <= cutoff
                    )
                )
            }
            blob_hashes = set(session.scalars(select(EvidenceBlobRow.sha256)))

        # Select exactly one version per logical event at the requested point
        # in time.  A later restatement cannot erase what was known earlier.
        latest_by_logical: dict[str, AfterSalesEventRow] = {}
        for row in rows:
            if order_filter is not None and row.order_ref != order_filter:
                continue
            if sku_filter is not None and row.sku != sku_filter:
                continue
            latest_by_logical[row.logical_event_id] = row
        selected = list(latest_by_logical.values())
        selected.sort(key=lambda row: (row.effective_time, row.event_id))
        invalid: list[str] = []
        totals = {
            AfterSalesImpact.EXPECTED_RETURN_COST.value: ZERO,
            AfterSalesImpact.CHARGEBACK_RESERVE.value: ZERO,
            AfterSalesImpact.REALIZED_ADJUSTMENT.value: ZERO,
            AfterSalesImpact.RECOVERY_AMOUNT.value: ZERO,
            AfterSalesImpact.REOPENED_SETTLEMENT.value: ZERO,
        }
        event_payloads: list[dict[str, Any]] = []
        currencies: set[str] = set()
        for row in selected:
            evidence_row = evidence_rows.get(row.evidence_id)
            if (
                evidence_row is None
                or evidence_row.blob_sha256 not in blob_hashes
                or self._aware(evidence_row.effective_at) > cutoff
                or (
                    evidence_row.effective_until is not None
                    and self._aware(evidence_row.effective_until) <= cutoff
                )
            ):
                invalid.append(row.event_id)
                continue
            currencies.add(row.currency)
            if row.currency != quote:
                invalid.append(row.event_id)
                continue
            signed = Decimal(str(row.amount))
            if row.impact == AfterSalesImpact.RECOVERY_AMOUNT.value:
                # Recovery is a benefit: an inflow/credit adds it, while a
                # debit records a later reversal of that recovery.
                if row.direction == AfterSalesDirection.DEBIT.value:
                    signed = -signed
            elif row.direction == AfterSalesDirection.CREDIT.value:
                signed = -signed
            if row.impact in totals:
                totals[row.impact] += signed
            event_payloads.append(self._event_payload(row))
        if len(currencies) > 1:
            invalid.extend(row.event_id for row in selected)
        # A credit cannot release more reserve than has been accrued.  Mark the
        # snapshot blocked instead of silently producing a negative reserve.
        for key in (
            AfterSalesImpact.EXPECTED_RETURN_COST.value,
            AfterSalesImpact.CHARGEBACK_RESERVE.value,
        ):
            if totals[key] < ZERO:
                invalid.append(f"negative_{key}")

        status = "NO_DATA"
        if selected:
            status = "BLOCKED" if invalid else "PARTIAL" if baseline is None else "VALID"
        if baseline is not None and not baseline.is_finite():
            invalid.append("realized_profit_invalid")
            status = "BLOCKED"
        risk_adjusted = None
        if baseline is not None and status in {"VALID", "PARTIAL"}:
            risk_adjusted = (
                baseline
                - totals[AfterSalesImpact.EXPECTED_RETURN_COST.value]
                - totals[AfterSalesImpact.CHARGEBACK_RESERVE.value]
                - totals[AfterSalesImpact.REALIZED_ADJUSTMENT.value]
                + totals[AfterSalesImpact.RECOVERY_AMOUNT.value]
                - totals[AfterSalesImpact.REOPENED_SETTLEMENT.value]
            )
        public_totals = {
            key: (self._decimal_text(value) if selected and not invalid else None)
            for key, value in totals.items()
        }
        payload = {
            "contract_id": self.SNAPSHOT_CONTRACT_ID,
            "registry_version": "native-after-sales/1.0.0",
            "status": status,
            "as_of": cutoff.isoformat(),
            "scope": scope,
            "order_ref": order_filter,
            "sku": sku_filter,
            "currency": quote,
            "realized_profit": (
                self._decimal_text(baseline)
                if baseline is not None and status in {"VALID", "PARTIAL"}
                else None
            ),
            "expected_return_cost": public_totals[
                AfterSalesImpact.EXPECTED_RETURN_COST.value
            ],
            "chargeback_reserve": public_totals[
                AfterSalesImpact.CHARGEBACK_RESERVE.value
            ],
            "realized_adjustment": public_totals[
                AfterSalesImpact.REALIZED_ADJUSTMENT.value
            ],
            "recovery_amount": public_totals[
                AfterSalesImpact.RECOVERY_AMOUNT.value
            ],
            "reopened_settlement": public_totals[
                AfterSalesImpact.REOPENED_SETTLEMENT.value
            ],
            "risk_adjusted_profit": (
                self._decimal_text(risk_adjusted) if risk_adjusted is not None else None
            ),
            "claim_status": self._claim_status(selected),
            "event_count": len(selected),
            "event_ids": sorted(row.event_id for row in selected),
            "evidence_ids": sorted({row.evidence_id for row in selected}),
            "versions": {
                row.logical_event_id: row.version for row in selected
            },
            "events": event_payloads if not invalid else [],
            "invalid": sorted(set(invalid)),
            "replay": {
                "latest_version_per_logical_event": True,
                "recorded_at_cutoff": cutoff.isoformat(),
                "old_versions_retained": True,
            },
            "control_envelope": {
                "read_only_projection": True,
                "external_write_allowed": False,
                "finance_cash_mutation_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def snapshot_for_order(self, **kwargs: Any) -> dict[str, Any]:
        """Explicit alias used by order-level profit projections."""

        return self.snapshot(**kwargs)

    @classmethod
    def _event_payload(cls, row: AfterSalesEventRow) -> dict[str, Any]:
        return {
            "event_id": row.event_id,
            "logical_event_id": row.logical_event_id,
            "version": row.version,
            "order_ref": row.order_ref,
            "sku": row.sku,
            "event_kind": row.event_kind,
            "impact": row.impact,
            "direction": row.direction,
            "claim_status": row.claim_status,
            "amount": cls._decimal_text(Decimal(str(row.amount))),
            "currency": row.currency,
            "event_time": cls._aware(row.event_time).isoformat(),
            "observed_time": cls._aware(row.observed_time).isoformat(),
            "effective_time": cls._aware(row.effective_time).isoformat(),
            "settled_time": (
                cls._aware(row.settled_time).isoformat()
                if row.settled_time
                else None
            ),
            "source_system": row.source_system,
            "source_record_id": row.source_record_id,
            "source_version": row.source_version,
            "causation_id": row.causation_id,
            "correlation_id": row.correlation_id,
            "evidence_id": row.evidence_id,
            "supersedes_event_id": row.supersedes_event_id,
            "recorded_at": cls._aware(row.recorded_at).isoformat(),
        }

    @classmethod
    def _event(cls, row: AfterSalesEventRow) -> AfterSalesEvent:
        return AfterSalesEvent(
            event_id=row.event_id,
            logical_event_id=row.logical_event_id,
            version=row.version,
            order_ref=row.order_ref,
            sku=row.sku,
            event_kind=row.event_kind,
            impact=row.impact,
            direction=row.direction,
            claim_status=row.claim_status,
            amount=cls._decimal_text(Decimal(str(row.amount))),
            currency=row.currency,
            event_time=cls._aware(row.event_time).isoformat(),
            observed_time=cls._aware(row.observed_time).isoformat(),
            effective_time=cls._aware(row.effective_time).isoformat(),
            settled_time=(
                cls._aware(row.settled_time).isoformat()
                if row.settled_time
                else None
            ),
            source_system=row.source_system,
            source_record_id=row.source_record_id,
            source_version=row.source_version,
            causation_id=row.causation_id,
            correlation_id=row.correlation_id,
            idempotency_key=row.idempotency_key,
            evidence_id=row.evidence_id,
            supersedes_event_id=row.supersedes_event_id,
            created_by=row.created_by,
            recorded_at=cls._aware(row.recorded_at).isoformat(),
            scope=cls._scope_from_row(row),
        )

    @staticmethod
    def _enum(value: Any, enum_type, field: str):
        try:
            return enum_type(value)
        except (TypeError, ValueError) as exc:
            raise AfterSalesLedgerError(f"{field} is unsupported") from exc

    @staticmethod
    def _required(value: Any, field: str, max_length: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > max_length:
            raise AfterSalesLedgerError(
                f"{field} must be 1 to {max_length} characters"
            )
        return normalized

    @classmethod
    def _optional(cls, value: Any, field: str, max_length: int) -> str | None:
        if value is None:
            return None
        return cls._required(value, field, max_length)

    @staticmethod
    def _json_mapping(value: Mapping[str, Any] | None) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise AfterSalesLedgerError("payload must be an object")
        try:
            encoded = json.dumps(
                dict(value), ensure_ascii=False, sort_keys=True, allow_nan=False
            )
            result = json.loads(encoded)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise AfterSalesLedgerError("payload must be finite JSON") from exc
        if not isinstance(result, dict):
            raise AfterSalesLedgerError("payload must be an object")
        return result

    @staticmethod
    def _decimal(value: Any, field: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise AfterSalesLedgerError(f"{field} must be numeric") from exc
        if not parsed.is_finite():
            raise AfterSalesLedgerError(f"{field} must be finite")
        return parsed

    @staticmethod
    def _decimal_text(value: Decimal | None) -> str | None:
        if value is None:
            return None
        if value == ZERO:
            return "0"
        return format(value.normalize(), "f")

    @staticmethod
    def _currency(value: str) -> str:
        normalized = str(value or "").strip().upper()
        if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
            raise AfterSalesLedgerError("currency must be a three-letter code")
        return normalized

    @staticmethod
    def _timestamp(value: str, field: str) -> datetime:
        try:
            return parse_timestamp(str(value), field)
        except (TypeError, ValueError) as exc:
            raise AfterSalesLedgerError(str(exc)) from exc

    @classmethod
    def _scope(
        cls,
        authority: Mapping[str, Any] | None,
        *,
        evidence_id: str | None,
    ) -> dict[str, Any]:
        if not isinstance(authority, Mapping):
            raise AfterSalesLedgerError("exact scope authority is required")
        tenant = cls._required(authority.get("tenant_ref"), "tenant_ref", 160)
        entity = cls._required(authority.get("entity_ref"), "entity_ref", 160)
        store = cls._required(authority.get("store_ref"), "store_ref", 160)
        grant = cls._required(
            authority.get("scope_grant_authority_sha256"),
            "scope_grant_authority_sha256",
            64,
        ).lower()
        if len(grant) != 64 or any(ch not in "0123456789abcdef" for ch in grant):
            raise AfterSalesLedgerError("scope grant authority must be SHA-256")
        source_hash = cls._required(
            authority.get("source_evidence_sha256")
            or authority.get("scope_source_evidence_sha256"),
            "source_evidence_sha256",
            64,
        ).lower()
        if len(source_hash) != 64 or any(
            ch not in "0123456789abcdef" for ch in source_hash
        ):
            raise AfterSalesLedgerError("source evidence authority must be SHA-256")
        as_of = authority.get("scope_as_of") or authority.get("as_of")
        if as_of is None:
            raise AfterSalesLedgerError("scope_as_of is required")
        cutoff = cls._timestamp(str(as_of), "scope_as_of")
        return {
            "tenant_ref": tenant,
            "entity_ref": entity,
            "store_ref": store,
            "scope_grant_authority_sha256": grant,
            "source_evidence_sha256": source_hash,
            "as_of": cutoff.isoformat(),
        }

    @staticmethod
    def _scope_columns(scope: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "scope_grant_authority_sha256": scope[
                "scope_grant_authority_sha256"
            ],
            "source_evidence_sha256": scope["source_evidence_sha256"],
            "scope_as_of": datetime.fromisoformat(scope["as_of"]),
        }

    @classmethod
    def _scope_from_row(cls, row: AfterSalesEventRow) -> dict[str, Any]:
        return {
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
            "source_evidence_sha256": row.source_evidence_sha256,
            "as_of": cls._aware(row.scope_as_of).isoformat(),
        }

    @classmethod
    def _same_scope(cls, row: AfterSalesEventRow, scope: Mapping[str, Any]) -> bool:
        return bool(
            row.tenant_ref == scope["tenant_ref"]
            and row.entity_ref == scope["entity_ref"]
            and row.store_ref == scope["store_ref"]
            and row.scope_grant_authority_sha256
            == scope["scope_grant_authority_sha256"]
        )

    @classmethod
    def _require_evidence(
        cls,
        session: Session,
        evidence_id: str,
    ) -> EvidenceRecordRow:
        evidence = session.get(EvidenceRecordRow, evidence_id)
        if evidence is None or session.get(EvidenceBlobRow, evidence.blob_sha256) is None:
            raise AfterSalesLedgerError("after-sales event requires existing Evidence")
        return evidence

    @staticmethod
    def _aware(value: datetime | None) -> datetime:
        if value is None:
            raise AfterSalesLedgerError("scope_as_of cannot be null")
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
                default=str,
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _claim_status(rows: list[AfterSalesEventRow]) -> str:
        claim_rows = [
            row
            for row in rows
            if row.claim_status != AfterSalesClaimStatus.NONE.value
        ]
        if not claim_rows:
            return "none"
        latest = max(
            claim_rows,
            key=lambda row: (row.effective_time, row.recorded_at, row.event_id),
        )
        return latest.claim_status


__all__ = [
    "AfterSalesClaimStatus",
    "AfterSalesDirection",
    "AfterSalesEvent",
    "AfterSalesEventKind",
    "AfterSalesEventRow",
    "AfterSalesImpact",
    "AfterSalesLedgerError",
    "AfterSalesLedgerService",
]
