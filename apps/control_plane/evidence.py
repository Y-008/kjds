from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base


class EvidenceGrade(StrEnum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


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

        digest = hashlib.sha256(content).hexdigest()
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            blob = session.get(EvidenceBlobRow, digest)
            if blob is None:
                session.add(EvidenceBlobRow(sha256=digest, byte_size=len(content), content_bytes=content, created_at=now))
            existing = session.scalar(
                select(EvidenceRecordRow).where(
                    EvidenceRecordRow.blob_sha256 == digest,
                    EvidenceRecordRow.source == source,
                    EvidenceRecordRow.source_ref == source_ref,
                    EvidenceRecordRow.effective_at == effective,
                )
            )
            if existing is not None:
                return self._record(existing, len(content))
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
                metadata_json=metadata or {},
            )
            session.add(row)
            session.flush()
            return self._record(row, len(content))

    def get(self, evidence_id: str) -> EvidenceRecord:
        with Session(self.engine) as session:
            row = session.get(EvidenceRecordRow, evidence_id)
            if row is None:
                raise KeyError(f"Unknown evidence: {evidence_id}")
            blob = session.get(EvidenceBlobRow, row.blob_sha256)
            if blob is None:
                raise RuntimeError(f"Evidence blob is missing: {row.blob_sha256}")
            return self._record(row, blob.byte_size)

    def list(self, limit: int = 100) -> list[EvidenceRecord]:
        with Session(self.engine) as session:
            rows = session.execute(
                select(EvidenceRecordRow, EvidenceBlobRow.byte_size)
                .join(EvidenceBlobRow, EvidenceBlobRow.sha256 == EvidenceRecordRow.blob_sha256)
                .order_by(EvidenceRecordRow.recorded_at.desc(), EvidenceRecordRow.id)
                .limit(limit)
            ).all()
            return [self._record(row, byte_size) for row, byte_size in rows]

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
        content, record = self.content(evidence_id)
        actual = hashlib.sha256(content).hexdigest()
        return EvidenceVerification(record.id, record.sha256, actual, len(content), hmac_compare(record.sha256, actual))

    def require_valid(self, evidence_ids: list[str]) -> None:
        normalized = [item.strip() for item in evidence_ids if item.strip()]
        if not normalized:
            raise ValueError("At least one immutable evidence record is required")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Duplicate evidence references are not allowed")
        for evidence_id in normalized:
            verification = self.verify(evidence_id)
            if not verification.valid:
                raise ValueError(f"Evidence failed hash verification: {evidence_id}")

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
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(LineageEdgeRow).where(
                    LineageEdgeRow.from_type == "evidence",
                    LineageEdgeRow.from_id == evidence_id,
                    LineageEdgeRow.to_type == target_type,
                    LineageEdgeRow.to_id == target_id,
                    LineageEdgeRow.relationship == relationship,
                )
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
