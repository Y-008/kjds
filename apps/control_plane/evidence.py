from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base


class EvidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


class RetentionClass(StrEnum):
    OPERATIONAL = "operational"
    FINANCIAL = "financial"
    COMPLIANCE = "compliance"
    EXPERIMENT = "experiment"
    SECURITY = "security"


UNIQUE_SOURCE_REF_SOURCES = {
    "browser-capture-inbox",
    "channel_account_authorization_consent",
    "channel_account_authorization_lifecycle",
    "channel_account_compensation_plan",
    "channel_account_governance_review",
    "channel_account_governance_submission",
    "channel_account_kill_switch_release",
    "channel_account_official_readback",
    "channel_account_one_time_permit",
    "marketplace-observation",
    "ozon-isolated-execution-worker",
    "scope_authority_review",
    "scope_authority_source",
    "seller_erp_bridge_binding",
    "seller_erp_bridge_review",
    "seller_erp_bridge_revocation",
    "seller_erp_bridge_source",
    "supplier_rfq_dispatch",
    "supplier_rfq_package",
}

CHANNEL_ACCOUNT_RESERVED_SOURCES = frozenset(
    {
        "channel_account_authorization_consent",
        "channel_account_authorization_lifecycle",
        "channel_account_compensation_plan",
        "channel_account_governance_review",
        "channel_account_governance_submission",
        "channel_account_kill_switch_release",
        "channel_account_official_readback",
        "channel_account_one_time_permit",
    }
)
CHANNEL_ACCOUNT_RESERVED_CONTRACTS = frozenset(
    {
        "kjds-channel-account-consent-evidence-v1",
        "kjds-channel-account-governance-submission-v1",
        "kjds-channel-account-kill-switch-evidence-v1",
        "kjds-channel-account-lifecycle-evidence-v1",
        "kjds-channel-account-one-time-permit-v1",
        "kjds-channel-account-readback-v1",
        "kjds-channel-account-compensation-evidence-v1",
        "kjds-channel-account-sod-review-v1",
    }
)
_RESERVED_CAPTURE_AUTHORITY = object()

RETENTION_REVIEW_DAYS = {
    RetentionClass.OPERATIONAL: 365,
    RetentionClass.FINANCIAL: 3650,
    RetentionClass.COMPLIANCE: 3650,
    RetentionClass.EXPERIMENT: 1095,
    RetentionClass.SECURITY: 2555,
}


