from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    or_,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import ChargeType, new_id
from .evidence import EvidenceRecordRow, parse_timestamp
from .facts import FactRecordRow
from .ozon_contracts import OzonRecordType
from .sql_repository import Base

SCOPE_COMPLETE_SQL = (
    "("
    "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
    "AND scope_grant_authority_sha256 IS NULL "
    "AND source_evidence_sha256 IS NULL AND scope_as_of IS NULL"
    ") OR ("
    "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
    "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
    "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
    "AND scope_grant_authority_sha256 IS NOT NULL "
    "AND length(scope_grant_authority_sha256) = 64 "
    "AND source_evidence_sha256 IS NOT NULL "
    "AND length(source_evidence_sha256) = 64 "
    "AND scope_as_of IS NOT NULL"
    ")"
)
ACTUAL_PROFIT_COST_TYPES = frozenset(
    {
        ChargeType.PRODUCT_COST,
        ChargeType.DOMESTIC_LOGISTICS,
        ChargeType.INTERNATIONAL_LOGISTICS,
        ChargeType.PACKAGING,
        ChargeType.WAREHOUSING,
        ChargeType.CUSTOMS,
        ChargeType.TAX,
        ChargeType.LAST_MILE,
        ChargeType.PLATFORM_FEE,
        ChargeType.ADVERTISING,
        ChargeType.RETURN,
        ChargeType.FX,
        ChargeType.CAPITAL_COST,
        ChargeType.CUSTOMER_COMPENSATION,
        ChargeType.DAMAGE,
    }
)
PROFIT_COST_VALUES_SQL = ", ".join(
    f"'{item.value}'" for item in sorted(ACTUAL_PROFIT_COST_TYPES, key=lambda item: item.value)
)
PROFIT_COST_ENTRY_SQL = (
    "(profit_cost_type IS NULL AND entry_kind <> 'bank_payment') OR ("
    "tenant_ref IS NOT NULL AND entry_kind = 'bank_payment' "
    f"AND profit_cost_type IN ({PROFIT_COST_VALUES_SQL}) AND amount <= 0"
    ")"
)
SUPPLIER_PAYMENT_BINDING_SQL = (
    "("
    "supplier_invoice_id IS NULL AND supplier_ref IS NULL "
    "AND payment_approval_id IS NULL AND payment_command_id IS NULL"
    ") OR ("
    "supplier_invoice_id IS NOT NULL AND length(supplier_invoice_id) > 0 "
    "AND supplier_ref IS NOT NULL AND length(supplier_ref) > 0 "
    "AND payment_approval_id IS NOT NULL "
    "AND length(payment_approval_id) > 0 "
    "AND payment_command_id IS NOT NULL "
    "AND length(payment_command_id) > 0 "
    "AND tenant_ref IS NOT NULL "
    "AND entry_kind = 'bank_payment' AND amount < 0"
    ")"
)


class FeeSignRule(StrEnum):
    PRESERVE = "preserve"
    ABSOLUTE_INFLOW = "absolute_inflow"
    ABSOLUTE_OUTFLOW = "absolute_outflow"


class FinanceEntryKind(StrEnum):
    ORDER_RECEIVABLE = "order_receivable"
    PLATFORM_FEE = "platform_fee"
    RETURN_ADJUSTMENT = "return_adjustment"
    PLATFORM_SETTLEMENT = "platform_settlement"
    BANK_RECEIPT = "bank_receipt"
    BANK_PAYMENT = "bank_payment"
    CASH_ADJUSTMENT = "cash_adjustment"


class CashPlanStatus(StrEnum):
    COMMITTED = "committed"
    SCENARIO = "scenario"


