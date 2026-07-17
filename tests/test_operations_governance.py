from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.operations_queue import OperationsQueueService
from apps.control_plane.pilot_readiness import PILOT_CONTROLS, PilotReadinessService
from apps.control_plane.sql_repository import Base


class FakeIncidents:
    def __init__(self, rows):
        self.rows = rows

    def list(self):
        return self.rows


class FakeExecutor:
    def __init__(self, rows=None):
        self.rows = rows or []

    def list(self):
        return self.rows


class FakePostExecution:
    def __init__(self, rows=None):
        self.rows = rows or []

    def list_windows(self):
        return self.rows


class FakeKillSwitch:
    def __init__(self, engaged=False):
        self.engaged = engaged

    def current(self):
        return SimpleNamespace(engaged=self.engaged)


def engine():
    value = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(value)
    return value


def evidence_record(evidence):
    return evidence.capture(
        content=b"operations governance evidence",
        filename="operations.txt",
        content_type="text/plain",
        source="test",
        source_ref="operations-governance",
        grade=EvidenceGrade.A,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="operator",
    )


def test_operations_queue_prioritizes_overdue_work_and_persists_escalation_once():
    database = engine()
    incidents = FakeIncidents(
        [
            {
                "id": "inc-critical",
                "status": "contained",
                "severity": "critical",
                "summary": "Remote state uncertain",
                "owner_id": None,
                "created_at": "2026-07-17T00:00:00+00:00",
            }
        ]
    )
    executor = FakeExecutor(
        [
            {
                "id": "lec-uncertain",
                "status": "uncertain",
                "command_kind": "execute",
                "operation": "ozon.product.import.v3",
                "claimed_by": "worker",
                "lease_expires_at": None,
                "created_at": "2026-07-17T00:20:00+00:00",
            }
        ]
    )
    windows = FakePostExecution(
        [
            {
                "id": "eow-1",
                "primary_metric": "contribution_profit_per_visitor",
                "created_by": "operator",
                "created_at": "2026-07-17T00:00:00+00:00",
                "ends_at": "2026-07-17T01:00:00+00:00",
                "evaluation": {"status": "monitoring"},
            }
        ]
    )
    service = OperationsQueueService(
        engine=database,
        incidents=incidents,
        limited_executor=executor,
        post_execution=windows,
    )
    queue = service.queue(as_of="2026-07-17T01:00:01+00:00")
    assert queue[0]["item_type"] == "incident"
    assert queue[0]["escalation_level"] == 3
    assert all(item["overdue"] for item in queue)
    first = service.scan(as_of="2026-07-17T01:00:01+00:00", actor_id="scheduler")
    retry = service.scan(as_of="2026-07-17T01:00:01+00:00", actor_id="scheduler")
    assert first["overdue_count"] == 3
    assert len(first["new_escalation_ids"]) >= 3
    assert retry["new_escalation_ids"] == []
    assert all(item["immutable"] for item in service.escalations())
    assert first["automatic_business_action"] is False


def test_read_only_pilot_requires_controls_drill_clean_state_and_independent_review():
    database = engine()
    evidence = EvidenceService(database)
    source = evidence_record(evidence)
    incidents = FakeIncidents(
        [
            {
                "id": "inc-drill",
                "mode": "drill",
                "status": "closed",
                "updated_at": "2026-07-16T00:00:00+00:00",
            }
        ]
    )
    switch = FakeKillSwitch()
    service = PilotReadinessService(
        engine=database,
        evidence=evidence,
        incidents=incidents,
        kill_switch=switch,
    )
    with pytest.raises(ValueError, match="read-only"):
        service.create(
            idempotency_key="bad-write-pilot",
            platform="ozon",
            account_alias="ozon-ru-main",
            allowed_operations=["ozon.product.import.v3"],
            max_daily_requests=10,
            max_targets=3,
            starts_at="2026-07-17T00:00:00+00:00",
            ends_at="2026-07-20T00:00:00+00:00",
            evidence_ids=[source.id],
            requested_by="pilot-owner",
        )
    pilot = service.create(
        idempotency_key="read-only-pilot-1",
        platform="ozon",
        account_alias="ozon-ru-main",
        allowed_operations=["ozon.product.read", "ozon.inventory.read"],
        max_daily_requests=100,
        max_targets=10,
        starts_at="2026-07-17T00:00:00+00:00",
        ends_at="2026-07-20T00:00:00+00:00",
        evidence_ids=[source.id],
        requested_by="pilot-owner",
    )
    assert service.evaluate(pilot["id"], as_of="2026-07-17T01:00:00+00:00")[
        "ready_for_review"
    ] is False
    for control in PILOT_CONTROLS:
        pilot = service.attest(
            pilot["id"],
            control=control,
            passed=True,
            notes=f"Verified {control}",
            evidence_ids=[source.id],
            attested_by="pilot-owner",
        )
    evaluation = service.evaluate(pilot["id"], as_of="2026-07-17T01:00:00+00:00")
    assert evaluation["ready_for_review"] is True
    assert evaluation["platform_write_allowed"] is False
    pilot = service.submit_review(
        pilot["id"], actor_id="pilot-owner", as_of="2026-07-17T01:00:00+00:00"
    )
    with pytest.raises(ValueError, match="independent"):
        service.review(
            pilot["id"], accepted=True, rationale="self review", actor_id="pilot-owner"
        )
    pilot = service.review(
        pilot["id"],
        accepted=True,
        rationale="Read-only scope and controls independently verified",
        actor_id="independent-reviewer",
    )
    pilot = service.activate(
        pilot["id"], actor_id="admin", as_of="2026-07-17T01:00:00+00:00"
    )
    assert pilot["status"] == "active"
    assert pilot["platform_write_allowed"] is False
    assert pilot["execution_eligible"] is False
    assert pilot["credential_material_stored"] is False
