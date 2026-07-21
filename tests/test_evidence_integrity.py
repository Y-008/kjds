from sqlalchemy import create_engine, delete, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceBlobRow, EvidenceGrade, EvidenceService
from apps.control_plane.evidence_integrity import EvidenceIntegrityMonitorService
from apps.control_plane.incident_recovery import RECOVERY_CHECKS, IncidentRecoveryService
from apps.control_plane.security import KillSwitchService
from apps.control_plane.sql_repository import Base


def setup_monitor():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    kill_switch = KillSwitchService(engine)
    incidents = IncidentRecoveryService(
        engine=engine,
        evidence=evidence,
        kill_switch=kill_switch,
    )
    return engine, evidence, incidents, kill_switch, EvidenceIntegrityMonitorService(
        evidence=evidence,
        incidents=incidents,
    )


def capture(evidence: EvidenceService, source_ref: str):
    return evidence.capture(
        content=source_ref.encode(),
        filename="source.txt",
        content_type="text/plain",
        source="test",
        source_ref=source_ref,
        grade=EvidenceGrade.A,
        effective_at="2026-07-19T00:00:00Z",
        effective_until=None,
        created_by="operator",
    )


def test_monitor_creates_verifiable_idempotent_incident_without_global_release_or_repair():
    engine, evidence, incidents, kill_switch, monitor = setup_monitor()
    corrupt = capture(evidence, "integrity://corrupt")
    with Session(engine) as session, session.begin():
        session.execute(
            update(EvidenceBlobRow)
            .where(EvidenceBlobRow.sha256 == corrupt.sha256)
            .values(content_bytes=b"integrity://corrupx")
        )

    first = monitor.scan(
        actor_id="monitor-a",
        as_of="2026-07-19T08:00:00Z",
    )
    retry = monitor.scan(
        actor_id="monitor-b",
        as_of="2026-07-19T09:00:00Z",
    )

    incident_id = first["incident_ids"][corrupt.id]
    assert retry["incident_ids"][corrupt.id] == incident_id
    assert retry["total"] == 1
    assert retry["scanned"] == 1
    assert len(incidents.list()) == 1
    assert incidents.get(incident_id)["severity"] == "medium"
    assert first["automatic_repair"] is False
    assert first["automatic_delete"] is False
    assert first["automatic_kill_switch_release"] is False
    assert kill_switch.current().engaged is False
    assert evidence.verify(first["finding_evidence_ids"][corrupt.id]).valid is True
    assert evidence.verify(first["scan_evidence_id"]).valid is True

    report_id = first["finding_evidence_ids"][corrupt.id]
    incidents.claim(incident_id, actor_id="recovery-owner")
    for check in RECOVERY_CHECKS:
        incidents.record_check(
            incident_id,
            check=check,
            passed=True,
            notes=f"Verified {check}",
            evidence_ids=[report_id],
            actor_id="recovery-owner",
        )
    incidents.submit_review(incident_id, actor_id="recovery-owner")
    incidents.review(
        incident_id,
        accepted=True,
        rationale="Integrity impact contained and recovery independently reviewed",
        evidence_ids=[report_id],
        actor_id="independent-reviewer",
    )
    incidents.close(
        incident_id,
        notes="Recovery completed without changing the original evidence in this test",
        evidence_ids=[report_id],
        actor_id="incident-closer",
    )
    recurrence = monitor.scan(
        actor_id="monitor-c",
        as_of="2026-07-19T10:00:00Z",
    )
    assert recurrence["incident_ids"][corrupt.id] != incident_id
    assert len(incidents.list()) == 2


def test_monitor_detects_record_whose_blob_is_missing_and_keeps_original_untouched():
    engine, evidence, incidents, _, monitor = setup_monitor()
    missing = capture(evidence, "integrity://missing")
    with Session(engine) as session, session.begin():
        session.execute(delete(EvidenceBlobRow).where(EvidenceBlobRow.sha256 == missing.sha256))

    result = monitor.scan(
        actor_id="monitor",
        as_of="2026-07-19T08:00:00Z",
    )

    finding = next(item for item in result["findings"] if item["evidence_id"] == missing.id)
    assert finding["codes"] == ("EVIDENCE_BLOB_MISSING",)
    assert incidents.get(result["incident_ids"][missing.id])["source_id"] == missing.id
    with Session(engine) as session:
        assert session.get(EvidenceBlobRow, missing.sha256) is None
