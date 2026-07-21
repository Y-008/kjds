from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import ChargeType, new_id
from .evidence import EvidenceRecordRow, parse_timestamp
from .facts import FactRecordRow
from .ozon_contracts import OzonRecordType
from .sql_repository import Base


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
    CASH_ADJUSTMENT = "cash_adjustment"


class CashPlanStatus(StrEnum):
    COMMITTED = "committed"
    SCENARIO = "scenario"


class FeeMappingRow(Base):
    __tablename__ = "fee_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "raw_code", "effective_from", "version", name="uq_fee_mapping_version"),
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


class FxRateRow(Base):
    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint(
            "base_currency",
            "quote_currency",
            "effective_at",
            "source",
            "version",
            name="uq_fx_rate_observation",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey(EvidenceRecordRow.id), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FinanceEntryRow(Base):
    __tablename__ = "finance_entries"
    __table_args__ = (
        UniqueConstraint("source", "source_ref", "entry_kind", name="uq_finance_source_entry"),
        UniqueConstraint("source_fact_id", name="uq_finance_source_fact"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    entry_kind: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    reconciliation_key: Mapped[str] = mapped_column(String, nullable=False)
    raw_fee_code: Mapped[str | None] = mapped_column(String, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey(EvidenceRecordRow.id), nullable=False)
    source_fact_id: Mapped[str | None] = mapped_column(ForeignKey(FactRecordRow.id), nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReconciliationRunRow(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    reconciliation_key: Mapped[str] = mapped_column(String, nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    fx_source: Mapped[str] = mapped_column(String, nullable=False)
    tolerance_ratio: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CashPlanItemRow(Base):
    __tablename__ = "cash_plan_items"
    __table_args__ = (UniqueConstraint("source", "source_ref", name="uq_cash_plan_source"),)

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


@dataclass(frozen=True, slots=True)
class FinanceEntry:
    id: str
    entry_kind: str
    source: str
    source_ref: str
    reconciliation_key: str
    raw_fee_code: str | None
    amount: str
    currency: str
    effective_at: str
    evidence_id: str
    source_fact_id: str | None
    review_required: bool
    created_by: str
    recorded_at: str


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
            self._require_evidence(session, evidence_id)
            latest = session.scalar(
                select(FeeMappingRow)
                .where(
                    FeeMappingRow.provider == provider,
                    FeeMappingRow.raw_code == raw_code,
                    FeeMappingRow.effective_from == start,
                )
                .order_by(FeeMappingRow.version.desc())
                .limit(1)
            )
            if latest is not None and (
                latest.canonical_type == canonical_type.value
                and latest.sign_rule == sign_rule.value
                and (self._aware(latest.effective_until) if latest.effective_until else None) == end
                and latest.evidence_id == evidence_id
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
            )
            session.add(row)
            session.flush()
            return self._fee_mapping(row)

    def list_fee_mappings(self, *, provider: str | None = None) -> list[FeeMapping]:
        query = select(FeeMappingRow)
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
    ) -> FxRate:
        rate = self._finite_decimal(rate, "FX rate")
        base = self._currency(base_currency)
        quote = self._currency(quote_currency)
        source = source.strip()
        if base == quote or rate <= 0 or not source:
            raise ValueError("FX rate requires distinct currencies, a positive rate, and a source")
        effective = parse_timestamp(effective_at, "effective_at")
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._require_evidence(session, evidence_id)
            latest = session.scalar(
                select(FxRateRow)
                .where(
                    FxRateRow.base_currency == base,
                    FxRateRow.quote_currency == quote,
                    FxRateRow.effective_at == effective,
                    FxRateRow.source == source,
                )
                .order_by(FxRateRow.version.desc())
                .limit(1)
            )
            if latest is not None and latest.rate == rate and latest.evidence_id == evidence_id:
                return self._fx_rate(latest)
            row = FxRateRow(
                id=new_id("fx"),
                base_currency=base,
                quote_currency=quote,
                rate=rate,
                version=1 if latest is None else latest.version + 1,
                effective_at=effective,
                source=source,
                evidence_id=evidence_id,
                created_by=created_by,
                recorded_at=now,
            )
            session.add(row)
            session.flush()
            return self._fx_rate(row)

    def list_fx_rates(self, *, base_currency: str | None = None) -> list[FxRate]:
        query = select(FxRateRow)
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
            existing = session.scalar(select(FinanceEntryRow).where(FinanceEntryRow.source_fact_id == fact_id))
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
        source_fact_id: str | None = None,
        review_required: bool = False,
    ) -> FinanceEntry:
        source = source.strip()
        source_ref = source_ref.strip()
        reconciliation_key = reconciliation_key.strip()
        raw_fee_code = raw_fee_code.strip() if raw_fee_code else None
        if not source or not source_ref or not reconciliation_key:
            raise ValueError("Finance entry requires source, source reference, and reconciliation key")
        if entry_kind is FinanceEntryKind.PLATFORM_FEE and not raw_fee_code:
            raise ValueError("Platform fee entry requires its raw fee code")
        amount = self._finite_decimal(amount, "Finance entry amount")
        currency = self._currency(currency)
        effective = parse_timestamp(effective_at, "effective_at")
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._require_evidence(session, evidence_id)
            existing = session.scalar(
                select(FinanceEntryRow).where(
                    FinanceEntryRow.source == source,
                    FinanceEntryRow.source_ref == source_ref,
                    FinanceEntryRow.entry_kind == entry_kind.value,
                )
            )
            if existing is not None:
                if not self._entry_matches(
                    existing,
                    reconciliation_key=reconciliation_key,
                    raw_fee_code=raw_fee_code,
                    amount=amount,
                    currency=currency,
                    effective_at=effective,
                    evidence_id=evidence_id,
                    source_fact_id=source_fact_id,
                    review_required=review_required,
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
                amount=amount,
                currency=currency,
                effective_at=effective,
                evidence_id=evidence_id,
                source_fact_id=source_fact_id,
                review_required=review_required,
                created_by=created_by,
                recorded_at=now,
            )
            session.add(row)
            session.flush()
            return self._entry(row)

    def list_entries(
        self, *, reconciliation_key: str | None = None, entry_kind: FinanceEntryKind | None = None
    ) -> list[FinanceEntry]:
        query = select(FinanceEntryRow)
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
                .where(FinanceEntryRow.entry_kind == FinanceEntryKind.PLATFORM_FEE.value)
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
                )
                is None
            ]

    def reconcile(
        self,
        reconciliation_key: str,
        *,
        quote_currency: str,
        fx_source: str,
        tolerance_ratio: Decimal,
        created_by: str,
    ) -> dict[str, Any]:
        tolerance_ratio = self._finite_decimal(tolerance_ratio, "Reconciliation tolerance")
        key = reconciliation_key.strip()
        quote = self._currency(quote_currency)
        fx_source = fx_source.strip()
        created_by = created_by.strip()
        if not key or not fx_source or not created_by or tolerance_ratio < 0 or tolerance_ratio >= 1:
            raise ValueError("Reconciliation requires key, FX source, reviewer, and tolerance in [0, 1)")
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            entries = session.scalars(
                select(FinanceEntryRow)
                .where(FinanceEntryRow.reconciliation_key == key)
                .order_by(FinanceEntryRow.effective_at, FinanceEntryRow.id)
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
                        session, provider="ozon", raw_code=entry.raw_fee_code or "", effective_at=entry.effective_at
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
                entry.evidence_id for entry in entries if entry.entry_kind == FinanceEntryKind.BANK_RECEIPT.value
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
            self._require_evidence(session, evidence_id)
            existing = session.scalar(
                select(CashPlanItemRow).where(
                    CashPlanItemRow.source == source, CashPlanItemRow.source_ref == source_ref
                )
            )
            if existing is not None:
                if not (
                    existing.category == category
                    and existing.amount == amount
                    and existing.currency == currency
                    and self._aware(existing.expected_at) == expected
                    and existing.probability == probability
                    and existing.status == status.value
                    and existing.evidence_id == evidence_id
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
    ) -> dict[str, Any]:
        opening_balance = self._finite_decimal(opening_balance, "Opening balance")
        start = parse_timestamp(start_at, "start_at")
        end = start + timedelta(weeks=13)
        quote = self._currency(quote_currency)
        fx_source = fx_source.strip()
        if not fx_source:
            raise ValueError("Cash forecast requires an FX source")
        with Session(self.engine) as session:
            items = session.scalars(
                select(CashPlanItemRow)
                .where(CashPlanItemRow.expected_at >= start, CashPlanItemRow.expected_at < end)
                .order_by(CashPlanItemRow.expected_at, CashPlanItemRow.id)
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
    def _require_evidence(session: Session, evidence_id: str) -> None:
        if session.get(EvidenceRecordRow, evidence_id) is None:
            raise KeyError(f"Unknown evidence: {evidence_id}")

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
        amount: Decimal,
        currency: str,
        effective_at: datetime,
        evidence_id: str,
        source_fact_id: str | None,
        review_required: bool,
    ) -> bool:
        return bool(
            row.reconciliation_key == reconciliation_key
            and row.raw_fee_code == raw_fee_code
            and row.amount == amount
            and row.currency == currency
            and cls._aware(row.effective_at) == effective_at
            and row.evidence_id == evidence_id
            and row.source_fact_id == source_fact_id
            and row.review_required == review_required
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

    @staticmethod
    def _resolve_fee_mapping(
        session: Session, *, provider: str, raw_code: str, effective_at: datetime
    ) -> FeeMappingRow | None:
        return session.scalar(
            select(FeeMappingRow)
            .where(
                FeeMappingRow.provider == provider,
                FeeMappingRow.raw_code == raw_code,
                FeeMappingRow.effective_from <= effective_at,
                or_(FeeMappingRow.effective_until.is_(None), FeeMappingRow.effective_until > effective_at),
            )
            .order_by(
                FeeMappingRow.effective_from.desc(),
                FeeMappingRow.version.desc(),
                FeeMappingRow.recorded_at.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def _convert(
        session: Session,
        *,
        amount: Decimal,
        currency: str,
        quote_currency: str,
        effective_at: datetime,
        fx_source: str,
    ) -> tuple[Decimal, str | None]:
        if currency == quote_currency:
            return amount, None
        rate = session.scalar(
            select(FxRateRow)
            .where(
                FxRateRow.base_currency == currency,
                FxRateRow.quote_currency == quote_currency,
                FxRateRow.source == fx_source,
                FxRateRow.effective_at <= effective_at,
            )
            .order_by(FxRateRow.effective_at.desc(), FxRateRow.version.desc(), FxRateRow.recorded_at.desc())
            .limit(1)
        )
        if rate is None:
            raise LookupError(f"Missing {currency}/{quote_currency} FX rate from {fx_source}")
        return amount * rate.rate, rate.id

    @staticmethod
    def _fee_mapping(row: FeeMappingRow) -> FeeMapping:
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
        )

    @staticmethod
    def _fx_rate(row: FxRateRow) -> FxRate:
        return FxRate(
            row.id,
            row.base_currency,
            row.quote_currency,
            str(row.rate),
            row.version,
            row.effective_at.isoformat(),
            row.source,
            row.evidence_id,
            row.created_by,
            row.recorded_at.isoformat(),
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
            str(row.amount),
            row.currency,
            row.effective_at.isoformat(),
            row.evidence_id,
            row.source_fact_id,
            row.review_required,
            row.created_by,
            row.recorded_at.isoformat(),
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
        )
