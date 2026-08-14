from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    select,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import LineageEdgeRow
from .imports import ImportDataRow, ImportJobRow
from .ozon_contracts import CONTRACT_VERSION, OzonRecordType, natural_key, normalize_record
from .sql_repository import Base, ProductRow


class FactRecordRow(Base):
    __tablename__ = "fact_records"
    __table_args__ = (
        CheckConstraint(
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
            ")",
            name="ck_fact_record_scope_complete",
        ),
        Index(
            "uq_fact_legacy_import_contract",
            "import_row_id",
            "contract_version",
            unique=True,
            sqlite_where=text("tenant_ref IS NULL"),
            postgresql_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_fact_legacy_source_payload",
            "source",
            "fact_type",
            "natural_key",
            "payload_hash",
            unique=True,
            sqlite_where=text("tenant_ref IS NULL"),
            postgresql_where=text("tenant_ref IS NULL"),
        ),
        Index(
            "uq_fact_scoped_import_contract",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "import_row_id",
            "contract_version",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "uq_fact_scoped_source_payload",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "source",
            "fact_type",
            "natural_key",
            "payload_hash",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "ix_fact_scope_recorded",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "recorded_at",
        ),
        Index(
            "ix_fact_scope_inventory_product_effective",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "product_id",
            "effective_at",
            "recorded_at",
            sqlite_where=text(
                "tenant_ref IS NOT NULL "
                "AND fact_type = 'ozon_inventory'"
            ),
            postgresql_where=text(
                "tenant_ref IS NOT NULL "
                "AND fact_type = 'ozon_inventory'"
            ),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    fact_type: Mapped[str] = mapped_column(String, nullable=False)
    natural_key: Mapped[str] = mapped_column(String, nullable=False)
    contract_version: Mapped[str] = mapped_column(String, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    import_row_id: Mapped[str] = mapped_column(ForeignKey("import_rows.id"), nullable=False)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
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


class PromotionRunRow(Base):
    __tablename__ = "promotion_runs"
    __table_args__ = (
        CheckConstraint(
            "("
            "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
            "AND scope_grant_authority_sha256 IS NULL "
            "AND source_evidence_sha256 IS NULL AND scope_as_of IS NULL "
            "AND request_sha256 IS NULL"
            ") OR ("
            "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
            "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
            "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
            "AND scope_grant_authority_sha256 IS NOT NULL "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND source_evidence_sha256 IS NOT NULL "
            "AND length(source_evidence_sha256) = 64 "
            "AND scope_as_of IS NOT NULL "
            "AND request_sha256 IS NOT NULL "
            "AND length(request_sha256) = 64"
            ")",
            name="ck_promotion_run_scope_complete",
        ),
        Index(
            "uq_promotion_run_scoped_request",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "request_sha256",
            unique=True,
            sqlite_where=text("tenant_ref IS NOT NULL"),
            postgresql_where=text("tenant_ref IS NOT NULL"),
        ),
        Index(
            "ix_promotion_run_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("import_jobs.id"), nullable=False)
    promoted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False)
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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
    request_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


@dataclass(frozen=True, slots=True)
class FactRecord:
    id: str
    source: str
    fact_type: str
    natural_key: str
    contract_version: str
    payload: dict[str, Any]
    payload_hash: str
    effective_at: str
    recorded_at: str
    evidence_id: str
    import_row_id: str
    product_id: str | None
    resolution_status: str
    created_by: str


@dataclass(frozen=True, slots=True)
class PromotionResult:
    id: str
    import_id: str
    promoted_count: int
    duplicate_count: int
    blocked_count: int
    errors: list[dict[str, Any]]
    created_by: str
    created_at: str


class FactPromotionService:
    def __init__(
        self,
        engine,
        *,
        finance_review_validator: Callable[[str], None] | None = None,
        fee_mapping_validator: Callable[[str], None] | None = None,
        accrual_classification_validator: Callable[[str], None] | None = None,
    ) -> None:
        self.engine = engine
        self.finance_review_validator = finance_review_validator
        self.fee_mapping_validator = fee_mapping_validator
        self.accrual_classification_validator = accrual_classification_validator

    def promote(self, import_id: str, *, created_by: str) -> PromotionResult:
        self._require_finance_review(import_id)
        now = datetime.now(UTC)
        promoted = 0
        duplicate = 0
        blocked = 0
        errors: list[dict[str, Any]] = []
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            job = session.get(ImportJobRow, import_id)
            if job is None:
                raise KeyError(f"Unknown import: {import_id}")
            if not job.evidence_id:
                raise ValueError("Import cannot be promoted without immutable source evidence")
            if job.status == "rejected":
                raise ValueError("Rejected import cannot be promoted to formal facts")
            rows = session.scalars(
                select(ImportDataRow).where(ImportDataRow.import_id == import_id).order_by(ImportDataRow.row_number)
            ).all()
            for row in rows:
                if row.errors_json:
                    blocked += 1
                    errors.append({"row_number": row.row_number, "errors": row.errors_json})
                    continue
                record_type = OzonRecordType(row.record_type)
                payload, contract_errors = normalize_record(record_type, row.normalized_json)
                if contract_errors:
                    blocked += 1
                    errors.append({"row_number": row.row_number, "errors": contract_errors})
                    continue
                payload_hash = hashlib.sha256(
                    json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
                ).hexdigest()
                fact_key = natural_key(record_type, payload)
                existing = session.scalar(
                    select(FactRecordRow).where(
                        FactRecordRow.tenant_ref.is_(None),
                        (FactRecordRow.import_row_id == row.id)
                        | (
                            (FactRecordRow.source == job.source)
                            & (FactRecordRow.fact_type == record_type.value)
                            & (FactRecordRow.natural_key == fact_key)
                            & (FactRecordRow.payload_hash == payload_hash)
                        )
                    )
                )
                if existing is not None:
                    duplicate += 1
                    continue

                product_id = None
                resolution_status = "resolved"
                sku = payload.get("sku")
                if sku:
                    product = session.scalar(select(ProductRow).where(ProductRow.sku == sku))
                    product_id = product.id if product else None
                    if product_id is None:
                        resolution_status = "requires_product_mapping"

                fact = FactRecordRow(
                    id=new_id("fact"),
                    source=job.source,
                    fact_type=record_type.value,
                    natural_key=fact_key,
                    contract_version=CONTRACT_VERSION,
                    payload_json=payload,
                    payload_hash=payload_hash,
                    effective_at=datetime.fromisoformat(payload["effective_at"]),
                    recorded_at=now,
                    evidence_id=job.evidence_id,
                    import_row_id=row.id,
                    product_id=product_id,
                    resolution_status=resolution_status,
                    created_by=created_by,
                )
                session.add(fact)
                session.add(
                    LineageEdgeRow(
                        id=new_id("lin"),
                        from_type="evidence",
                        from_id=job.evidence_id,
                        to_type="commerce_fact",
                        to_id=fact.id,
                        relationship="supports",
                        created_by=created_by,
                        recorded_at=now,
                    )
                )
                promoted += 1

            run = PromotionRunRow(
                id=new_id("prom"),
                import_id=import_id,
                promoted_count=promoted,
                duplicate_count=duplicate,
                blocked_count=blocked,
                errors_json=errors,
                created_by=created_by,
                created_at=now,
            )
            session.add(run)
            session.flush()
            return self._promotion(run)

    def _require_finance_review(self, import_id: str) -> None:
        with Session(self.engine) as session:
            job = session.get(ImportJobRow, import_id)
            if job is None:
                raise KeyError(f"Unknown import: {import_id}")
            finance_types = {
                OzonRecordType.FEE.value,
                OzonRecordType.ACCRUAL.value,
                OzonRecordType.RETURN.value,
                OzonRecordType.SETTLEMENT.value,
            }
            if job.record_type not in finance_types:
                return
        if self.finance_review_validator is None:
            raise ValueError("Finance import requires an independent accepted source review")
        self.finance_review_validator(import_id)
        if job.record_type == OzonRecordType.FEE.value:
            if self.fee_mapping_validator is None:
                raise ValueError("Ozon fee import requires approved fee mappings")
            self.fee_mapping_validator(import_id)
        if job.record_type == OzonRecordType.ACCRUAL.value:
            if self.accrual_classification_validator is None:
                raise ValueError("Ozon accrual import requires approved control classifications")
            self.accrual_classification_validator(import_id)

    def get(self, fact_id: str) -> FactRecord:
        with Session(self.engine) as session:
            row = session.get(FactRecordRow, fact_id)
            if row is None or row.tenant_ref is not None:
                raise KeyError(f"Unknown fact: {fact_id}")
            return self._fact(row)

    def list(self, *, fact_type: str | None = None, limit: int = 100) -> list[FactRecord]:
        query = select(FactRecordRow).where(
            FactRecordRow.tenant_ref.is_(None)
        )
        if fact_type:
            query = query.where(FactRecordRow.fact_type == fact_type)
        query = query.order_by(FactRecordRow.recorded_at.desc(), FactRecordRow.id).limit(limit)
        with Session(self.engine) as session:
            return [self._fact(row) for row in session.scalars(query).all()]

    @staticmethod
    def _fact(row: FactRecordRow) -> FactRecord:
        return FactRecord(
            row.id,
            row.source,
            row.fact_type,
            row.natural_key,
            row.contract_version,
            row.payload_json,
            row.payload_hash,
            row.effective_at.isoformat(),
            row.recorded_at.isoformat(),
            row.evidence_id,
            row.import_row_id,
            row.product_id,
            row.resolution_status,
            row.created_by,
        )

    @staticmethod
    def _promotion(row: PromotionRunRow) -> PromotionResult:
        return PromotionResult(
            row.id,
            row.import_id,
            row.promoted_count,
            row.duplicate_count,
            row.blocked_count,
            row.errors_json,
            row.created_by,
            row.created_at.isoformat(),
        )
