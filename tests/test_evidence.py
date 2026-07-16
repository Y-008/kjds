import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceBlobRow, EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base


def make_service():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, EvidenceService(engine)


def capture(service: EvidenceService, *, source_ref: str = "ozon-export://orders/2026-07-16"):
    return service.capture(
        content=b"order_id,amount\n1001,50\n",
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


def test_hash_verification_detects_blob_tampering():
    engine, service = make_service()
    record = capture(service)
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceBlobRow).where(EvidenceBlobRow.sha256 == record.sha256).values(content_bytes=b"tampered")
        )
    assert service.verify(record.id).valid is False


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
