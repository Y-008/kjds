from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine

from apps.control_plane.pm_heartbeat_store import ProjectHeartbeatRow, SqlProjectHeartbeatStore
from apps.control_plane.sql_repository import Base


def test_heartbeat_store_is_append_only_and_recoverable():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ProjectHeartbeatRow.__table__])
    store = SqlProjectHeartbeatStore(engine)
    first = store.record(
        project_id="p1", tenant_id="t1", entity_id="e1", store_ref="s1",
        head="abc", graph_snapshot_sha256="a" * 64, status="hold",
        payload={"reasons": ["proof_not_ready"]}, observed_at=datetime(2026, 9, 6, tzinfo=UTC),
    )
    second = store.record(
        project_id="p1", tenant_id="t1", entity_id="e1", store_ref="s1",
        head="def", graph_snapshot_sha256="b" * 64, status="dispatch",
        payload={"next_actions": ["compute_frontier"]}, observed_at=datetime(2026, 9, 6, 0, 1, tzinfo=UTC),
    )
    assert first["revision"] == 1
    assert second["revision"] == 2
    assert store.latest(project_id="p1", tenant_id="t1", entity_id="e1", store_ref="s1")["head"] == "def"
    assert len(store.history(project_id="p1", tenant_id="t1", entity_id="e1", store_ref="s1")) == 2


def test_heartbeat_store_replays_same_idempotency_key_and_rejects_payload_drift():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ProjectHeartbeatRow.__table__])
    store = SqlProjectHeartbeatStore(engine)
    args = dict(
        project_id="p-idem",
        tenant_id="t1",
        entity_id="e1",
        store_ref="s1",
        head="abc",
        graph_snapshot_sha256="a" * 64,
        status="hold",
        payload={"reason": "evidence_stale"},
        observed_at=datetime(2026, 9, 6, tzinfo=UTC),
        idempotency_key="pm-heartbeat-1",
    )
    first = store.record(**args)
    replay = store.record(**args)
    assert first["heartbeat_id"] == replay["heartbeat_id"]
    assert replay["idempotent"] is True
    assert len(store.history(project_id="p-idem", tenant_id="t1", entity_id="e1", store_ref="s1")) == 1

    with pytest.raises(ValueError, match="idempotency key conflicts"):
        store.record(**{**args, "payload": {"reason": "different"}})


def test_heartbeat_expected_revision_is_compare_and_swap():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ProjectHeartbeatRow.__table__])
    store = SqlProjectHeartbeatStore(engine)
    common = dict(
        project_id="p-cas",
        tenant_id="t1",
        entity_id="e1",
        store_ref="s1",
        graph_snapshot_sha256="b" * 64,
        status="hold",
        payload={},
    )
    first = store.record(**common, head="a", expected_revision=0, idempotency_key="cas-1")
    assert first["revision"] == 1
    second = store.record(**common, head="b", expected_revision=1, idempotency_key="cas-2")
    assert second["revision"] == 2
    with pytest.raises(ValueError, match="revision is stale"):
        store.record(**common, head="c", expected_revision=1, idempotency_key="cas-3")


def test_heartbeat_liveness_columns_are_projected_for_watchdogs():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ProjectHeartbeatRow.__table__])
    store = SqlProjectHeartbeatStore(engine)
    heartbeat = store.record(
        project_id="p-live",
        tenant_id="t1",
        entity_id="e1",
        store_ref="s1",
        head="a",
        graph_snapshot_sha256="c" * 64,
        status="isolate",
        payload={"recovery": "reclaim"},
        idempotency_key="live-1",
        liveness_deadline=datetime(2026, 9, 6, 13, tzinfo=UTC),
        heartbeat_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        progress_cursor="page:2",
        expected_next_event="page:3",
        stuck_detector_version="kjds-stuck-detector-v2",
        compensation_action="reclaim_lease_and_recover",
        recovery_ref="incident-1",
    )
    assert heartbeat["liveness_deadline"].endswith("+00:00")
    assert heartbeat["progress_cursor"] == "page:2"
    assert heartbeat["compensation_action"] == "reclaim_lease_and_recover"


def test_list_latest_is_scope_bound_and_selects_one_revision_per_project_store():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ProjectHeartbeatRow.__table__])
    store = SqlProjectHeartbeatStore(engine)
    common = dict(
        tenant_id="tenant-a",
        entity_id="entity-a",
        store_ref="store-a",
        head="h",
        graph_snapshot_sha256="d" * 64,
        status="hold",
        payload={},
    )
    store.record(project_id="p1", **common, idempotency_key="p1-1")
    store.record(project_id="p1", **{**common, "head": "h2"}, idempotency_key="p1-2")
    store.record(project_id="p2", **common, idempotency_key="p2-1")
    store.record(
        project_id="p-other",
        **{**common, "tenant_id": "tenant-b"},
        idempotency_key="other-1",
    )

    rows = store.list_latest(
        tenant_id="tenant-a",
        entity_id="entity-a",
        store_refs=("store-a",),
    )
    assert [(row["project_id"], row["revision"]) for row in rows] == [
        ("p1", 2),
        ("p2", 1),
    ]
    assert store.list_latest(tenant_id="tenant-a", store_refs=()) == ()


def test_list_latest_can_replay_only_observations_known_by_cutoff():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ProjectHeartbeatRow.__table__])
    store = SqlProjectHeartbeatStore(engine)
    common = dict(
        tenant_id="tenant-a", entity_id="entity-a", store_ref="store-a",
        project_id="p1", head="h", graph_snapshot_sha256="d" * 64,
        status="hold", payload={}, idempotency_key="k1",
    )
    store.record(**common, observed_at=datetime(2026, 9, 5, tzinfo=UTC))
    store.record(**{**common, "idempotency_key": "k2", "head": "future"}, observed_at=datetime(2026, 9, 7, tzinfo=UTC))
    rows = store.list_latest(
        tenant_id="tenant-a", entity_id="entity-a", store_refs=("store-a",),
        observed_until=datetime(2026, 9, 6, tzinfo=UTC),
    )
    assert rows[0]["head"] == "h"
