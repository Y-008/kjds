import pytest
from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.api_contracts import LimitedExecutionReceiptInput
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.incident_recovery import RECOVERY_CHECKS, IncidentRecoveryService
from apps.control_plane.routers.execution_operations import record_limited_execution_receipt
from apps.control_plane.security import KillSwitchService, Principal
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


def test_uncertain_execution_receipt_opens_one_containment_incident(monkeypatch):
    from apps.control_plane.routers import execution_operations

    incidents, kill_switch, source = setup_service()
    receipt = {
        "id": "lxr-1",
        "command_id": "lxc-1",
        "outcome": "uncertain",
        "remote_operation_id": "42",
        "resulting_state_hash": None,
        "mutation_applied": False,
        "error_code": "REMOTE_WRITE_UNCERTAIN",
        "error_detail": "authoritative reconciliation required",
        "evidence_ids": [source.id],
    }

    class Executor:
        def record_receipt(self, command_id, **_values):
            assert command_id == "lxc-1"
            return receipt

        def get(self, command_id):
            assert command_id == "lxc-1"
            return {
                "plan_id": "gxp-1",
                "adapter_id": "ozon.product.import.v3",
                "target": {"offer_id": "offer-1"},
            }

    monkeypatch.setattr(execution_operations.runtime, "limited_executor", Executor())
    monkeypatch.setattr(execution_operations.runtime, "incident_recovery", incidents)
    request = Request({"type": "http"})
    request.state.request_id = "req-1"
    request.state.trace_id = "trace-1"
    body = LimitedExecutionReceiptInput(**{key: receipt[key] for key in (
        "outcome",
        "remote_operation_id",
        "resulting_state_hash",
        "mutation_applied",
        "error_code",
        "error_detail",
        "evidence_ids",
    )})
    principal = Principal("ozon-worker", frozenset({"executor"}))

    first = record_limited_execution_receipt("lxc-1", body, request, principal)
    retry = record_limited_execution_receipt("lxc-1", body, request, principal)

    assert retry["incident_id"] == first["incident_id"]
    assert kill_switch.current().engaged is True
    stored = incidents.get(first["incident_id"])
    assert stored["severity"] == "critical"
    assert stored["trigger_type"] == "remote_write_uncertain"
    assert stored["source_id"] == "lxc-1"
    assert len(incidents.list()) == 1
