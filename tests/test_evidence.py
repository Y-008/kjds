from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceGrade,
    EvidenceRecordRow,
    EvidenceService,
)
from apps.control_plane.sql_repository import Base


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, EvidenceService(engine)


def capture(
    service: EvidenceService,
    *,
    source_ref: str = "ozon-export://orders/2026-07-16",
    content: bytes = b"order_id,amount\n1001,50\n",
):
    return service.capture(
        content=content,
        filename="orders.csv",
        content_type="text/csv",
        source="ozon_export",
        source_ref=source_ref,
        grade=EvidenceGrade.A,
        effective_at="2026-07-15T00:00:00+03:00",
        effective_until=None,
        created_by="operator-1",
        metadata={"market": "RU"},
    )


def test_evidence_is_hashed_bitemporal_and_idempotent():
    _, service = make_service()
    first = capture(service)
    second = capture(service)

    assert second.id == first.id
    assert first.sha256 == "d6f3a486054a360be75359168c72ecda4da3e47f489f8cf9c8ec30a1e6a6b522"
    assert first.effective_at == "2026-07-14T21:00:00+00:00"
    assert first.recorded_at > first.effective_at
    assert service.verify(first.id).valid is True


def test_execution_evidence_source_ref_rejects_conflicting_content():
    engine, service = make_service()
    common = {
        "filename": "before.json",
        "content_type": "application/json",
        "source": "ozon-isolated-execution-worker",
        "source_ref": "execution://lxc-1/before_read",
        "grade": EvidenceGrade.A,
        "effective_at": "2026-07-15T00:00:00Z",
        "effective_until": None,
        "created_by": "ozon-worker",
    }
    first = service.capture(content=b'{"state":1}', **common)

    assert service.capture(content=b'{"state":1}', **common).id == first.id
    with pytest.raises(ValueError, match="different immutable content"):
        service.capture(content=b'{"state":2}', **common)
    with Session(engine) as session:
        assert session.query(EvidenceRecordRow).count() == 1


def test_other_evidence_sources_keep_bitemporal_source_ref_semantics():
    _, service = make_service()

    first = capture(service, source_ref="shared://reference", content=b"first")
    second = capture(service, source_ref="shared://reference", content=b"second")

    assert second.id != first.id


def test_hash_verification_detects_blob_tampering():
    engine, service = make_service()
    record = capture(service)
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceBlobRow).where(EvidenceBlobRow.sha256 == record.sha256).values(content_bytes=b"tampered")
        )
    assert service.verify(record.id).valid is False


def test_bounded_integrity_scan_detects_hash_size_and_missing_blob_failures():
    engine, service = make_service()
    healthy = capture(service, source_ref="scan://healthy", content=b"healthy")
    corrupt = capture(service, source_ref="scan://corrupt", content=b"corrupt")
    missing = service.capture(
        content=b"missing blob",
        filename="missing.txt",
        content_type="text/plain",
        source="test",
        source_ref="scan://missing",
        grade=EvidenceGrade.B,
        effective_at="2026-07-15T00:00:00Z",
        effective_until=None,
        created_by="monitor",
    )
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceBlobRow)
            .where(EvidenceBlobRow.sha256 == corrupt.sha256)
            .values(content_bytes=b"x", byte_size=99)
        )
        session.execute(delete(EvidenceBlobRow).where(EvidenceBlobRow.sha256 == missing.sha256))

    first = service.scan_integrity(limit=2)
    second = service.scan_integrity(limit=2, offset=2)
    findings = {item.evidence_id: item for item in (*first.findings, *second.findings)}

    assert first.total == 3
    assert first.scanned == 2
    assert first.next_offset == 2
    assert second.scanned == 1
    assert second.next_offset is None
    assert healthy.id not in findings
    assert findings[corrupt.id].codes == (
        "EVIDENCE_HASH_MISMATCH",
        "EVIDENCE_SIZE_MISMATCH",
    )
    assert findings[missing.id].codes == ("EVIDENCE_BLOB_MISSING",)


