from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.operating_intelligence import (
    AnomalyScanRunRow,
    OperatingIntelligenceService,
)
from apps.control_plane.operations_queue import (
    OperationsEscalationEventRow,
    OperationsQueueService,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base


class ProfitLedger:
    def snapshot(self, **_values):
        return {
            "coverage_ratio": "0.5",
            "rows": [
                {
                    "gross_revenue": "100",
                    "actual_profit": "-5",
                    "accrual_contribution": "-5",
                    "settlement_contribution": "80",
                    "cash_contribution": "70",
                    "evidence_ids": ["evd-ledger"],
                    "erosion": {
                        "returns": "5",
                        "warehousing": "10",
                        "advertising": "20",
                    },
                }
            ],
        }


class Evidence:
    def require_valid(self, _evidence_ids):
        return None


class BlockedScopedEvidence:
    def project(self, **_values):
        return {
            "status": "blocked",
            "source_gaps": ["evidence_scope_conflict"],
        }


class MustNotReadLegacy:
    def list(self):
        raise AssertionError("scoped queue must not read legacy incidents")


class EmptyAuthority:
    def list(self):
        return []

    def list_windows(self):
        return []


class ScopedGovernance:
    def project(self, **_values):
        return {
            "status": "no_data",
            "commands": [],
            "windows": [],
            "source_gaps": [],
        }


def database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def intelligence(engine):
    return OperatingIntelligenceService(
        engine=engine,
        profit_ledger=ProfitLedger(),
        evidence=Evidence(),
    )


def scope(
    *,
    actor_id: str,
    tenant_ref: str,
    entity_ref: str,
    store_ref: str,
    authority_character: str,
):
    return {
        "principal": Principal(
            actor_id=actor_id,
            roles=frozenset({"monitor", "operator"}),
            tenant_ref=tenant_ref,
            store_refs=frozenset({store_ref}),
        ),
        "entity_scope": {
            "status": "ready",
            "entity_ref": entity_ref,
            "authority_sha256": authority_character * 64,
        },
        "store_ref": store_ref,
    }


def test_scans_tasks_events_and_queue_are_exact_scope_isolated():
    engine = database()
    service = intelligence(engine)
    first_scope = scope(
        actor_id="operator-a",
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        authority_character="a",
    )
    second_scope = scope(
        actor_id="operator-b",
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        authority_character="b",
    )
    first = service.scan(
        actor_id="operator-a",
        as_of="2026-07-28T01:00:00+00:00",
        **first_scope,
    )
    second = service.scan(
        actor_id="operator-b",
        as_of="2026-07-28T01:01:00+00:00",
        **second_scope,
    )
    first_task_id = next(
        item["task_id"]
        for item in first["results"]
        if item["status"] == "task_created"
    )

    service.ensure_internal_task(
        task_kind="legacy-unscoped",
        scope={"store_ref": "store-a"},
        title="Legacy task",
        severity="low",
        owner="operations",
        evidence_ids=[],
        snapshot={},
        actor_id="legacy",
        as_of="2026-07-28T00:00:00+00:00",
    )

    first_tasks = service.tasks(
        as_of="2026-07-28T02:00:00+00:00",
        **first_scope,
    )
    second_tasks = service.tasks(
        as_of="2026-07-28T02:00:00+00:00",
        **second_scope,
    )
    assert {task["id"] for task in first_tasks}.isdisjoint(
        task["id"] for task in second_tasks
    )
    assert all(
        task["scope"]["tenant_ref"] == "tenant-a"
        for task in first_tasks
    )
    assert all(
        task["scope"]["tenant_ref"] == "tenant-b"
        for task in second_tasks
    )
    assert len(service.scans(**first_scope)) == 1
    assert len(service.scans(**second_scope)) == 1
    assert all(
        item["item_id"] != "legacy-unscoped"
        for item in service.queue_items(
            now=datetime(2026, 7, 28, 2, tzinfo=UTC),
            **first_scope,
        )
    )
    with pytest.raises(KeyError, match="Unknown operating task"):
        service.task_events(first_task_id, **second_scope)
    with pytest.raises(KeyError, match="Unknown operating task"):
        service.append_task_event(
            first_task_id,
            event_type="acknowledge",
            reason="Cross-scope attempt",
            evidence_ids=[],
            actor_id="operator-b",
            **second_scope,
        )

    assert first["scope"]["scope_authority_sha256"] == "a" * 64
    assert second["scope"]["scope_authority_sha256"] == "b" * 64


def test_scoped_queue_excludes_legacy_sources_and_freezes_escalations():
    engine = database()
    tasks = intelligence(engine)
    active_scope = scope(
        actor_id="operator-a",
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        authority_character="a",
    )
    other_scope = scope(
        actor_id="operator-b",
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        authority_character="b",
    )
    tasks.scan(
        actor_id="operator-a",
        as_of="2026-07-28T01:00:00+00:00",
        **active_scope,
    )
    queue = OperationsQueueService(
        engine=engine,
        incidents=MustNotReadLegacy(),
        limited_executor=EmptyAuthority(),
        post_execution=EmptyAuthority(),
        operating_tasks=tasks,
        governance_scope=ScopedGovernance(),
    )

    projection = queue.projection(
        as_of="2026-07-28T03:00:00+00:00",
        **active_scope,
    )
    scanned = queue.scan(
        as_of="2026-07-28T03:00:00+00:00",
        actor_id="monitor-a",
        **active_scope,
    )

    assert projection["status"] == "ready"
    assert projection["items"]
    assert projection["excluded_sources"] == [
        "legacy_unscoped_incidents"
    ]
    assert scanned["persisted"] is True
    assert queue.escalations(**active_scope)
    assert queue.escalations(**other_scope) == []
    assert all(
        item["scope"]["entity_ref"] == "entity-a"
        for item in queue.escalations(**active_scope)
    )


def test_missing_entity_scope_creates_no_scan_task_or_escalation():
    engine = database()
    tasks = intelligence(engine)
    principal = Principal(
        actor_id="monitor-a",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    entity_scope = {
        "status": "no_data",
        "entity_ref": None,
        "authority_sha256": None,
    }
    queue = OperationsQueueService(
        engine=engine,
        incidents=MustNotReadLegacy(),
        limited_executor=EmptyAuthority(),
        post_execution=EmptyAuthority(),
        operating_tasks=tasks,
        governance_scope=ScopedGovernance(),
    )

    scan = tasks.scan(
        store_ref="store-a",
        actor_id="monitor-a",
        as_of="2026-07-28T01:00:00+00:00",
        principal=principal,
        entity_scope=entity_scope,
    )
    escalation = queue.scan(
        store_ref="store-a",
        as_of="2026-07-28T03:00:00+00:00",
        actor_id="monitor-a",
        principal=principal,
        entity_scope=entity_scope,
    )

    assert scan["persisted"] is False
    assert escalation["persisted"] is False
    assert tasks.scans() == []
    assert tasks.tasks() == []
    assert queue.escalations() == []


def test_database_rejects_partial_native_scope_tuples():
    engine = database()
    with Session(engine) as session:
        session.add(
            AnomalyScanRunRow(
                id="asn-invalid",
                registry_version="test",
                tenant_ref="tenant-a",
                entity_ref=None,
                store_ref="store-a",
                scope_authority_sha256=None,
                as_of=datetime(2026, 7, 28, tzinfo=UTC),
                results_json=[],
                snapshot_sha256="a" * 64,
                created_by="test",
                created_at=datetime(2026, 7, 28, tzinfo=UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(
            OperationsEscalationEventRow(
                id="ose-invalid",
                queue_key="task:invalid",
                item_type="operating_task",
                item_id="invalid",
                level=1,
                tenant_ref="tenant-a",
                entity_ref=None,
                store_ref=None,
                scope_authority_sha256=None,
                due_at=datetime(2026, 7, 28, tzinfo=UTC),
                escalated_by="test",
                created_at=datetime(2026, 7, 28, tzinfo=UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_scoped_task_resolution_rejects_unbound_evidence():
    engine = database()
    service = OperatingIntelligenceService(
        engine=engine,
        profit_ledger=ProfitLedger(),
        evidence=Evidence(),
        scoped_evidence=BlockedScopedEvidence(),
    )
    active_scope = scope(
        actor_id="operator-a",
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_ref="store-a",
        authority_character="a",
    )
    scan = service.scan(
        actor_id="operator-a",
        as_of="2026-07-28T01:00:00+00:00",
        **active_scope,
    )
    task_id = next(
        item["task_id"]
        for item in scan["results"]
        if item["status"] == "task_created"
    )
    service.append_task_event(
        task_id,
        event_type="acknowledge",
        reason="Accepted",
        evidence_ids=[],
        actor_id="operator-a",
        **active_scope,
    )
    service.append_task_event(
        task_id,
        event_type="start",
        reason="Started",
        evidence_ids=[],
        actor_id="operator-a",
        **active_scope,
    )

    with pytest.raises(ValueError, match="exact tenant/entity/store"):
        service.append_task_event(
            task_id,
            event_type="resolve",
            reason="Unbound evidence",
            evidence_ids=["evd-unbound"],
            actor_id="operator-a",
            **active_scope,
        )
    task = next(
        item
        for item in service.tasks(**active_scope)
        if item["id"] == task_id
    )
    assert task["status"] == "in_progress"
