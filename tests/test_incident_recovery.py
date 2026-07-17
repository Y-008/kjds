import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.incident_recovery import RECOVERY_CHECKS, IncidentRecoveryService
from apps.control_plane.security import KillSwitchService
from apps.control_plane.sql_repository import Base


def setup_service():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    source = evidence.capture(
        content=b"incident recovery evidence",
        filename="incident.txt",
        content_type="text/plain",
        source="test",
        source_ref="incident-recovery",
        grade=EvidenceGrade.A,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="monitor",
    )
    kill_switch = KillSwitchService(engine)
    return (
        IncidentRecoveryService(
            engine=engine,
            evidence=evidence,
            kill_switch=kill_switch,
        ),
        kill_switch,
        source,
    )


def test_live_incident_requires_checklist_independent_review_and_explicit_release():
    service, kill_switch, source = setup_service()
    incident = service.open(
        idempotency_key="ozon-write-uncertain-1",
        mode="live",
        severity="critical",
        trigger_type="remote_write_uncertain",
        source_type="limited_execution_command",
        source_id="lec-1",
        summary="Ozon write result cannot be confirmed",
        impact=["listing:offer-1", "store:ozon-ru"],
        evidence_ids=[source.id],
        opened_by="risk-owner",
    )
    retry = service.open(
        idempotency_key="ozon-write-uncertain-1",
        mode="live",
        severity="critical",
        trigger_type="remote_write_uncertain",
        source_type="limited_execution_command",
        source_id="lec-1",
        summary="Ozon write result cannot be confirmed",
        impact=["store:ozon-ru", "listing:offer-1"],
        evidence_ids=[source.id],
        opened_by="risk-owner",
    )
    assert retry["id"] == incident["id"]
    assert kill_switch.current().engaged is True
    assert incident["status"] == "contained"
    incident = service.claim(incident["id"], actor_id="recovery-owner")
    assert incident["status"] == "recovering"

    with pytest.raises(ValueError, match="checklist is incomplete"):
        service.submit_review(incident["id"], actor_id="recovery-owner")
    for check in RECOVERY_CHECKS:
        incident = service.record_check(
            incident["id"],
            check=check,
            passed=True,
            notes=f"Verified {check}",
            evidence_ids=[source.id],
            actor_id="recovery-owner",
        )
    incident = service.submit_review(incident["id"], actor_id="recovery-owner")
    assert incident["status"] == "pending_review"
    with pytest.raises(ValueError, match="independent"):
        service.review(
            incident["id"],
            accepted=True,
            rationale="Self review is prohibited",
            evidence_ids=[source.id],
            actor_id="recovery-owner",
        )
    incident = service.review(
        incident["id"],
        accepted=True,
        rationale="Remote state, data, credentials, and monitoring are reconciled",
        evidence_ids=[source.id],
        actor_id="independent-reviewer",
    )
    assert incident["status"] == "ready_for_release"
    assert incident["automatic_release"] is False
    with pytest.raises(ValueError, match="explicitly release"):
        service.close(
            incident["id"],
            notes="Cannot close while frozen",
            evidence_ids=[source.id],
            actor_id="admin-owner",
        )
    kill_switch.set_state(
        engaged=False,
        reason="Independent recovery review accepted",
        actor_id="admin-owner",
    )
    incident = service.close(
        incident["id"],
        notes="Recovery verified and production writes remain manually controlled",
        evidence_ids=[source.id],
        actor_id="admin-owner",
    )
    assert incident["status"] == "closed"
    assert set(incident["checks"]) == set(RECOVERY_CHECKS)
    assert all(event["immutable"] for event in incident["events"])


def test_drill_uses_same_recovery_ledger_without_freezing_production():
    service, kill_switch, source = setup_service()
    incident = service.open(
        idempotency_key="quarterly-recovery-drill",
        mode="drill",
        severity="high",
        trigger_type="simulated_api_outage",
        source_type=None,
        source_id=None,
        summary="Quarterly Ozon API recovery exercise",
        impact=["simulated:ozon-worker"],
        evidence_ids=[source.id],
        opened_by="risk-owner",
    )
    assert incident["mode"] == "drill"
    assert incident["status"] == "open"
    assert kill_switch.current().engaged is False