class EvidenceBlobRow(Base):
    __tablename__ = "evidence_blobs"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceRecordRow(Base):
    __tablename__ = "evidence_records"
    __table_args__ = (
        UniqueConstraint("blob_sha256", "source", "source_ref", "effective_at", name="uq_evidence_capture"),
        Index(
            "uq_execution_evidence_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'ozon-isolated-execution-worker'"),
            sqlite_where=text("source = 'ozon-isolated-execution-worker'"),
        ),
        Index(
            "uq_scope_authority_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'scope_authority_source'"),
            sqlite_where=text("source = 'scope_authority_source'"),
        ),
        Index(
            "uq_scope_authority_review_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'scope_authority_review'"),
            sqlite_where=text("source = 'scope_authority_review'"),
        ),
        Index(
            "uq_seller_erp_bridge_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'seller_erp_bridge_source'"),
            sqlite_where=text("source = 'seller_erp_bridge_source'"),
        ),
        Index(
            "uq_seller_erp_bridge_review_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'seller_erp_bridge_review'"),
            sqlite_where=text("source = 'seller_erp_bridge_review'"),
        ),
        Index(
            "uq_seller_erp_bridge_binding_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'seller_erp_bridge_binding'"),
            sqlite_where=text("source = 'seller_erp_bridge_binding'"),
        ),
        Index(
            "uq_seller_erp_bridge_revocation_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text("source = 'seller_erp_bridge_revocation'"),
            sqlite_where=text("source = 'seller_erp_bridge_revocation'"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    blob_sha256: Mapped[str] = mapped_column(ForeignKey("evidence_blobs.sha256"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    grade: Mapped[str] = mapped_column(String, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class LineageEdgeRow(Base):
    __tablename__ = "lineage_edges"
    __table_args__ = (
        UniqueConstraint(
            "from_type",
            "from_id",
            "to_type",
            "to_id",
            "relationship",
            name="uq_lineage_edge",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    from_type: Mapped[str] = mapped_column(String, nullable=False)
    from_id: Mapped[str] = mapped_column(String, nullable=False)
    to_type: Mapped[str] = mapped_column(String, nullable=False)
    to_id: Mapped[str] = mapped_column(String, nullable=False)
    relationship: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: str
    sha256: str
    byte_size: int
    filename: str
    content_type: str
    source: str
    source_ref: str
    grade: EvidenceGrade
    effective_at: str
    effective_until: str | None
    recorded_at: str
    created_by: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LineageEdge:
    id: str
    from_type: str
    from_id: str
    to_type: str
    to_id: str
    relationship: str
    created_by: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class EvidenceVerification:
    evidence_id: str
    expected_sha256: str
    actual_sha256: str
    byte_size: int
    valid: bool


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityFinding:
    evidence_id: str
    declared_sha256: str
    actual_sha256: str | None
    declared_byte_size: int | None
    actual_byte_size: int | None
    codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceIntegrityScan:
    total: int
    offset: int
    scanned: int
    valid: int
    invalid: int
    next_offset: int | None
    findings: tuple[EvidenceIntegrityFinding, ...]


@dataclass(frozen=True, slots=True)
class RetentionAssessment:
    evidence_id: str
    retention_class: str | None
    legal_hold: bool
    review_due_at: str | None
    status: str
    archive_eligible: bool
    automatic_delete_allowed: bool = False


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


class EvidenceService:
    def __init__(self, engine) -> None:
        self.engine = engine

    def capture(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        source: str,
        source_ref: str,
        grade: EvidenceGrade,
        effective_at: str,
        effective_until: str | None,
        created_by: str,
        metadata: dict[str, Any] | None = None,
        _reserved_authority: object | None = None,
        _session: Session | None = None,
    ) -> EvidenceRecord:
        if not content:
            raise ValueError("Evidence content cannot be empty")
        filename = filename.strip()
        content_type = content_type.strip() or "application/octet-stream"
        source = source.strip()
        source_ref = source_ref.strip()
        if not filename or not source or not source_ref:
            raise ValueError("Evidence requires filename, source, and source_ref")
        effective = parse_timestamp(effective_at, "effective_at")
        effective_end = parse_timestamp(effective_until, "effective_until") if effective_until else None
        if effective_end is not None and effective_end <= effective:
            raise ValueError("effective_until must be later than effective_at")

        metadata = metadata or {}
        if (
            source.strip().lower() in CHANNEL_ACCOUNT_RESERVED_SOURCES
            or str(metadata.get("contract_id") or "").strip() in CHANNEL_ACCOUNT_RESERVED_CONTRACTS
            or str(metadata.get("channel_account_review_contract_id") or "").strip()
            == "kjds-channel-account-sod-review-v1"
        ) and _reserved_authority is not _RESERVED_CAPTURE_AUTHORITY:
            raise ValueError("Reserved channel account Evidence requires the dedicated separation-of-duties workflow")
        retention_class = metadata.get("retention_class")
        if retention_class is not None:
            try:
                RetentionClass(retention_class)
            except ValueError as exc:
                raise ValueError(f"Unsupported retention_class: {retention_class}") from exc
        if "legal_hold" in metadata and not isinstance(metadata["legal_hold"], bool):
            raise ValueError("legal_hold must be true or false")

        digest = hashlib.sha256(content).hexdigest()
        now = datetime.now(UTC)
        if _session is not None:
            blob = _session.get(EvidenceBlobRow, digest)
            if blob is None:
                _session.add(
                    EvidenceBlobRow(
                        sha256=digest,
                        byte_size=len(content),
                        content_bytes=content,
                        created_at=now,
                    )
                )
            existing = self._captured_row(
                _session,
                digest=digest,
                source=source,
                source_ref=source_ref,
                effective_at=effective,
            )
            if existing is not None:
                return self._record(existing, len(content))
            if source in UNIQUE_SOURCE_REF_SOURCES:
                source_ref_winner = self._source_ref_row(
                    _session,
                    source=source,
                    source_ref=source_ref,
                )
                if source_ref_winner is not None:
                    if not hmac.compare_digest(
                        source_ref_winner.blob_sha256,
                        digest,
                    ):
                        raise ValueError(
                            "Evidence source reference already has different immutable content"
                        )
                    return self._record(source_ref_winner, len(content))
            row = EvidenceRecordRow(
                id=new_id("evd"),
                blob_sha256=digest,
                filename=filename,
                content_type=content_type,
                source=source,
                source_ref=source_ref,
                grade=grade.value,
                effective_at=effective,
                effective_until=effective_end,
                recorded_at=now,
                created_by=created_by,
                metadata_json=metadata,
            )
            _session.add(row)
            _session.flush()
            return self._record(row, len(content))
        try:
            with Session(self.engine) as session, session.begin():
                blob = session.get(EvidenceBlobRow, digest)
                if blob is None:
                    session.add(
                        EvidenceBlobRow(sha256=digest, byte_size=len(content), content_bytes=content, created_at=now)
                    )
                existing = self._captured_row(
                    session,
                    digest=digest,
                    source=source,
                    source_ref=source_ref,
                    effective_at=effective,
                )
                if existing is not None:
                    return self._record(existing, len(content))
                if source in UNIQUE_SOURCE_REF_SOURCES:
                    source_ref_winner = self._source_ref_row(
                        session,
                        source=source,
                        source_ref=source_ref,
                    )
                    if source_ref_winner is not None:
                        if not hmac.compare_digest(source_ref_winner.blob_sha256, digest):
                            raise ValueError("Evidence source reference already has different immutable content")
                        return self._record(source_ref_winner, len(content))
                row = EvidenceRecordRow(
                    id=new_id("evd"),
                    blob_sha256=digest,
                    filename=filename,
                    content_type=content_type,
                    source=source,
                    source_ref=source_ref,
                    grade=grade.value,
                    effective_at=effective,
                    effective_until=effective_end,
                    recorded_at=now,
                    created_by=created_by,
                    metadata_json=metadata,
                )
                session.add(row)
                session.flush()
                return self._record(row, len(content))
        except IntegrityError:
            with Session(self.engine) as session:
                winner = self._captured_row(
                    session,
                    digest=digest,
                    source=source,
                    source_ref=source_ref,
                    effective_at=effective,
                )
                if winner is None and source in UNIQUE_SOURCE_REF_SOURCES:
                    winner = self._source_ref_row(
                        session,
                        source=source,
                        source_ref=source_ref,
                    )
                if winner is None:
                    raise
                if not hmac.compare_digest(winner.blob_sha256, digest):
                    raise ValueError("Evidence source reference already has different immutable content") from None
                return self._record(winner, len(content))

    def get(self, evidence_id: str) -> EvidenceRecord:
        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            if blob is None:
                raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
            return self._record(row, blob.byte_size)

    def get_metadata(self, evidence_id: str) -> EvidenceRecord:
        """Load record metadata and blob size without selecting blob content."""

        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            return self._record(row, 0)

    def list(self, limit: int = 100) -> list[EvidenceRecord]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
                .join(EvidenceBlobRow, EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256)
                .order_by(EvidenceRecordRow.recorded_at.desc(), EvidenceRecordRow.id)
                .limit(limit)
            ).all()
            return [self._record(row, byte_size) for row, byte_size in rows]

    def list_by_source(self, source: str, limit: int = 100) -> list[EvidenceRecord]:
        source = source.strip()
        if not source:
            raise ValueError("Evidence source is required")
        with Session(self.engine) as session:
            rows = session.execute(
                select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
                .join(
                    EvidenceBlobRow,
                    EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256,
                )
                .where(EvidenceRecordRow.source == source)
                .order_by(EvidenceRecordRow.recorded_at.desc(), EvidenceRecordRow.id)
                .limit(min(max(limit, 1), 2000))
            ).all()
            return [self._record(row, byte_size) for row, byte_size in rows]

    def find_by_source_ref(self, *, source: str, source_ref: str) -> EvidenceRecord | None:
        source = source.strip()
        source_ref = source_ref.strip()
        if not source or not source_ref:
            raise ValueError("Evidence source and source_ref are required")
        with Session(self.engine) as session:
            result = session.execute(
                select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
                .join(EvidenceBlobRow, EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256)
                .where(
                    EvidenceRecordRow.source == source,
                    EvidenceRecordRow.source_ref == source_ref,
                )
                .order_by(EvidenceRecordRow.recorded_at, EvidenceRecordRow.id)
                .limit(1)
            ).first()
            if result is None:
                return None
            row, byte_size = result
            return self._record(row, byte_size)

    def find_binding_ids(
        self,
        *,
        target_evidence_ids: list[str],
        binding_contract_id: str,
        as_of: datetime,
    ) -> list[str]:
        """Find current immutable bindings without scanning the global ledger."""
        targets = sorted({item.strip() for item in target_evidence_ids if item.strip()})
        contract = binding_contract_id.strip()
        if not targets:
            return []
        if not contract:
            raise ValueError("binding_contract_id is required")
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        cutoff = as_of.astimezone(UTC)
        with Session(self.engine) as session:
            return list(
                session.scalars(
                    select(EvidenceRecordRow.id)
                    .where(
                        EvidenceRecordRow.metadata_json["evidence_scope_contract_id"].as_string() == contract,
                        EvidenceRecordRow.metadata_json["target_evidence_id"].as_string().in_(targets),
                        EvidenceRecordRow.effective_at <= cutoff,
                        (EvidenceRecordRow.effective_until.is_(None) | (EvidenceRecordRow.effective_until > cutoff)),
                    )
                    .order_by(EvidenceRecordRow.id)
                )
            )

    def content(self, evidence_id: str) -> tuple[bytes, EvidenceRecord]:
        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            if blob is None:
                raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
            return blob.content_bytes, self._record(row, blob.byte_size)

    def verify(self, evidence_id: str) -> EvidenceVerification:
        _, verification = self.inspect_integrity(evidence_id)
        return verification

    def scan_integrity(
        self,
        *,
        limit: int = 500,
        offset: int = 0,
        excluded_sources: tuple[str, ...] = (),
    ) -> EvidenceIntegrityScan:
        """Verify a bounded record/blob snapshot, including records whose blob is missing."""
        if not 1 <= limit <= 1000:
            raise ValueError("Evidence integrity scan limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("Evidence integrity scan offset cannot be negative")
        excluded_sources = tuple(sorted({item.strip() for item in excluded_sources if item.strip()}))
        with Session(self.engine) as session:
            count_query = select(func.count()).select_from(EvidenceRecordRow)
            rows_query = (
                select(EvidenceRecordRow, EvidenceBlobRow)
                .outerjoin(EvidenceBlobRow, EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256)
                .order_by(EvidenceRecordRow.recorded_at, EvidenceRecordRow.id)
                .offset(offset)
                .limit(limit)
            )
            if excluded_sources:
                source_filter = EvidenceRecordRow.source.not_in(excluded_sources)
                count_query = count_query.where(source_filter)
                rows_query = rows_query.where(source_filter)
            total = int(session.scalar(count_query) or 0)
            rows = list(session.execute(rows_query).all())
            snapshots = [
                (
                    row.id,
                    row.blob_sha256,
                    blob.byte_size if blob is not None else None,
                    bytes(blob.content_bytes) if blob is not None else None,
                )
                for row, blob in rows
            ]

        findings: list[EvidenceIntegrityFinding] = []
        for evidence_id, declared_sha256, declared_byte_size, content in snapshots:
            if content is None:
                findings.append(
                    EvidenceIntegrityFinding(
                        evidence_id,
                        declared_sha256,
                        None,
                        None,
                        None,
                        ("EVIDENCE_BLOB_MISSING",),
                    )
                )
                continue
            actual_sha256 = hashlib.sha256(content).hexdigest()
            actual_byte_size = len(content)
            codes = []
            if not hmac_compare(declared_sha256, actual_sha256):
                codes.append("EVIDENCE_HASH_MISMATCH")
            if declared_byte_size != actual_byte_size:
                codes.append("EVIDENCE_SIZE_MISMATCH")
            if codes:
                findings.append(
                    EvidenceIntegrityFinding(
                        evidence_id,
                        declared_sha256,
                        actual_sha256,
                        declared_byte_size,
                        actual_byte_size,
                        tuple(codes),
                    )
                )

        scanned = len(snapshots)
        next_offset = offset + scanned if offset + scanned < total else None
        return EvidenceIntegrityScan(
            total=total,
            offset=offset,
            scanned=scanned,
            valid=scanned - len(findings),
            invalid=len(findings),
            next_offset=next_offset,
            findings=tuple(findings),
        )

    def inspect_integrity(self, evidence_id: str) -> tuple[EvidenceRecord, EvidenceVerification]:
        """Read record and blob in one snapshot and recompute the blob digest."""
        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            if blob is None:
                raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
            content = bytes(blob.content_bytes)
            record = self._record(row, blob.byte_size)
        actual = hashlib.sha256(content).hexdigest()
        verification = EvidenceVerification(
            record.id,
            record.sha256,
            actual,
            len(content),
            hmac_compare(record.sha256, actual),
        )
        return record, verification

    def retention(self, evidence_id: str, *, as_of: datetime | None = None) -> RetentionAssessment:
        record = self.get(evidence_id)
        class_value = record.metadata.get("retention_class")
        legal_hold = record.metadata.get("legal_hold", False)
        if class_value is None:
            return RetentionAssessment(record.id, None, legal_hold, None, "classification_required", False)

        retention_class = RetentionClass(class_value)
        recorded_at = datetime.fromisoformat(record.recorded_at.replace("Z", "+00:00"))
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        review_due = recorded_at.astimezone(UTC) + timedelta(days=RETENTION_REVIEW_DAYS[retention_class])
        now = (as_of or datetime.now(UTC)).astimezone(UTC)
        status = "legal_hold" if legal_hold else "review_due" if now >= review_due else "active"
        return RetentionAssessment(
            record.id,
            retention_class.value,
            legal_hold,
            review_due.isoformat(),
            status,
            status == "review_due",
        )

    def require_valid(self, evidence_ids: list[str]) -> None:
        normalized = self._normalized_evidence_ids(evidence_ids)
        for evidence_id in normalized:
            verification = self.verify(evidence_id)
            if not verification.valid:
                raise ValueError(f"Evidence failed hash verification: {evidence_id}")

    def require_current(
        self,
        evidence_ids: list[str],
        *,
        as_of: datetime | None = None,
    ) -> None:
        """Require immutable evidence that is effective at the execution decision time."""
        normalized = self._normalized_evidence_ids(evidence_ids)
        current = as_of or datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        current = current.astimezone(UTC)
        for evidence_id in normalized:
            record, verification = self.inspect_integrity(evidence_id)
            if not verification.valid:
                raise ValueError(f"Evidence failed hash verification: {evidence_id}")
            effective_at = self._stored_timestamp(record.effective_at)
            effective_until = self._stored_timestamp(record.effective_until) if record.effective_until else None
            if effective_at > current:
                raise ValueError(f"Evidence is not yet effective: {evidence_id}")
            if effective_until is not None and current >= effective_until:
                raise ValueError(f"Evidence is no longer effective: {evidence_id}")

    @staticmethod
    def _normalized_evidence_ids(evidence_ids: list[str]) -> list[str]:
        normalized = [item.strip() for item in evidence_ids if item.strip()]
        if not normalized:
            raise ValueError("At least one immutable evidence record is required")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Duplicate evidence references are not allowed")
        return normalized

    @staticmethod
    def _stored_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    def link(
        self,
        *,
        evidence_id: str,
        target_type: str,
        target_id: str,
        relationship: str,
        created_by: str,
    ) -> LineageEdge:
        self.get(evidence_id)
        target_type = target_type.strip().lower()
        target_id = target_id.strip()
        relationship = relationship.strip()
        if not target_type or not target_id or not relationship:
            raise ValueError("Lineage requires target_type, target_id, and relationship")
        if target_type == "evidence":
            self.get(target_id)
            if target_id == evidence_id:
                raise ValueError("Evidence cannot derive from itself")
        try:
            with Session(self.engine) as session, session.begin():
                existing = self._lineage_row(
                    session,
                    evidence_id=evidence_id,
                    target_type=target_type,
                    target_id=target_id,
                    relationship=relationship,
                )
                if existing is not None:
                    return self._edge(existing)
                row = LineageEdgeRow(
                    id=new_id("lin"),
                    from_type="evidence",
                    from_id=evidence_id,
                    to_type=target_type,
                    to_id=target_id,
                    relationship=relationship,
                    created_by=created_by,
                    recorded_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                return self._edge(row)
        except IntegrityError:
            with Session(self.engine) as session:
                winner = self._lineage_row(
                    session,
                    evidence_id=evidence_id,
                    target_type=target_type,
                    target_id=target_id,
                    relationship=relationship,
                )
                if winner is None:
                    raise
                return self._edge(winner)

    def lineage(self, evidence_id: str) -> list[LineageEdge]:
        self.get(evidence_id)
        with Session(self.engine) as session:
            rows = session.scalars(
                select(LineageEdgeRow)
                .where(
                    (LineageEdgeRow.from_type == "evidence") & (LineageEdgeRow.from_id == evidence_id)
                    | (LineageEdgeRow.to_type == "evidence") & (LineageEdgeRow.to_id == evidence_id)
                )
                .order_by(LineageEdgeRow.recorded_at, LineageEdgeRow.id)
            ).all()
        return [self._edge(row) for row in rows]

    def target_evidence_ids(
        self,
        *,
        target_type: str,
        target_id: str,
        relationship: str | None = None,
    ) -> list[str]:
        target_type = target_type.strip().lower()
        target_id = target_id.strip()
        if not target_type or not target_id:
            raise ValueError("Target evidence lookup requires target_type and target_id")
        relationship = relationship.strip() if relationship else None
        with Session(self.engine) as session:
            query = select(LineageEdgeRow.from_id).where(
                LineageEdgeRow.from_type == "evidence",
                LineageEdgeRow.to_type == target_type,
                LineageEdgeRow.to_id == target_id,
            )
            if relationship:
                query = query.where(LineageEdgeRow.relationship == relationship)
            return list(session.scalars(query.distinct().order_by(LineageEdgeRow.from_id)).all())

    @staticmethod
    def _record(row: EvidenceRecordRow, byte_size: int) -> EvidenceRecord:
        return EvidenceRecord(
            row.id,
            row.blob_sha256,
            byte_size,
            row.filename,
            row.content_type,
            row.source,
            row.source_ref,
            EvidenceGrade(row.grade),
            row.effective_at.isoformat(),
            row.effective_until.isoformat() if row.effective_until else None,
            row.recorded_at.isoformat(),
            row.created_by,
            row.metadata_json,
        )

    @staticmethod
    def _captured_row(
        session: Session,
        *,
        digest: str,
        source: str,
        source_ref: str,
        effective_at: datetime,
    ) -> EvidenceRecordRow | None:
        return session.scalar(
            select(EvidenceRecordRow).where(
                EvidenceRecordRow.blob_sha256 == digest,
                EvidenceRecordRow.source == source,
                EvidenceRecordRow.source_ref == source_ref,
                EvidenceRecordRow.effective_at == effective_at,
            )
        )

    @staticmethod
    def _source_ref_row(
        session: Session,
        *,
        source: str,
        source_ref: str,
    ) -> EvidenceRecordRow | None:
        return session.scalar(
            select(EvidenceRecordRow).where(
                EvidenceRecordRow.source == source,
                EvidenceRecordRow.source_ref == source_ref,
            )
        )

    @staticmethod
    def _lineage_row(
        session: Session,
        *,
        evidence_id: str,
        target_type: str,
        target_id: str,
        relationship: str,
    ) -> LineageEdgeRow | None:
        return session.scalar(
            select(LineageEdgeRow).where(
                LineageEdgeRow.from_type == "evidence",
                LineageEdgeRow.from_id == evidence_id,
                LineageEdgeRow.to_type == target_type,
                LineageEdgeRow.to_id == target_id,
                LineageEdgeRow.relationship == relationship,
            )
        )

    @staticmethod
    def _edge(row: LineageEdgeRow) -> LineageEdge:
        return LineageEdge(
            row.id,
            row.from_type,
            row.from_id,
            row.to_type,
            row.to_id,
            row.relationship,
            row.created_by,
            row.recorded_at.isoformat(),
        )


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
