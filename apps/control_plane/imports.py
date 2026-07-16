from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceRecordRow
from .ozon_contracts import CONTRACTS, OzonRecordType, detect_record_type, normalize_record
from .sql_repository import Base

MAX_IMPORT_BYTES = 20 * 1024 * 1024
MAX_IMPORT_ROWS = 50_000

FIELD_ALIASES = {
    "external_id": {
        "external_id",
        "operation_id",
        "document_id",
        "order_id",
        "order_number",
        "номер документа",
        "номер заказа",
        "номер операции",
        "номер отправления",
        "номер возврата",
    },
    "sku": {"sku", "offer_id", "артикул", "артикул продавца"},
    "quantity": {"quantity", "qty", "количество"},
    "currency": {"currency", "валюта"},
    "gross_revenue": {"gross_revenue", "price", "revenue", "сумма", "цена", "итого"},
    "status": {"status", "статус"},
    "effective_at": {
        "effective_at",
        "created_at",
        "order_date",
        "date",
        "дата",
        "дата заказа",
        "дата операции",
        "дата начисления",
        "дата выплаты",
    },
    "fee_type": {"fee_type", "service", "commission_type", "услуга", "тип начисления"},
    "amount": {
        "amount",
        "fee_amount",
        "settlement_amount",
        "refund_amount",
        "итого",
        "итого, руб",
        "сумма выплаты",
        "сумма операции",
    },
    "return_reason": {"return_reason", "reason", "причина возврата"},
}


class ImportJobRow(Base):
    __tablename__ = "import_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String)
    record_type: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String)
    row_count: Mapped[int] = mapped_column(Integer)
    accepted_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    mapping_json: Mapped[dict[str, str]] = mapped_column(JSON)
    errors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey(EvidenceRecordRow.id), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportDataRow(Base):
    __tablename__ = "import_rows"
    __table_args__ = (UniqueConstraint("import_id", "row_number"),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("import_jobs.id"))
    row_number: Mapped[int] = mapped_column(Integer)
    record_type: Mapped[str] = mapped_column(String)
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    errors_json: Mapped[list[str]] = mapped_column(JSON)


@dataclass(frozen=True, slots=True)
class ImportResult:
    id: str
    source: str
    record_type: str
    filename: str
    sha256: str
    status: str
    row_count: int
    accepted_count: int
    rejected_count: int
    mapping: dict[str, str]
    errors: list[dict[str, Any]]
    evidence_id: str | None
    created_at: str
    duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean_header(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _detect_mapping(headers: list[str]) -> dict[str, str]:
    normalized_headers = {_clean_header(header): header for header in headers}
    mapping: dict[str, str] = {}
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in normalized_headers:
                mapping[canonical] = normalized_headers[alias]
                break
    return mapping


def _normalize(
    raw: dict[str, Any], mapping: dict[str, str], record_type: OzonRecordType
) -> tuple[dict[str, Any], list[str]]:
    result: dict[str, Any] = {}
    for canonical, header in mapping.items():
        value = raw.get(header)
        result[canonical] = str(value or "").strip()
    return normalize_record(record_type, result)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, Decimal)):
        return str(value)
    return str(value)


def _csv_rows(content: bytes) -> Iterable[dict[str, Any]]:
    decoded: str | None = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            decoded = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("CSV encoding must be UTF-8 or Windows-1251")
    sample = decoded[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    yield from csv.DictReader(io.StringIO(decoded), dialect=dialect)


def _xlsx_rows(content: bytes) -> Iterable[dict[str, Any]]:
    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sheet = workbook.active
    values = sheet.iter_rows(values_only=True)
    headers = [str(value or "").strip() for value in next(values, ())]
    for row in values:
        yield dict(zip(headers, row, strict=False))


class OzonImportService:
    def __init__(self, engine) -> None:
        self.engine = engine

    def find_by_content(self, content: bytes) -> ImportResult | None:
        digest = hashlib.sha256(content).hexdigest()
        with Session(self.engine) as session:
            existing = session.scalar(select(ImportJobRow).where(ImportJobRow.sha256 == digest))
            return self._result(existing, duplicate=True) if existing else None

    def import_file(self, *, filename: str, content: bytes, evidence_id: str | None = None) -> ImportResult:
        if not content:
            raise ValueError("Import file is empty")
        if len(content) > MAX_IMPORT_BYTES:
            raise ValueError("Import file exceeds 20 MB")
        extension = Path(filename).suffix.lower()
        if extension not in {".csv", ".xlsx"}:
            raise ValueError("Only CSV and XLSX imports are supported")
        digest = hashlib.sha256(content).hexdigest()
        existing = self.find_by_content(content)
        if existing:
            return existing

        raw_rows = list(_csv_rows(content) if extension == ".csv" else _xlsx_rows(content))
        if len(raw_rows) > MAX_IMPORT_ROWS:
            raise ValueError("Import file exceeds 50,000 rows")
        headers = list(raw_rows[0]) if raw_rows else []
        record_type = detect_record_type(filename, headers)
        mapping = _detect_mapping(headers)
        missing_columns = [name for name in sorted(CONTRACTS[record_type].required_fields) if name not in mapping]
        file_errors = [{"type": "missing_column", "field": name} for name in missing_columns]
        job_id = new_id("imp")
        accepted = 0
        rejected = 0
        data_rows: list[ImportDataRow] = []
        for row_number, raw in enumerate(raw_rows, start=2):
            normalized, errors = _normalize(raw, mapping, record_type)
            accepted += not errors
            rejected += bool(errors)
            data_rows.append(
                ImportDataRow(
                    id=new_id("row"),
                    import_id=job_id,
                    row_number=row_number,
                    record_type=record_type.value,
                    external_id=normalized.get("external_id"),
                    payload_json={str(key): _json_value(value) for key, value in raw.items()},
                    normalized_json=normalized,
                    errors_json=errors,
                )
            )
        status = "rejected" if missing_columns else ("completed_with_errors" if rejected else "completed")
        job = ImportJobRow(
            id=job_id,
            source="ozon-export",
            record_type=record_type.value,
            filename=Path(filename).name,
            sha256=digest,
            status=status,
            row_count=len(raw_rows),
            accepted_count=accepted,
            rejected_count=rejected,
            mapping_json=mapping,
            errors_json=file_errors,
            evidence_id=evidence_id,
            created_at=datetime.now(UTC),
        )
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            session.add(job)
            session.flush()
            session.add_all(data_rows)
        return self._result(job)

    def get(self, import_id: str) -> ImportResult:
        with Session(self.engine) as session:
            row = session.get(ImportJobRow, import_id)
            if row is None:
                raise KeyError(f"Unknown import: {import_id}")
            return self._result(row)

    @staticmethod
    def _result(row: ImportJobRow, *, duplicate: bool = False) -> ImportResult:
        return ImportResult(
            row.id,
            row.source,
            row.record_type,
            row.filename,
            row.sha256,
            row.status,
            row.row_count,
            row.accepted_count,
            row.rejected_count,
            row.mapping_json,
            row.errors_json,
            row.evidence_id,
            row.created_at.isoformat(),
            duplicate,
        )