def test_retention_requires_classification_and_never_allows_automatic_deletion():
    _, service = make_service()
    unclassified = capture(service)
    assert service.retention(unclassified.id).status == "classification_required"

    classified = service.capture(
        content=b"settlement",
        filename="settlement.csv",
        content_type="text/csv",
        source="finance",
        source_ref="bank://settlement/1",
        grade=EvidenceGrade.A,
        effective_at="2026-07-15T00:00:00Z",
        effective_until=None,
        created_by="finance-operator",
        metadata={"retention_class": "financial", "legal_hold": True},
    )
    assessment = service.retention(classified.id)
    assert assessment.status == "legal_hold"
    assert assessment.archive_eligible is False
    assert assessment.automatic_delete_allowed is False
    assert assessment.review_due_at is not None


def test_capture_rejects_unknown_retention_class():
    _, service = make_service()
    with pytest.raises(ValueError, match="Unsupported retention_class"):
        service.capture(
            content=b"x",
            filename="x.txt",
            content_type="text/plain",
            source="test",
            source_ref="test://retention",
            grade=EvidenceGrade.C,
            effective_at="2026-07-15T00:00:00Z",
            effective_until=None,
            created_by="tester",
            metadata={"retention_class": "forever"},
        )


def test_evidence_gate_rejects_unknown_duplicate_and_tampered_references():
    engine, service = make_service()
    record = capture(service)
    service.require_valid([record.id])

    with pytest.raises(KeyError, match="Unknown evidence"):
        service.require_valid(["evd_missing"])
    with pytest.raises(ValueError, match="Duplicate evidence"):
        service.require_valid([record.id, record.id])

    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceBlobRow).where(EvidenceBlobRow.sha256 == record.sha256).values(content_bytes=b"tampered")
        )
    with pytest.raises(ValueError, match="failed hash verification"):
        service.require_valid([record.id])


def test_current_evidence_gate_is_time_bounded_without_changing_integrity_semantics():
    engine, service = make_service()
    record = capture(service, source_ref="current://evidence")
    boundary = datetime(2026, 7, 20, tzinfo=UTC)

    with Session(engine) as session, session.begin():
        row = session.get(EvidenceRecordRow, record.id)
        row.effective_at = boundary
        row.effective_until = boundary + timedelta(days=1)

    service.require_current([record.id], as_of=boundary)
    with pytest.raises(ValueError, match="no longer effective"):
        service.require_current(
            [record.id],
            as_of=boundary + timedelta(days=1),
        )
    with pytest.raises(ValueError, match="not yet effective"):
        service.require_current(
            [record.id],
            as_of=boundary - timedelta(microseconds=1),
        )

    service.require_valid([record.id])
    with pytest.raises(ValueError, match="as_of must include a timezone"):
        service.require_current([record.id], as_of=datetime(2026, 7, 20))
    with pytest.raises(ValueError, match="Duplicate evidence"):
        service.require_current([record.id, record.id], as_of=boundary)


def test_lineage_links_evidence_to_fact_and_other_evidence():
    _, service = make_service()
    source = capture(service)
    derived = service.capture(
        content=b"normalized order 1001",
        filename="normalized.json",
        content_type="application/json",
        source="normalizer",
        source_ref="job://normalize/1",
        grade=EvidenceGrade.B,
        effective_at="2026-07-15T00:00:00+03:00",
        effective_until=None,
        created_by="data-agent",
    )
    fact_edge = service.link(
        evidence_id=source.id,
        target_type="order",
        target_id="ord_1001",
        relationship="supports",
        created_by="operator-1",
    )
    derived_edge = service.link(
        evidence_id=source.id,
        target_type="evidence",
        target_id=derived.id,
        relationship="normalized_into",
        created_by="data-agent",
    )

    assert fact_edge.to_id == "ord_1001"
    assert {edge.id for edge in service.lineage(source.id)} == {fact_edge.id, derived_edge.id}
    assert service.target_evidence_ids(target_type="order", target_id="ord_1001") == [source.id]
