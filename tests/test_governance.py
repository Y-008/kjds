import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane import governance as governance_module
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.governance import GovernanceService
from apps.control_plane.sql_repository import Base, EventRow


def service():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    record = evidence.capture(
        content=b"approved gate evidence",
        filename="gate.txt",
        content_type="text/plain",
        source="test",
        source_ref="gate-review",
        grade=EvidenceGrade.A,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="owner",
    )
    return GovernanceService(engine=engine, evidence=evidence), record.id


def payload(evidence_id: str):
    return {
        "idempotency_key": "g0-review-1",
        "gate_id": "G0",
        "owner_id": "owner",
        "approver_id": "approver",
        "participants": ["owner", "finance"],
        "objective": "Confirm the business can enter controlled pilot.",
        "exit_criteria": "Owner, approver, evidence and loss limits are explicit.",
        "deliverables": ["G0 evidence pack", "Risk register"],
        "evidence_ids": [],
        "unknowns": ["Live Ozon settlement sample"],
        "blockers": [],
        "risk_budget": {"amount": "10000", "currency": "CNY"},
        "max_loss": {"amount": "3000", "currency": "CNY"},
        "rollback_plan": "Stop writes, preserve evidence, and return to read-only mode.",
        "actor_id": "owner",
    }


def test_gate_review_requires_independent_approver_and_is_idempotent():
    governance, evidence_id = service()
    data = payload(evidence_id)
    with pytest.raises(ValueError, match="different identities"):
        governance.create(**{**data, "approver_id": "owner"})
    created = governance.create(**data)
    retry = governance.create(**data)
    assert retry["id"] == created["id"]
    assert created["status"] == "draft"
    assert created["approver_id"] == "approver"
    assert "approver" in created["participants"]


def test_gate_review_submit_and_decide_require_evidence_and_separation():
    governance, evidence_id = service()
    created = governance.create(**payload(evidence_id))
    with pytest.raises((KeyError, ValueError)):
        governance.submit(created["id"], evidence_ids=["missing"], actor_id="owner")
    submitted = governance.submit(created["id"], evidence_ids=[evidence_id], actor_id="owner")
    assert submitted["status"] == "submitted"
    with pytest.raises(ValueError, match="named approver"):
        governance.decide(
            created["id"],
            decision="PASS",
            rationale="not independent",
            conditions=[],
            actor_id="owner",
        )
    decided = governance.decide(
        created["id"],
        decision="CONDITIONAL",
        rationale="Proceed only after live settlement evidence is attached.",
        conditions=["Attach settlement sample before G1."],
        actor_id="approver",
    )
    assert decided["status"] == "decided"
    assert decided["decision"] == "CONDITIONAL"
    assert decided["evidence_ids"] == [evidence_id]
    with Session(governance.engine) as session:
        events = list(session.scalars(select(EventRow).order_by(EventRow.sequence)))
    assert [event.event_type for event in events] == [
        "gate_review.created",
        "gate_review.submitted",
        "gate_review.decided",
    ]
    assert [event.actor_id for event in events] == ["owner", "owner", "approver"]
    assert events[1].source_evidence_id == evidence_id
    assert events[2].payload_json == {
        "gate_id": "G0",
        "status": "decided",
        "decision": "CONDITIONAL",
        "condition_count": 1,
    }


def test_gate_decision_rolls_back_when_outbox_write_fails(monkeypatch):
    governance, evidence_id = service()
    created = governance.create(**payload(evidence_id))
    governance.submit(created["id"], evidence_ids=[evidence_id], actor_id="owner")
    real_add = governance_module.add_outbox_event

    def fail_decision(session, event_type, *args, **kwargs):
        if event_type == "gate_review.decided":
            raise RuntimeError("simulated outbox failure")
        return real_add(session, event_type, *args, **kwargs)

    monkeypatch.setattr(governance_module, "add_outbox_event", fail_decision)
    with pytest.raises(RuntimeError, match="simulated outbox failure"):
        governance.decide(
            created["id"],
            decision="PASS",
            rationale="All exit evidence is valid.",
            conditions=[],
            actor_id="approver",
        )

    stored = governance.get(created["id"])
    assert stored["status"] == "submitted"
    assert stored["decision"] is None
    with Session(governance.engine) as session:
        event_types = list(
            session.scalars(select(EventRow.event_type).order_by(EventRow.sequence))
        )
    assert event_types == ["gate_review.created", "gate_review.submitted"]


def test_gate_review_rejects_loss_above_budget():
    governance, evidence_id = service()
    data = payload(evidence_id)
    data["max_loss"] = {"amount": "10001", "currency": "CNY"}
    with pytest.raises(ValueError, match="exceed risk budget"):
        governance.create(**data)