class FeeMappingRow(Base):
    __tablename__ = "fee_mappings"
    __table_args__ = (
        CheckConstraint(
            SCOPE_COMPLETE_SQL,
            name="ck_fee_mappings_scope_complete",
        ),
        Index(
            "uq_fee_mapping_legacy_version",
            "provider",
            "raw_code",
            "effective_from",
            "version",
            unique=True,
            sqlite_where=text("tenant_ref IS NULL"),
            postgresql_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_fee_mapping_scoped_version",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "provider",
            "raw_code",
            "effective_from",
            "version",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "ix_fee_mapping_scope_lookup",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "provider",
            "raw_code",
            "effective_from",
            "recorded_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    raw_code: Mapped[str] = mapped_column(String, nullable=False)
    canonical_type: Mapped[str] = mapped_column(String, nullable=False)
    sign_rule: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey(EvidenceRecordRow.id), nullable=False)
    approved_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    source_evidence_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    scope_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class FxRateRow(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        CheckConstraint(
            SCOPE_COMPLETE_SQL,
            name="ck_fx_rates_scope_complete",
        ),
        Index(
            "uq_fx_rate_legacy_observation",
            "base_currency",
            "quote_currency",
            "effective_at",
            "source",
            "version",
            unique=True,
            sqlite_where=text("tenant_ref IS NULL"),
            postgresql_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_fx_rate_scoped_observation",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "base_currency",
            "quote_currency",
            "effective_at",
            "source",
            "version",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "ix_fx_rate_scope_lookup",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "base_currency",
            "quote_currency",
            "source",
            "effective_at",
            "recorded_at",
        ),
        Index(
            "uq_fx_rate_scoped_intake_idempotency",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            unique=True,
            sqlite_where=text(
                "tenant_ref IS NOT NULL AND idempotency_key IS NOT NULL"
            ),
            postgresql_where=text(
                "tenant_ref IS NOT NULL AND idempotency_key IS NOT NULL"
            ),
        ),
        CheckConstraint(
            "(expires_at IS NULL AND source_type IS NULL AND authority IS NULL "
            "AND purposes_json IS NULL AND intake_content_sha256 IS NULL "
            "AND idempotency_key IS NULL) OR "
            "(expires_at IS NOT NULL AND expires_at > effective_at "
            "AND source_type IS NOT NULL AND length(source_type) > 0 "
            "AND authority IS NOT NULL AND length(authority) > 0 "
            "AND purposes_json IS NOT NULL "
            "AND intake_content_sha256 IS NOT NULL "
            "AND length(intake_content_sha256) = 64 "
            "AND idempotency_key IS NOT NULL AND length(idempotency_key) > 0)",
            name="ck_fx_rates_complete_intake_metadata",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    authority: Mapped[str | None] = mapped_column(String(300), nullable=True)
    purposes_json: Mapped[list[str] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    intake_content_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(180), nullable=True
    )
    evidence_id: Mapped[str] = mapped_column(ForeignKey(EvidenceRecordRow.id), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    source_evidence_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    scope_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class FinanceEntryRow(Base):
    __tablename__ = "finance_entries"
    __table_args__ = (
        CheckConstraint(
            SCOPE_COMPLETE_SQL,
            name="ck_finance_entries_scope_complete",
        ),
        CheckConstraint(
            PROFIT_COST_ENTRY_SQL,
            name="ck_finance_entries_profit_cost_type",
        ),
        CheckConstraint(
            SUPPLIER_PAYMENT_BINDING_SQL,
            name="ck_finance_entries_supplier_payment_binding",
        ),
        Index(
            "uq_finance_entry_legacy_source",
            "source",
            "source_ref",
            "entry_kind",
            unique=True,
            sqlite_where=text("tenant_ref IS NULL"),
            postgresql_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_finance_entry_scoped_source",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source",
            "source_ref",
            "entry_kind",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "uq_finance_entry_legacy_fact",
            "source_fact_id",
            unique=True,
            sqlite_where=text(
                "tenant_ref IS NULL AND source_fact_id IS NOT NULL"
            ),
            postgresql_where=text(
                "tenant_ref IS NULL AND source_fact_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_finance_entry_scoped_fact",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source_fact_id",
            unique=True,
            sqlite_where=text(
                "tenant_ref IS NOT NULL AND source_fact_id IS NOT NULL"
            ),
            postgresql_where=text(
                "tenant_ref IS NOT NULL AND source_fact_id IS NOT NULL"
            ),
        ),
        Index(
            "ix_finance_entry_scope_reconciliation",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "reconciliation_key",
            "effective_at",
            "recorded_at",
        ),
        Index(
            "ix_finance_entry_scope_profit",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "reconciliation_key",
            "profit_cost_type",
            "effective_at",
            "recorded_at",
        ),
        Index(
            "ix_finance_entry_scope_supplier_invoice",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "supplier_invoice_id",
            "effective_at",
            "recorded_at",
            sqlite_where=text("supplier_invoice_id IS NOT NULL"),
            postgresql_where=text("supplier_invoice_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    reconciliation_key: Mapped[str] = mapped_column(String, nullable=False)
    raw_fee_code: Mapped[str | None] = mapped_column(String, nullable=True)
    profit_cost_type: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey(EvidenceRecordRow.id), nullable=False)
    source_fact_id: Mapped[str | None] = mapped_column(ForeignKey(FactRecordRow.id), nullable=True)
    supplier_invoice_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    supplier_ref: Mapped[str | None] = mapped_column(
        String(240),
        nullable=True,
    )
    payment_approval_id: Mapped[str | None] = mapped_column(
        ForeignKey("approvals.id"),
        nullable=True,
    )
    payment_command_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    source_evidence_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    scope_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class ReconciliationRunRow(Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = (
        CheckConstraint(
            SCOPE_COMPLETE_SQL,
            name="ck_reconciliation_runs_scope_complete",
        ),
        Index(
            "ix_reconciliation_scope_key_recorded",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "reconciliation_key",
            "recorded_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    reconciliation_key: Mapped[str] = mapped_column(String, nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_source: Mapped[str] = mapped_column(String, nullable=False)
    tolerance_ratio: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    source_evidence_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    scope_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class CashPlanItemRow(Base):
    __tablename__ = "cash_plan_items"
    __table_args__ = (
        CheckConstraint(
            SCOPE_COMPLETE_SQL,
            name="ck_cash_plan_items_scope_complete",
        ),
        Index(
            "uq_cash_plan_legacy_source",
            "source",
            "source_ref",
            unique=True,
            sqlite_where=text("tenant_ref IS NULL"),
            postgresql_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_cash_plan_scoped_source",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source",
            "source_ref",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "ix_cash_plan_scope_window",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "expected_at",
            "recorded_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    expected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    probability: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey(EvidenceRecordRow.id), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    source_evidence_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    scope_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


@dataclass(frozen=True, slots=True)
class FeeMapping:
    id: str
    provider: str
    raw_code: str
    canonical_type: str
    sign_rule: str
    version: int
    effective_from: str
    effective_until: str | None
    evidence_id: str
    approved_by: str
    recorded_at: str
    scope: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class FxRate:
    id: str
    base_currency: str
    quote_currency: str
    rate: str
    version: int
    effective_at: str
    source: str
    evidence_id: str
    created_by: str
    recorded_at: str
    scope: dict[str, Any] | None = None
    expires_at: str | None = None
    source_type: str | None = None
    authority: str | None = None
    purposes: tuple[str, ...] = ()
    intake_content_sha256: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class FinanceEntry:
    id: str
    entry_kind: str
    source: str
    source_ref: str
    reconciliation_key: str
    raw_fee_code: str | None
    profit_cost_type: str | None
    amount: str
    currency: str
    effective_at: str
    evidence_id: str
    source_fact_id: str | None
    supplier_invoice_id: str | None
    supplier_ref: str | None
    payment_approval_id: str | None
    payment_command_id: str | None
    review_required: bool
    created_by: str
    recorded_at: str
    scope: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class CashPlanItem:
    id: str
    source: str
    source_ref: str
    category: str
    amount: str
    currency: str
    expected_at: str
    probability: str
    status: str
    evidence_id: str
    created_by: str
    recorded_at: str
    scope: dict[str, Any] | None = None


class FinanceService:
    def __init__(self, engine) -> None:
        self.engine = engine

    def register_fee_mapping(
        self,
        *,
        provider: str,
        raw_code: str,
        canonical_type: ChargeType,
        sign_rule: FeeSignRule,
        effective_from: str,
        effective_until: str | None,
        evidence_id: str,
        approved_by: str,
        scope_authority: dict[str, Any] | None = None,
    ) -> FeeMapping:
        provider = provider.strip().lower()
        raw_code = raw_code.strip()
        approved_by = approved_by.strip()
        if not provider or not raw_code or not approved_by:
            raise ValueError("Fee mapping requires provider, raw code, and approver")
        start = parse_timestamp(effective_from, "effective_from")
        end = parse_timestamp(effective_until, "effective_until") if effective_until else None
        if end is not None and end <= start:
            raise ValueError("effective_until must be later than effective_from")
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            evidence = self._require_evidence(session, evidence_id)
            scope = self._scope_authority(
                scope_authority,
                evidence_sha256=evidence.blob_sha256,
            )
            latest_query = select(FeeMappingRow).where(
                FeeMappingRow.provider == provider,
                FeeMappingRow.raw_code == raw_code,
                FeeMappingRow.effective_from == start,
            )
            latest_query = self._scope_query(
                latest_query,
                FeeMappingRow,
                scope,
            )
            latest = session.scalar(
                latest_query
                .order_by(FeeMappingRow.version.desc())
                .limit(1)
            )
            if latest is not None and (
                latest.canonical_type == canonical_type.value
                and latest.sign_rule == sign_rule.value
                and (self._aware(latest.effective_until) if latest.effective_until else None) == end
                and latest.evidence_id == evidence_id
                and self._scope_matches(latest, scope)
            ):
                return self._fee_mapping(latest)
            row = FeeMappingRow(
                id=new_id("fee_map"),
                provider=provider,
                raw_code=raw_code,
                canonical_type=canonical_type.value,
                sign_rule=sign_rule.value,
                version=1 if latest is None else latest.version + 1,
                effective_from=start,
                effective_until=end,
                evidence_id=evidence_id,
                approved_by=approved_by,
                recorded_at=now,
                **self._scope_columns(scope),
            )
            session.add(row)
            session.flush()
            return self._fee_mapping(row)

    def list_fee_mappings(self, *, provider: str | None = None) -> list[FeeMapping]:
        query = select(FeeMappingRow).where(FeeMappingRow.tenant_ref.is_(None))
        if provider:
            query = query.where(FeeMappingRow.provider == provider.strip().lower())
        query = query.order_by(
            FeeMappingRow.provider,
            FeeMappingRow.raw_code,
            FeeMappingRow.effective_from.desc(),
            FeeMappingRow.version.desc(),
        )
        with Session(self.engine) as session:
            return [self._fee_mapping(row) for row in session.scalars(query).all()]

    def resolve_fee_mapping(self, *, provider: str, raw_code: str, effective_at: str) -> FeeMapping | None:
        provider = provider.strip().lower()
        raw_code = raw_code.strip()
        if not provider or not raw_code:
            raise ValueError("Fee mapping lookup requires provider and raw code")
        effective = parse_timestamp(effective_at, "effective_at")
        with Session(self.engine) as session:
            row = self._resolve_fee_mapping(
                session,
                provider=provider,
                raw_code=raw_code,
                effective_at=effective,
                scope=None,
            )
            return self._fee_mapping(row) if row is not None else None

    def add_fx_rate(
        self,
        *,
        base_currency: str,
        quote_currency: str,
        rate: Decimal,
        effective_at: str,
        source: str,
        evidence_id: str,
        created_by: str,
        scope_authority: dict[str, Any] | None = None,
        expires_at: str | None = None,
        source_type: str | None = None,
        authority: str | None = None,
        purposes: list[str] | tuple[str, ...] | None = None,
        intake_content_sha256: str | None = None,
        idempotency_key: str | None = None,
    ) -> FxRate:
        rate = self._finite_decimal(rate, "FX rate")
        base = self._currency(base_currency)
        quote = self._currency(quote_currency)
        source = source.strip()
        if base == quote or rate <= 0 or not source:
            raise ValueError("FX rate requires distinct currencies, a positive rate, and a source")
        effective = parse_timestamp(effective_at, "effective_at")
        metadata_values = (
            expires_at,
            source_type,
            authority,
            purposes,
            intake_content_sha256,
            idempotency_key,
        )
        complete_metadata = any(value is not None for value in metadata_values)
        expires = None
        normalized_purposes: list[str] | None = None
        normalized_source_type = None
        normalized_authority = None
        normalized_intake_hash = None
        normalized_idempotency = None
        if complete_metadata:
            if any(value is None for value in metadata_values):
                raise ValueError("Complete FX intake metadata is all-or-none")
            expires = parse_timestamp(str(expires_at), "expires_at")
            if expires <= effective:
                raise ValueError("expires_at must be later than effective_at")
            normalized_source_type = str(source_type).strip()
            normalized_authority = str(authority).strip()
            normalized_purposes = sorted(
                {
                    str(item).strip()
                    for item in (purposes or ())
                    if str(item).strip()
                }
            )
            normalized_intake_hash = str(intake_content_sha256).strip().lower()
            normalized_idempotency = str(idempotency_key).strip()
            if (
                not normalized_source_type
                or not normalized_authority
                or not normalized_purposes
                or not normalized_idempotency
            ):
                raise ValueError("Complete FX intake metadata cannot contain empty values")
            self._require_sha256(
                normalized_intake_hash,
                "intake_content_sha256",
            )
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            evidence = self._require_evidence(session, evidence_id)
            scope = self._scope_authority(
                scope_authority,
                evidence_sha256=evidence.blob_sha256,
            )
            if complete_metadata and scope is None:
                raise ValueError("Complete FX intake metadata requires exact scope authority")
            if normalized_idempotency is not None:
                replay_query = select(FxRateRow).where(
                    FxRateRow.idempotency_key == normalized_idempotency,
                )
                replay_query = self._scope_query(
                    replay_query,
                    FxRateRow,
                    scope,
                )
                replay = session.scalar(replay_query.limit(1))
                if replay is not None:
                    replay_matches = (
                        replay.intake_content_sha256 == normalized_intake_hash
                        and replay.base_currency == base
                        and replay.quote_currency == quote
                        and replay.rate == rate
                        and self._aware(replay.effective_at) == effective
                        and (
                            self._aware(replay.expires_at)
                            if replay.expires_at
                            else None
                        )
                        == expires
                        and replay.source == source
                        and replay.source_type == normalized_source_type
                        and replay.authority == normalized_authority
                        and replay.purposes_json == normalized_purposes
                        and replay.evidence_id == evidence_id
                    )
                    if not replay_matches:
                        raise ValueError(
                            "FX idempotency key conflicts with immutable intake content"
                        )
                    return self._fx_rate(replay)
            latest_query = select(FxRateRow).where(
                FxRateRow.base_currency == base,
                FxRateRow.quote_currency == quote,
                FxRateRow.effective_at == effective,
                FxRateRow.source == source,
            )
            latest_query = self._scope_query(
                latest_query,
                FxRateRow,
                scope,
            )
            latest = session.scalar(
                latest_query
                .order_by(FxRateRow.version.desc())
                .limit(1)
            )
            if (
                latest is not None
                and latest.rate == rate
                and latest.evidence_id == evidence_id
                and self._scope_matches(latest, scope)
                and latest.expires_at == expires
                and latest.source_type == normalized_source_type
                and latest.authority == normalized_authority
                and latest.purposes_json == normalized_purposes
                and latest.intake_content_sha256 == normalized_intake_hash
                and latest.idempotency_key == normalized_idempotency
            ):
                return self._fx_rate(latest)
            row = FxRateRow(
                id=new_id("fx"),
                base_currency=base,
                quote_currency=quote,
                rate=rate,
                version=1 if latest is None else latest.version + 1,
                effective_at=effective,
                source=source,
                expires_at=expires,
                source_type=normalized_source_type,
                authority=normalized_authority,
                purposes_json=normalized_purposes,
                intake_content_sha256=normalized_intake_hash,
                idempotency_key=normalized_idempotency,
                evidence_id=evidence_id,
                created_by=created_by,
                recorded_at=now,
                **self._scope_columns(scope),
            )
            session.add(row)
            session.flush()
            return self._fx_rate(row)

    def list_fx_rates(self, *, base_currency: str | None = None) -> list[FxRate]:
        query = select(FxRateRow).where(FxRateRow.tenant_ref.is_(None))
        if base_currency:
            query = query.where(FxRateRow.base_currency == self._currency(base_currency))
        query = query.order_by(FxRateRow.effective_at.desc(), FxRateRow.version.desc(), FxRateRow.id)
        with Session(self.engine) as session:
            return [self._fx_rate(row) for row in session.scalars(query).all()]

    def ingest_fact(self, fact_id: str, *, created_by: str) -> FinanceEntry:
        with Session(self.engine) as session:
            fact = session.get(FactRecordRow, fact_id)
            if fact is None:
                raise KeyError(f"Unknown fact: {fact_id}")
            if fact.tenant_ref is not None:
                raise ValueError(
                    "Native scoped Fact accounting ingestion is not authorized; "
                    "use an independently reviewed scoped finance entry"
                )
            scope_authority = None
            existing_query = select(FinanceEntryRow).where(
                FinanceEntryRow.source_fact_id == fact_id
            )
            existing_query = self._scope_query(
                existing_query,
                FinanceEntryRow,
                scope_authority,
            )
            existing = session.scalar(existing_query)
            if existing is not None:
                return self._entry(existing)
            payload = fact.payload_json
            fact_type = OzonRecordType(fact.fact_type)
            if fact_type is OzonRecordType.ORDER:
                entry_kind = FinanceEntryKind.ORDER_RECEIVABLE
                amount = Decimal(payload["gross_revenue"])
                raw_fee_code = None
                review_required = False
            elif fact_type is OzonRecordType.FEE:
                entry_kind = FinanceEntryKind.PLATFORM_FEE
                amount = Decimal(payload["amount"])
                raw_fee_code = payload["fee_type"]
                review_required = False
            elif fact_type is OzonRecordType.SETTLEMENT:
                entry_kind = FinanceEntryKind.PLATFORM_SETTLEMENT
                amount = Decimal(payload["amount"])
                raw_fee_code = None
                review_required = False
            elif fact_type is OzonRecordType.ACCRUAL:
                raise ValueError(
                    "Ozon accrual facts require an approved accounting classification before finance ingestion"
                )
            elif payload.get("amount") and payload.get("currency"):
                entry_kind = FinanceEntryKind.RETURN_ADJUSTMENT
                amount = Decimal(payload["amount"])
                raw_fee_code = None
                review_required = True
            else:
                raise ValueError("Return fact has no financial amount to ingest")

        return self.record_entry(
            entry_kind=entry_kind,
            source="ozon_formal_fact",
            source_ref=fact_id,
            reconciliation_key=payload["external_id"],
            raw_fee_code=raw_fee_code,
            amount=amount,
            currency=payload["currency"],
            effective_at=payload["effective_at"],
            evidence_id=fact.evidence_id,
            source_fact_id=fact_id,
            review_required=review_required,
            created_by=created_by,
            scope_authority=scope_authority,
        )

    def record_entry(
        self,
        *,
        entry_kind: FinanceEntryKind,
        source: str,
        source_ref: str,
        reconciliation_key: str,
        amount: Decimal,
        currency: str,
        effective_at: str,
        evidence_id: str,
        created_by: str,
        raw_fee_code: str | None = None,
        profit_cost_type: ChargeType | None = None,
        source_fact_id: str | None = None,
        supplier_invoice_id: str | None = None,
        supplier_ref: str | None = None,
        payment_approval_id: str | None = None,
        payment_command_id: str | None = None,
        review_required: bool = False,
        scope_authority: dict[str, Any] | None = None,
    ) -> FinanceEntry:
        source = source.strip()
        source_ref = source_ref.strip()
        reconciliation_key = reconciliation_key.strip()
        raw_fee_code = raw_fee_code.strip() if raw_fee_code else None
        supplier_invoice_id = (
            supplier_invoice_id.strip() if supplier_invoice_id else None
        )
        supplier_ref = supplier_ref.strip() if supplier_ref else None
        payment_approval_id = (
            payment_approval_id.strip() if payment_approval_id else None
        )
        payment_command_id = (
            payment_command_id.strip() if payment_command_id else None
        )
        payment_binding = (
            supplier_invoice_id,
            supplier_ref,
            payment_approval_id,
            payment_command_id,
        )
        if any(payment_binding) and not all(payment_binding):
            raise ValueError(
                "Supplier payment binding must be complete or empty"
            )
        if profit_cost_type is not None and not isinstance(
            profit_cost_type,
            ChargeType,
        ):
            profit_cost_type = ChargeType(profit_cost_type)
        if not source or not source_ref or not reconciliation_key:
            raise ValueError("Finance entry requires source, source reference, and reconciliation key")
        if entry_kind is FinanceEntryKind.PLATFORM_FEE and not raw_fee_code:
            raise ValueError("Platform fee entry requires its raw fee code")
        if entry_kind is FinanceEntryKind.BANK_PAYMENT:
            if profit_cost_type not in ACTUAL_PROFIT_COST_TYPES:
                raise ValueError(
                    "Bank payment requires one supported actual profit cost type"
                )
            if profit_cost_type is ChargeType.PLATFORM_FEE:
                raise ValueError(
                    "Platform fee must be classified by an exact-scope fee mapping"
                )
        elif profit_cost_type is not None:
            raise ValueError(
                "profit_cost_type is only allowed for scoped bank payments"
            )
        amount = self._finite_decimal(amount, "Finance entry amount")
        if entry_kind is FinanceEntryKind.BANK_PAYMENT and amount > 0:
            raise ValueError("Bank payment amount must be zero or an outflow")
        if all(payment_binding) and (
            entry_kind is not FinanceEntryKind.BANK_PAYMENT
            or amount >= 0
            or profit_cost_type is not ChargeType.PRODUCT_COST
        ):
            raise ValueError(
                "Supplier invoice payment must be a negative product-cost bank payment"
            )
        currency = self._currency(currency)
        effective = parse_timestamp(effective_at, "effective_at")
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            evidence = self._require_evidence(session, evidence_id)
            scope = self._scope_authority(
                scope_authority,
                evidence_sha256=evidence.blob_sha256,
            )
            if entry_kind is FinanceEntryKind.BANK_PAYMENT and scope is None:
                raise ValueError(
                    "Bank payment actual cost requires native scope authority"
                )
            if all(payment_binding):
                self._require_supplier_payment_binding(
                    session,
                    supplier_invoice_id=supplier_invoice_id,
                    supplier_ref=supplier_ref,
                    payment_approval_id=payment_approval_id,
                    payment_command_id=payment_command_id,
                    currency=currency,
                    scope=scope,
                )
            existing_query = select(FinanceEntryRow).where(
                FinanceEntryRow.source == source,
                FinanceEntryRow.source_ref == source_ref,
                FinanceEntryRow.entry_kind == entry_kind.value,
            )
            existing_query = self._scope_query(
                existing_query,
                FinanceEntryRow,
                scope,
            )
            existing = session.scalar(existing_query)
            if existing is not None:
                if not self._entry_matches(
                    existing,
                    reconciliation_key=reconciliation_key,
                    raw_fee_code=raw_fee_code,
                    profit_cost_type=(
                        profit_cost_type.value if profit_cost_type else None
                    ),
                    amount=amount,
                    currency=currency,
                    effective_at=effective,
                    evidence_id=evidence_id,
                    source_fact_id=source_fact_id,
                    supplier_invoice_id=supplier_invoice_id,
                    supplier_ref=supplier_ref,
                    payment_approval_id=payment_approval_id,
                    payment_command_id=payment_command_id,
                    review_required=review_required,
                    scope=scope,
                ):
                    raise ValueError("Finance entry idempotency key conflicts with existing values")
                return self._entry(existing)
            row = FinanceEntryRow(
                id=new_id("fin"),
                entry_kind=entry_kind.value,
                source=source,
                source_ref=source_ref,
                reconciliation_key=reconciliation_key,
                raw_fee_code=raw_fee_code,
                profit_cost_type=(
                    profit_cost_type.value if profit_cost_type else None
                ),
                amount=amount,
                currency=currency,
                effective_at=effective,
                evidence_id=evidence_id,
                source_fact_id=source_fact_id,
                supplier_invoice_id=supplier_invoice_id,
                supplier_ref=supplier_ref,
                payment_approval_id=payment_approval_id,
                payment_command_id=payment_command_id,
                review_required=review_required,
                created_by=created_by,
                recorded_at=now,
                **self._scope_columns(scope),
            )
            session.add(row)
            session.flush()
            return self._entry(row)

    def list_entries(
        self, *, reconciliation_key: str | None = None, entry_kind: FinanceEntryKind | None = None
    ) -> list[FinanceEntry]:
        query = select(FinanceEntryRow).where(
            FinanceEntryRow.tenant_ref.is_(None)
        )
        if reconciliation_key:
            query = query.where(FinanceEntryRow.reconciliation_key == reconciliation_key)
        if entry_kind:
            query = query.where(FinanceEntryRow.entry_kind == entry_kind.value)
        query = query.order_by(FinanceEntryRow.effective_at, FinanceEntryRow.id)
        with Session(self.engine) as session:
            return [self._entry(row) for row in session.scalars(query).all()]

    def unknown_fee_entries(self, *, provider: str = "ozon") -> list[FinanceEntry]:
        provider = provider.strip().lower()
        with Session(self.engine) as session:
            rows = session.scalars(
                select(FinanceEntryRow)
                .where(
                    FinanceEntryRow.tenant_ref.is_(None),
                    FinanceEntryRow.entry_kind
                    == FinanceEntryKind.PLATFORM_FEE.value,
                )
                .order_by(FinanceEntryRow.effective_at, FinanceEntryRow.id)
            ).all()
            return [
                self._entry(row)
                for row in rows
                if self._resolve_fee_mapping(
                    session,
                    provider=provider,
                    raw_code=row.raw_fee_code or "",
                    effective_at=row.effective_at,
                    scope=None,
                )
                is None
            ]

    def read_scoped_sources(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
        max_facts: int = 5000,
        max_entries: int = 5000,
        max_reconciliations: int = 5000,
    ) -> dict[str, Any]:
        context = self._scope_context(
            {
                "tenant_ref": tenant_ref,
                "entity_ref": entity_ref,
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    scope_grant_authority_sha256
                ),
                "scope_as_of": as_of,
            }
        )
        if context is None:
            raise ValueError("Native finance read scope is required")
        for name, limit in (
            ("max_facts", max_facts),
            ("max_entries", max_entries),
            ("max_reconciliations", max_reconciliations),
        ):
            if limit < 1 or limit > 50_000:
                raise ValueError(f"{name} must be between 1 and 50000")
        cutoff = context["scope_as_of"]
        with Session(self.engine) as session:
            facts = list(
                session.scalars(
                    select(FactRecordRow)
                    .where(
                        FactRecordRow.tenant_ref == context["tenant_ref"],
                        FactRecordRow.entity_ref == context["entity_ref"],
                        FactRecordRow.store_ref == context["store_ref"],
                        FactRecordRow.scope_grant_authority_sha256
                        == context["scope_grant_authority_sha256"],
                        FactRecordRow.fact_type.in_(
                            (
                                OzonRecordType.ORDER.value,
                                OzonRecordType.ACCRUAL.value,
                                OzonRecordType.SETTLEMENT.value,
                                OzonRecordType.FEE.value,
                                OzonRecordType.RETURN.value,
                            )
                        ),
                        FactRecordRow.scope_as_of <= cutoff,
                        FactRecordRow.effective_at <= cutoff,
                        FactRecordRow.recorded_at <= cutoff,
                    )
                    .order_by(
                        FactRecordRow.effective_at,
                        FactRecordRow.recorded_at,
                        FactRecordRow.id,
                    )
                    .limit(max_facts + 1)
                ).all()
            )
            entries = list(
                session.scalars(
                    select(FinanceEntryRow)
                    .where(
                        FinanceEntryRow.tenant_ref
                        == context["tenant_ref"],
                        FinanceEntryRow.entity_ref
                        == context["entity_ref"],
                        FinanceEntryRow.store_ref == context["store_ref"],
                        FinanceEntryRow.scope_grant_authority_sha256
                        == context["scope_grant_authority_sha256"],
                        FinanceEntryRow.scope_as_of <= cutoff,
                        FinanceEntryRow.effective_at <= cutoff,
                        FinanceEntryRow.recorded_at <= cutoff,
                    )
                    .order_by(
                        FinanceEntryRow.effective_at,
                        FinanceEntryRow.recorded_at,
                        FinanceEntryRow.id,
                    )
                    .limit(max_entries + 1)
                ).all()
            )
            reconciliations = list(
                session.scalars(
                    select(ReconciliationRunRow)
                    .where(
                        ReconciliationRunRow.tenant_ref
                        == context["tenant_ref"],
                        ReconciliationRunRow.entity_ref
                        == context["entity_ref"],
                        ReconciliationRunRow.store_ref
                        == context["store_ref"],
                        ReconciliationRunRow.scope_grant_authority_sha256
                        == context["scope_grant_authority_sha256"],
                        ReconciliationRunRow.scope_as_of <= cutoff,
                        ReconciliationRunRow.recorded_at <= cutoff,
                    )
                    .order_by(
                        ReconciliationRunRow.recorded_at,
                        ReconciliationRunRow.id,
                    )
                    .limit(max_reconciliations + 1)
                ).all()
            )

            payload = {
                "contract_id": "kjds-scoped-finance-read-source-v1",
                "as_of": cutoff.isoformat(),
                "scope": self._serialized_scope(context),
                "facts": [
                    {
                        "id": row.id,
                        "source": row.source,
                        "fact_type": row.fact_type,
                        "natural_key": row.natural_key,
                        "contract_version": row.contract_version,
                        "payload": row.payload_json,
                        "payload_hash": row.payload_hash,
                        "effective_at": self._aware(
                            row.effective_at
                        ).isoformat(),
                        "recorded_at": self._aware(
                            row.recorded_at
                        ).isoformat(),
                        "evidence_id": row.evidence_id,
                        "product_id": row.product_id,
                        "resolution_status": row.resolution_status,
                        "source_evidence_sha256": (
                            row.source_evidence_sha256
                        ),
                        "scope_as_of": self._aware(
                            row.scope_as_of
                        ).isoformat(),
                    }
                    for row in facts[:max_facts]
                ],
                "entries": [
                    {
                        "id": row.id,
                        "entry_kind": row.entry_kind,
                        "source": row.source,
                        "source_ref": row.source_ref,
                        "reconciliation_key": row.reconciliation_key,
                        "raw_fee_code": row.raw_fee_code,
                        "profit_cost_type": row.profit_cost_type,
                        "amount": str(row.amount),
                        "currency": row.currency,
                        "effective_at": self._aware(
                            row.effective_at
                        ).isoformat(),
                        "evidence_id": row.evidence_id,
                        "source_fact_id": row.source_fact_id,
                        "supplier_invoice_id": row.supplier_invoice_id,
                        "supplier_ref": row.supplier_ref,
                        "payment_approval_id": row.payment_approval_id,
                        "payment_command_id": row.payment_command_id,
                        "review_required": row.review_required,
                        "created_by": row.created_by,
                        "recorded_at": self._aware(
                            row.recorded_at
                        ).isoformat(),
                        "source_evidence_sha256": (
                            row.source_evidence_sha256
                        ),
                        "scope_as_of": self._aware(
                            row.scope_as_of
                        ).isoformat(),
                    }
                    for row in entries[:max_entries]
                ],
                "reconciliations": [
                    {
                        "id": row.id,
                        "reconciliation_key": row.reconciliation_key,
                        "quote_currency": row.quote_currency,
                        "fx_source": row.fx_source,
                        "tolerance_ratio": str(row.tolerance_ratio),
                        "status": row.status,
                        "snapshot": row.snapshot_json,
                        "created_by": row.created_by,
                        "recorded_at": self._aware(
                            row.recorded_at
                        ).isoformat(),
                        "source_evidence_sha256": (
                            row.source_evidence_sha256
                        ),
                        "scope_as_of": self._aware(
                            row.scope_as_of
                        ).isoformat(),
                    }
                    for row in reconciliations[:max_reconciliations]
                ],
                "truncated": {
                    "facts": len(facts) > max_facts,
                    "entries": len(entries) > max_entries,
                    "reconciliations": (
                        len(reconciliations) > max_reconciliations
                    ),
                },
            }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def read_scoped_profit_authorities(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        scope_grant_authority_sha256: str,
        as_of: str,
        max_fee_mappings: int = 5000,
        max_fx_rates: int = 5000,
    ) -> dict[str, Any]:
        context = self._scope_context(
            {
                "tenant_ref": tenant_ref,
                "entity_ref": entity_ref,
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    scope_grant_authority_sha256
                ),
                "scope_as_of": as_of,
            }
        )
        if context is None:
            raise ValueError("Native profit authority read scope is required")
        for name, limit in (
            ("max_fee_mappings", max_fee_mappings),
            ("max_fx_rates", max_fx_rates),
        ):
            if limit < 1 or limit > 50_000:
                raise ValueError(f"{name} must be between 1 and 50000")
        cutoff = context["scope_as_of"]
        with Session(self.engine) as session:
            mappings = list(
                session.scalars(
                    select(FeeMappingRow)
                    .where(
                        FeeMappingRow.tenant_ref == context["tenant_ref"],
                        FeeMappingRow.entity_ref == context["entity_ref"],
                        FeeMappingRow.store_ref == context["store_ref"],
                        FeeMappingRow.scope_grant_authority_sha256
                        == context["scope_grant_authority_sha256"],
                        FeeMappingRow.scope_as_of <= cutoff,
                        FeeMappingRow.effective_from <= cutoff,
                        FeeMappingRow.recorded_at <= cutoff,
                    )
                    .order_by(
                        FeeMappingRow.effective_from,
                        FeeMappingRow.version,
                        FeeMappingRow.recorded_at,
                        FeeMappingRow.id,
                    )
                    .limit(max_fee_mappings + 1)
                ).all()
            )
            rates = list(
                session.scalars(
                    select(FxRateRow)
                    .where(
                        FxRateRow.tenant_ref == context["tenant_ref"],
                        FxRateRow.entity_ref == context["entity_ref"],
                        FxRateRow.store_ref == context["store_ref"],
                        FxRateRow.scope_grant_authority_sha256
                        == context["scope_grant_authority_sha256"],
                        FxRateRow.scope_as_of <= cutoff,
                        FxRateRow.effective_at <= cutoff,
                        FxRateRow.recorded_at <= cutoff,
                    )
                    .order_by(
                        FxRateRow.effective_at,
                        FxRateRow.version,
                        FxRateRow.recorded_at,
                        FxRateRow.id,
                    )
                    .limit(max_fx_rates + 1)
                ).all()
            )
        payload = {
            "contract_id": "kjds-scoped-profit-authority-source-v1",
            "as_of": cutoff.isoformat(),
            "scope": self._serialized_scope(context),
            "fee_mappings": [
                {
                    "id": row.id,
                    "provider": row.provider,
                    "raw_code": row.raw_code,
                    "canonical_type": row.canonical_type,
                    "sign_rule": row.sign_rule,
                    "version": row.version,
                    "effective_from": self._aware(
                        row.effective_from
                    ).isoformat(),
                    "effective_until": (
                        self._aware(row.effective_until).isoformat()
                        if row.effective_until
                        else None
                    ),
                    "evidence_id": row.evidence_id,
                    "approved_by": row.approved_by,
                    "recorded_at": self._aware(
                        row.recorded_at
                    ).isoformat(),
                    "source_evidence_sha256": row.source_evidence_sha256,
                    "scope_as_of": self._aware(
                        row.scope_as_of
                    ).isoformat(),
                }
                for row in mappings[:max_fee_mappings]
            ],
            "fx_rates": [
                {
                    "id": row.id,
                    "base_currency": row.base_currency,
                    "quote_currency": row.quote_currency,
                    "rate": str(row.rate),
                    "version": row.version,
                    "effective_at": self._aware(
                        row.effective_at
                    ).isoformat(),
                    "expires_at": (
                        self._aware(row.expires_at).isoformat()
                        if row.expires_at
                        else None
                    ),
                    "source": row.source,
                    "source_type": row.source_type,
                    "authority": row.authority,
                    "purposes": list(row.purposes_json or []),
                    "intake_content_sha256": row.intake_content_sha256,
                    "idempotency_key": row.idempotency_key,
                    "evidence_id": row.evidence_id,
                    "created_by": row.created_by,
                    "recorded_at": self._aware(
                        row.recorded_at
                    ).isoformat(),
                    "source_evidence_sha256": row.source_evidence_sha256,
                    "scope_as_of": self._aware(
                        row.scope_as_of
                    ).isoformat(),
                }
                for row in rates[:max_fx_rates]
            ],
            "truncated": {
                "fee_mappings": len(mappings) > max_fee_mappings,
                "fx_rates": len(rates) > max_fx_rates,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def reconcile(
        self,
        reconciliation_key: str,
        *,
        quote_currency: str,
        fx_source: str,
        tolerance_ratio: Decimal,
        created_by: str,
        scope_authority: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tolerance_ratio = self._finite_decimal(tolerance_ratio, "Reconciliation tolerance")
        key = reconciliation_key.strip()
        quote = self._currency(quote_currency)
        fx_source = fx_source.strip()
        created_by = created_by.strip()
        if not key or not fx_source or not created_by or tolerance_ratio < 0 or tolerance_ratio >= 1:
            raise ValueError("Reconciliation requires key, FX source, reviewer, and tolerance in [0, 1)")
        now = datetime.now(UTC)
        scope_context = self._scope_context(scope_authority)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            entries_query = select(FinanceEntryRow).where(
                FinanceEntryRow.reconciliation_key == key
            )
            entries_query = self._scope_query(
                entries_query,
                FinanceEntryRow,
                scope_context,
            )
            if scope_context is not None:
                entries_query = entries_query.where(
                    FinanceEntryRow.scope_as_of
                    <= scope_context["scope_as_of"],
                    FinanceEntryRow.effective_at
                    <= scope_context["scope_as_of"],
                    FinanceEntryRow.recorded_at
                    <= scope_context["scope_as_of"],
                )
            entries = session.scalars(
                entries_query.order_by(
                    FinanceEntryRow.effective_at,
                    FinanceEntryRow.id,
                )
            ).all()
            if not entries:
                raise KeyError(f"No finance entries for reconciliation key: {key}")

            totals = {kind.value: Decimal("0") for kind in FinanceEntryKind}
            counts = {kind.value: 0 for kind in FinanceEntryKind}
            unknown_fees: list[dict[str, str]] = []
            missing_fx: list[dict[str, str]] = []
            review_required: list[str] = []
            applied_fx: list[dict[str, str]] = []
            applied_mappings: list[dict[str, str]] = []
            self_review_dependency_keys: set[tuple[str, str]] = set()
            evidence_hash_by_id: dict[str, str] = {}
            for entry in entries:
                if entry.created_by == created_by:
                    self_review_dependency_keys.add(("finance_entry", entry.id))
                evidence = session.get(EvidenceRecordRow, entry.evidence_id)
                if evidence is not None:
                    evidence_hash_by_id[evidence.id] = evidence.blob_sha256
                    if evidence.created_by == created_by:
                        self_review_dependency_keys.add(("evidence", evidence.id))
                amount = entry.amount
                if entry.entry_kind == FinanceEntryKind.PLATFORM_FEE.value:
                    mapping = self._resolve_fee_mapping(
                        session,
                        provider="ozon",
                        raw_code=entry.raw_fee_code or "",
                        effective_at=entry.effective_at,
                        scope=scope_context,
                    )
                    if mapping is None:
                        unknown_fees.append(
                            {"entry_id": entry.id, "raw_fee_code": entry.raw_fee_code or "", "amount": str(amount)}
                        )
                        continue
                    amount = self._apply_sign_rule(amount, FeeSignRule(mapping.sign_rule))
                    applied_mappings.append(
                        {
                            "entry_id": entry.id,
                            "mapping_id": mapping.id,
                            "canonical_type": mapping.canonical_type,
                        }
                    )
                    if mapping.approved_by == created_by:
                        self_review_dependency_keys.add(("fee_mapping", mapping.id))
                if entry.review_required:
                    review_required.append(entry.id)
                try:
                    converted, rate_id = self._convert(
                        session,
                        amount=amount,
                        currency=entry.currency,
                        quote_currency=quote,
                        effective_at=entry.effective_at,
                        fx_source=fx_source,
                        scope=scope_context,
                    )
                except LookupError:
                    missing_fx.append(
                        {"entry_id": entry.id, "currency": entry.currency, "effective_at": entry.effective_at.isoformat()}
                    )
                    continue
                totals[entry.entry_kind] += converted
                counts[entry.entry_kind] += 1
                if rate_id:
                    applied_fx.append({"entry_id": entry.id, "fx_rate_id": rate_id})
                    rate = session.get(FxRateRow, rate_id)
                    if rate is not None and rate.created_by == created_by:
                        self_review_dependency_keys.add(("fx_rate", rate.id))

            expected_settlement = (
                totals[FinanceEntryKind.ORDER_RECEIVABLE.value]
                + totals[FinanceEntryKind.PLATFORM_FEE.value]
                + totals[FinanceEntryKind.RETURN_ADJUSTMENT.value]
                + totals[FinanceEntryKind.CASH_ADJUSTMENT.value]
            )
            settlement = totals[FinanceEntryKind.PLATFORM_SETTLEMENT.value]
            bank = totals[FinanceEntryKind.BANK_RECEIPT.value]
            settlement_variance = settlement - expected_settlement
            bank_variance = bank - settlement
            missing_legs = [
                kind.value
                for kind in (
                    FinanceEntryKind.ORDER_RECEIVABLE,
                    FinanceEntryKind.PLATFORM_SETTLEMENT,
                    FinanceEntryKind.BANK_RECEIPT,
                )
                if counts[kind.value] == 0
            ]
            bank_evidence_ids = {
                entry.evidence_id
                for entry in entries
                if entry.entry_kind
                in {
                    FinanceEntryKind.BANK_RECEIPT.value,
                    FinanceEntryKind.BANK_PAYMENT.value,
                }
            }
            platform_evidence_ids = {
                entry.evidence_id
                for entry in entries
                if entry.entry_kind
                in {
                    FinanceEntryKind.ORDER_RECEIVABLE.value,
                    FinanceEntryKind.PLATFORM_FEE.value,
                    FinanceEntryKind.RETURN_ADJUSTMENT.value,
                    FinanceEntryKind.PLATFORM_SETTLEMENT.value,
                }
            }
            bank_evidence_by_hash = {
                blob_hash: sorted(evidence_id for evidence_id in bank_evidence_ids if evidence_hash_by_id[evidence_id] == blob_hash)
                for blob_hash in {evidence_hash_by_id[evidence_id] for evidence_id in bank_evidence_ids}
            }
            platform_evidence_by_hash = {
                blob_hash: sorted(
                    evidence_id for evidence_id in platform_evidence_ids if evidence_hash_by_id[evidence_id] == blob_hash
                )
                for blob_hash in {evidence_hash_by_id[evidence_id] for evidence_id in platform_evidence_ids}
            }
            evidence_conflicts = [
                {
                    "blob_sha256": blob_hash,
                    "bank_evidence_ids": bank_evidence_by_hash[blob_hash],
                    "platform_evidence_ids": platform_evidence_by_hash[blob_hash],
                }
                for blob_hash in sorted(bank_evidence_by_hash.keys() & platform_evidence_by_hash.keys())
            ]
            self_review_dependencies = [
                {"type": dependency_type, "id": dependency_id}
                for dependency_type, dependency_id in sorted(self_review_dependency_keys)
            ]
            settlement_ratio = self._variance_ratio(settlement_variance, expected_settlement)
            bank_ratio = self._variance_ratio(bank_variance, settlement)
            if missing_fx:
                status = "blocked_missing_fx"
            elif unknown_fees:
                status = "blocked_unknown_fee"
            elif review_required:
                status = "blocked_review_required"
            elif missing_legs:
                status = "incomplete"
            elif evidence_conflicts:
                status = "blocked_evidence_independence"
            elif self_review_dependencies:
                status = "blocked_self_review"
            elif settlement_ratio <= tolerance_ratio and bank_ratio <= tolerance_ratio:
                status = "matched"
            else:
                status = "variance"

            snapshot = {
                "entry_count": len(entries),
                "totals": {name: str(value) for name, value in totals.items()},
                "expected_settlement": str(expected_settlement),
                "platform_settlement": str(settlement),
                "bank_receipt": str(bank),
                "settlement_variance": str(settlement_variance),
                "bank_variance": str(bank_variance),
                "settlement_variance_ratio": str(settlement_ratio),
                "bank_variance_ratio": str(bank_ratio),
                "unknown_fees": unknown_fees,
                "missing_fx": missing_fx,
                "review_required": review_required,
                "missing_legs": missing_legs,
                "evidence_conflicts": evidence_conflicts,
                "self_review_dependencies": self_review_dependencies,
                "applied_fx": applied_fx,
                "applied_fee_mappings": applied_mappings,
            }
            snapshot["input_sha256"] = self._hash(
                {
                    "reconciliation_key": key,
                    "quote_currency": quote,
                    "fx_source": fx_source,
                    "tolerance_ratio": str(tolerance_ratio),
                    "entry_ids": [entry.id for entry in entries],
                    "entry_authorities": [
                        entry.source_evidence_sha256 for entry in entries
                    ],
                    "snapshot": snapshot,
                }
            )
            run_scope = (
                {
                    **scope_context,
                    "source_evidence_sha256": self._hash(
                        sorted(
                            {
                                str(entry.source_evidence_sha256)
                                for entry in entries
                                if entry.source_evidence_sha256
                            }
                        )
                    ),
                }
                if scope_context is not None
                else None
            )
            row = ReconciliationRunRow(
                id=new_id("recon"),
                reconciliation_key=key,
                quote_currency=quote,
                fx_source=fx_source,
                tolerance_ratio=tolerance_ratio,
                status=status,
                snapshot_json=snapshot,
                created_by=created_by,
                recorded_at=now,
                **self._scope_columns(run_scope),
            )
            session.add(row)
            session.flush()
            return {
                "id": row.id,
                "reconciliation_key": key,
                "quote_currency": quote,
                "fx_source": fx_source,
                "tolerance_ratio": str(tolerance_ratio),
                "status": status,
                "snapshot": snapshot,
                "created_by": created_by,
                "recorded_at": now.isoformat(),
                "scope": self._serialized_scope(run_scope),
            }

    def add_cash_plan_item(
        self,
        *,
        source: str,
        source_ref: str,
        category: str,
        amount: Decimal,
        currency: str,
        expected_at: str,
        probability: Decimal,
        status: CashPlanStatus,
        evidence_id: str,
        created_by: str,
        scope_authority: dict[str, Any] | None = None,
    ) -> CashPlanItem:
        amount = self._finite_decimal(amount, "Cash plan amount")
        probability = self._finite_decimal(probability, "Cash plan probability")
        source = source.strip()
        source_ref = source_ref.strip()
        category = category.strip()
        if not source or not source_ref or not category or probability < 0 or probability > 1:
            raise ValueError("Cash plan requires source, category, and probability in [0, 1]")
        if status is CashPlanStatus.COMMITTED and probability != 1:
            raise ValueError("Committed cash plan items require probability 1")
        currency = self._currency(currency)
        expected = parse_timestamp(expected_at, "expected_at")
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            evidence = self._require_evidence(session, evidence_id)
            scope = self._scope_authority(
                scope_authority,
                evidence_sha256=evidence.blob_sha256,
            )
            existing_query = select(CashPlanItemRow).where(
                CashPlanItemRow.source == source,
                CashPlanItemRow.source_ref == source_ref,
            )
            existing_query = self._scope_query(
                existing_query,
                CashPlanItemRow,
                scope,
            )
            existing = session.scalar(existing_query)
            if existing is not None:
                if not (
                    existing.category == category
                    and existing.amount == amount
                    and existing.currency == currency
                    and self._aware(existing.expected_at) == expected
                    and existing.probability == probability
                    and existing.status == status.value
                    and existing.evidence_id == evidence_id
                    and self._scope_matches(existing, scope)
                ):
                    raise ValueError("Cash plan idempotency key conflicts with existing values")
                return self._cash_item(existing)
            row = CashPlanItemRow(
                id=new_id("cash"),
                source=source,
                source_ref=source_ref,
                category=category,
                amount=amount,
                currency=currency,
                expected_at=expected,
                probability=probability,
                status=status.value,
                evidence_id=evidence_id,
                created_by=created_by,
                recorded_at=now,
                **self._scope_columns(scope),
            )
            session.add(row)
            session.flush()
            return self._cash_item(row)

    def cash_forecast(
        self,
        *,
        start_at: str,
        opening_balance: Decimal,
        quote_currency: str,
        fx_source: str,
        scope_authority: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        opening_balance = self._finite_decimal(opening_balance, "Opening balance")
        start = parse_timestamp(start_at, "start_at")
        end = start + timedelta(weeks=13)
        quote = self._currency(quote_currency)
        fx_source = fx_source.strip()
        if not fx_source:
            raise ValueError("Cash forecast requires an FX source")
        scope = self._scope_context(scope_authority)
        with Session(self.engine) as session:
            items_query = select(CashPlanItemRow).where(
                CashPlanItemRow.expected_at >= start,
                CashPlanItemRow.expected_at < end,
            )
            items_query = self._scope_query(
                items_query,
                CashPlanItemRow,
                scope,
            )
            if scope is not None:
                items_query = items_query.where(
                    CashPlanItemRow.scope_as_of <= scope["scope_as_of"],
                    CashPlanItemRow.recorded_at <= scope["scope_as_of"],
                )
            items = session.scalars(
                items_query.order_by(
                    CashPlanItemRow.expected_at,
                    CashPlanItemRow.id,
                )
            ).all()
            weeks = [
                {
                    "week": index + 1,
                    "start_at": (start + timedelta(weeks=index)).isoformat(),
                    "end_at": (start + timedelta(weeks=index + 1)).isoformat(),
                    "committed_net": Decimal("0"),
                    "probability_weighted_net": Decimal("0"),
                    "item_ids": [],
                }
                for index in range(13)
            ]
            blocked: list[dict[str, str]] = []
            for item in items:
                item_expected_at = self._aware(item.expected_at)
                try:
                    converted, _ = self._convert(
                        session,
                        amount=item.amount,
                        currency=item.currency,
                        quote_currency=quote,
                        effective_at=item_expected_at,
                        fx_source=fx_source,
                        scope=scope,
                    )
                except LookupError:
                    blocked.append(
                        {"item_id": item.id, "currency": item.currency, "expected_at": item_expected_at.isoformat()}
                    )
                    continue
                index = (item_expected_at - start).days // 7
                weeks[index]["item_ids"].append(item.id)
                if item.status == CashPlanStatus.COMMITTED.value:
                    weeks[index]["committed_net"] += converted
                weeks[index]["probability_weighted_net"] += converted * item.probability

            committed_balance = opening_balance
            weighted_balance = opening_balance
            serialized_weeks = []
            for week in weeks:
                committed_balance += week["committed_net"]
                weighted_balance += week["probability_weighted_net"]
                serialized_weeks.append(
                    {
                        **week,
                        "committed_net": str(week["committed_net"]),
                        "probability_weighted_net": str(week["probability_weighted_net"]),
                        "committed_closing_balance": str(committed_balance),
                        "probability_weighted_closing_balance": str(weighted_balance),
                    }
                )
            return {
                "status": "blocked_missing_fx" if blocked else "ready",
                "start_at": start.isoformat(),
                "quote_currency": quote,
                "fx_source": fx_source,
                "opening_balance": str(opening_balance),
                "weeks": serialized_weeks,
                "blocked_items": blocked,
            }

    @staticmethod
    def _require_evidence(
        session: Session,
        evidence_id: str,
    ) -> EvidenceRecordRow:
        row = session.get(EvidenceRecordRow, evidence_id)
        if row is None:
            raise KeyError(f"Unknown evidence: {evidence_id}")
        return row

    @classmethod
    def _scope_authority(
        cls,
        value: dict[str, Any] | None,
        *,
        evidence_sha256: str,
    ) -> dict[str, Any] | None:
        context = cls._scope_context(value)
        if context is None:
            return None
        claimed = str(
            (value or {}).get("source_evidence_sha256") or evidence_sha256
        ).strip().lower()
        cls._require_sha256(claimed, "source_evidence_sha256")
        if claimed != evidence_sha256:
            raise ValueError(
                "Native finance source Evidence authority changed"
            )
        return {
            **context,
            "source_evidence_sha256": claimed,
        }

    @classmethod
    def _scope_context(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        required = (
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "scope_as_of",
        )
        normalized = {
            field: str(value.get(field) or "").strip()
            for field in required
        }
        if any(not item for item in normalized.values()):
            raise ValueError("Native finance scope authority is incomplete")
        for field in ("tenant_ref", "entity_ref", "store_ref"):
            if len(normalized[field]) > 160:
                raise ValueError(f"{field} must be at most 160 characters")
        authority = normalized["scope_grant_authority_sha256"].lower()
        cls._require_sha256(
            authority,
            "scope_grant_authority_sha256",
        )
        return {
            "tenant_ref": normalized["tenant_ref"],
            "entity_ref": normalized["entity_ref"],
            "store_ref": normalized["store_ref"],
            "scope_grant_authority_sha256": authority,
            "scope_as_of": parse_timestamp(
                normalized["scope_as_of"],
                "scope_as_of",
            ),
        }

    @staticmethod
    def _require_sha256(value: str, name: str) -> None:
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError(f"{name} must be SHA-256")

    @staticmethod
    def _scope_columns(
        scope: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if scope is None:
            return {
                "tenant_ref": None,
                "entity_ref": None,
                "store_ref": None,
                "scope_grant_authority_sha256": None,
                "source_evidence_sha256": None,
                "scope_as_of": None,
            }
        return {
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "scope_grant_authority_sha256": (
                scope["scope_grant_authority_sha256"]
            ),
            "source_evidence_sha256": scope["source_evidence_sha256"],
            "scope_as_of": scope["scope_as_of"],
        }

    @staticmethod
    def _serialized_scope(
        scope: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if scope is None:
            return None
        return {
            "tenant_ref": scope["tenant_ref"],
            "entity_ref": scope["entity_ref"],
            "store_ref": scope["store_ref"],
            "scope_grant_authority_sha256": (
                scope["scope_grant_authority_sha256"]
            ),
            "source_evidence_sha256": scope.get(
                "source_evidence_sha256"
            ),
            "as_of": FinanceService._aware(
                scope["scope_as_of"]
            ).isoformat(),
            "authority": "native",
        }

    @classmethod
    def _serialized_row_scope(cls, row) -> dict[str, Any] | None:
        if row.tenant_ref is None or row.scope_as_of is None:
            return None
        return {
            "tenant_ref": row.tenant_ref,
            "entity_ref": row.entity_ref,
            "store_ref": row.store_ref,
            "scope_grant_authority_sha256": (
                row.scope_grant_authority_sha256
            ),
            "source_evidence_sha256": row.source_evidence_sha256,
            "as_of": cls._aware(row.scope_as_of).isoformat(),
            "authority": "native",
        }

    @staticmethod
    def _scope_query(query, model, scope: dict[str, Any] | None):
        if scope is None:
            return query.where(model.tenant_ref.is_(None))
        return query.where(
            model.tenant_ref == scope["tenant_ref"],
            model.entity_ref == scope["entity_ref"],
            model.store_ref == scope["store_ref"],
            model.scope_grant_authority_sha256
            == scope["scope_grant_authority_sha256"],
        )

    @classmethod
    def _scope_matches(
        cls,
        row,
        scope: dict[str, Any] | None,
    ) -> bool:
        if scope is None:
            return row.tenant_ref is None
        return bool(
            row.tenant_ref == scope["tenant_ref"]
            and row.entity_ref == scope["entity_ref"]
            and row.store_ref == scope["store_ref"]
            and row.scope_grant_authority_sha256
            == scope["scope_grant_authority_sha256"]
            and row.source_evidence_sha256
            == scope["source_evidence_sha256"]
            and cls._aware(row.scope_as_of) == scope["scope_as_of"]
        )

    @staticmethod
    def _currency(value: str) -> str:
        currency = value.strip().upper()
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            raise ValueError("Currency must be a three-letter code")
        return currency

    @staticmethod
    def _finite_decimal(value: Decimal, name: str) -> Decimal:
        try:
            parsed = Decimal(value)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not parsed.is_finite():
            raise ValueError(f"{name} must be finite")
        return parsed

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    @classmethod
    def _entry_matches(
        cls,
        row: FinanceEntryRow,
        *,
        reconciliation_key: str,
        raw_fee_code: str | None,
        profit_cost_type: str | None,
        amount: Decimal,
        currency: str,
        effective_at: datetime,
        evidence_id: str,
        source_fact_id: str | None,
        supplier_invoice_id: str | None,
        supplier_ref: str | None,
        payment_approval_id: str | None,
        payment_command_id: str | None,
        review_required: bool,
        scope: dict[str, Any] | None,
    ) -> bool:
        return bool(
            row.reconciliation_key == reconciliation_key
            and row.raw_fee_code == raw_fee_code
            and row.profit_cost_type == profit_cost_type
            and row.amount == amount
            and row.currency == currency
            and cls._aware(row.effective_at) == effective_at
            and row.evidence_id == evidence_id
            and row.source_fact_id == source_fact_id
            and row.supplier_invoice_id == supplier_invoice_id
            and row.supplier_ref == supplier_ref
            and row.payment_approval_id == payment_approval_id
            and row.payment_command_id == payment_command_id
            and row.review_required == review_required
            and cls._scope_matches(row, scope)
        )

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _require_supplier_payment_binding(
        session: Session,
        *,
        supplier_invoice_id: str | None,
        supplier_ref: str | None,
        payment_approval_id: str | None,
        payment_command_id: str | None,
        currency: str,
        scope: dict[str, Any] | None,
    ) -> None:
        from .accounts_payable import SupplierInvoiceRow
        from .limited_executor import LimitedExecutionCommandRow
        from .sql_repository import ApprovalRow

        if scope is None:
            raise ValueError("Supplier payment requires exact scope authority")
        invoice = session.get(SupplierInvoiceRow, supplier_invoice_id)
        approval = session.get(ApprovalRow, payment_approval_id)
        command = session.get(
            LimitedExecutionCommandRow,
            payment_command_id,
        )
        if invoice is None or approval is None or command is None:
            raise ValueError(
                "Supplier payment binding references missing authority"
            )
        if (
            invoice.supplier_ref != supplier_ref
            or invoice.currency != currency
            or invoice.tenant_ref != scope["tenant_ref"]
            or invoice.entity_ref != scope["entity_ref"]
            or invoice.store_ref != scope["store_ref"]
            or invoice.scope_grant_authority_sha256
            != scope["scope_grant_authority_sha256"]
        ):
            raise ValueError(
                "Supplier payment binding conflicts with invoice scope"
            )
        if (
            approval.status != "approved"
            or approval.action != "finance.pay_supplier_invoice"
            or approval.resource_type != "supplier_invoice"
            or approval.resource_id != supplier_invoice_id
            or not approval.decided_by
            or approval.decided_by == approval.requested_by
        ):
            raise ValueError(
                "Supplier payment requires an independent exact invoice approval"
            )
        if (
            command.command_kind != "execute"
            or command.action_id != "supplier_payment"
            or command.operation != "finance.pay_supplier_invoice"
            or command.target_json.get("supplier_invoice_id")
            != supplier_invoice_id
        ):
            raise ValueError(
                "Supplier payment command is not bound to the exact invoice"
            )

    @staticmethod
    def _apply_sign_rule(amount: Decimal, rule: FeeSignRule) -> Decimal:
        if rule is FeeSignRule.ABSOLUTE_INFLOW:
            return abs(amount)
        if rule is FeeSignRule.ABSOLUTE_OUTFLOW:
            return -abs(amount)
        return amount

    @staticmethod
    def _variance_ratio(variance: Decimal, base: Decimal) -> Decimal:
        return abs(variance) / max(abs(base), Decimal("1"))

    @classmethod
    def _resolve_fee_mapping(
        cls,
        session: Session,
        *,
        provider: str,
        raw_code: str,
        effective_at: datetime,
        scope: dict[str, Any] | None,
    ) -> FeeMappingRow | None:
        query = select(FeeMappingRow).where(
            FeeMappingRow.provider == provider,
            FeeMappingRow.raw_code == raw_code,
            FeeMappingRow.effective_from <= effective_at,
            or_(
                FeeMappingRow.effective_until.is_(None),
                FeeMappingRow.effective_until > effective_at,
            ),
        )
        query = cls._scope_query(query, FeeMappingRow, scope)
        if scope is not None:
            query = query.where(
                FeeMappingRow.scope_as_of <= scope["scope_as_of"],
                FeeMappingRow.recorded_at <= scope["scope_as_of"],
            )
        return session.scalar(
            query
            .order_by(
                FeeMappingRow.effective_from.desc(),
                FeeMappingRow.version.desc(),
                FeeMappingRow.recorded_at.desc(),
            )
            .limit(1)
        )

    @classmethod
    def _convert(
        cls,
        session: Session,
        *,
        amount: Decimal,
        currency: str,
        quote_currency: str,
        effective_at: datetime,
        fx_source: str,
        scope: dict[str, Any] | None,
    ) -> tuple[Decimal, str | None]:
        if currency == quote_currency:
            return amount, None
        query = select(FxRateRow).where(
            FxRateRow.base_currency == currency,
            FxRateRow.quote_currency == quote_currency,
            FxRateRow.source == fx_source,
            FxRateRow.effective_at <= effective_at,
            or_(
                FxRateRow.expires_at.is_(None),
                FxRateRow.expires_at > effective_at,
            ),
        )
        query = cls._scope_query(query, FxRateRow, scope)
        if scope is not None:
            query = query.where(
                FxRateRow.scope_as_of <= scope["scope_as_of"],
                FxRateRow.recorded_at <= scope["scope_as_of"],
            )
        rate = session.scalar(
            query
            .order_by(FxRateRow.effective_at.desc(), FxRateRow.version.desc(), FxRateRow.recorded_at.desc())
            .limit(1)
        )
        if rate is None:
            raise LookupError(f"Missing {currency}/{quote_currency} FX rate from {fx_source}")
        return amount * rate.rate, rate.id

    @classmethod
    def _fee_mapping(cls, row: FeeMappingRow) -> FeeMapping:
        return FeeMapping(
            row.id,
            row.provider,
            row.raw_code,
            row.canonical_type,
            row.sign_rule,
            row.version,
            row.effective_from.isoformat(),
            row.effective_until.isoformat() if row.effective_until else None,
            row.evidence_id,
            row.approved_by,
            row.recorded_at.isoformat(),
            cls._serialized_row_scope(row),
        )

    @classmethod
    def _fx_rate(cls, row: FxRateRow) -> FxRate:
        return FxRate(
            id=row.id,
            base_currency=row.base_currency,
            quote_currency=row.quote_currency,
            rate=str(row.rate),
            version=row.version,
            effective_at=row.effective_at.isoformat(),
            source=row.source,
            evidence_id=row.evidence_id,
            created_by=row.created_by,
            recorded_at=row.recorded_at.isoformat(),
            scope=cls._serialized_row_scope(row),
            expires_at=(
                row.expires_at.isoformat() if row.expires_at else None
            ),
            source_type=row.source_type,
            authority=row.authority,
            purposes=tuple(row.purposes_json or ()),
            intake_content_sha256=row.intake_content_sha256,
            idempotency_key=row.idempotency_key,
        )

    @staticmethod
    def _entry(row: FinanceEntryRow) -> FinanceEntry:
        return FinanceEntry(
            row.id,
            row.entry_kind,
            row.source,
            row.source_ref,
            row.reconciliation_key,
            row.raw_fee_code,
            row.profit_cost_type,
            str(row.amount),
            row.currency,
            row.effective_at.isoformat(),
            row.evidence_id,
            row.source_fact_id,
            row.supplier_invoice_id,
            row.supplier_ref,
            row.payment_approval_id,
            row.payment_command_id,
            row.review_required,
            row.created_by,
            row.recorded_at.isoformat(),
            (
                {
                    "tenant_ref": row.tenant_ref,
                    "entity_ref": row.entity_ref,
                    "store_ref": row.store_ref,
                    "scope_grant_authority_sha256": (
                        row.scope_grant_authority_sha256
                    ),
                    "source_evidence_sha256": (
                        row.source_evidence_sha256
                    ),
                    "as_of": FinanceService._aware(
                        row.scope_as_of
                    ).isoformat(),
                    "authority": "native",
                }
                if row.tenant_ref is not None
                and row.scope_as_of is not None
                else None
            ),
        )

    @staticmethod
    def _cash_item(row: CashPlanItemRow) -> CashPlanItem:
        return CashPlanItem(
            row.id,
            row.source,
            row.source_ref,
            row.category,
            str(row.amount),
            row.currency,
            row.expected_at.isoformat(),
            str(row.probability),
            row.status,
            row.evidence_id,
            row.created_by,
            row.recorded_at.isoformat(),
            (
                {
                    "tenant_ref": row.tenant_ref,
                    "entity_ref": row.entity_ref,
                    "store_ref": row.store_ref,
                    "scope_grant_authority_sha256": (
                        row.scope_grant_authority_sha256
                    ),
                    "source_evidence_sha256": (
                        row.source_evidence_sha256
                    ),
                    "as_of": FinanceService._aware(
                        row.scope_as_of
                    ).isoformat(),
                    "authority": "native",
                }
                if row.tenant_ref is not None
                and row.scope_as_of is not None
                else None
            ),
        )
