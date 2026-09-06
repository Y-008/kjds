from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from apps.control_plane.api import registered_routes
from apps.control_plane.data_fabric_contracts import DataProductDescriptor
from apps.control_plane.routers import control_plane_observability
from apps.control_plane.security import Principal
from apps.control_plane.temporal_fact_store import (
    QualityState,
    TemporalFactQueryResult,
    TemporalFactStore,
)


def _verified_order_product() -> DataProductDescriptor:
    return DataProductDescriptor(
        dataset_id="orders.canonical.v1",
        version="1",
        owner="oms",
        grain="order_line",
        quality_threshold=0.0,
        rebuild_method="test replay",
        status="verified",
        authority="canonical_fact",
    )


def test_observability_routes_are_registered():
    paths = {route.path for route in registered_routes()}
    assert "/v1/analytics/{recipe}/drilldown" in paths
    assert "/v1/analytics/{recipe}/lineage" in paths
    assert "/v1/operations/stuck" in paths
    assert "/v1/economics/guard-status" in paths


def test_analytics_time_rejects_future_as_of():
    with pytest.raises(HTTPException, match="future"):
        control_plane_observability._time("2999-01-01T00:00:00Z", "as_of")


def test_analytics_rejects_entity_without_current_scope_grant(monkeypatch):
    principal = Principal(
        actor_id="analyst", roles=frozenset({"monitor"}), tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(
        control_plane_observability.runtime.scope_grants,
        "current",
        lambda **_: {"status": "ready", "entity_ref": "other-entity"},
    )
    with pytest.raises(HTTPException, match="authorized scope"):
        control_plane_observability._recipe(
            "orders", principal, entity_id="entity-a", store_id="store-a",
            metric=("net_sales",), dimension=("store",), start_at=None,
            end_at=None, as_of=None,
        )


def test_heartbeat_without_consumer_is_not_attributed_to_project_manager():
    observation = control_plane_observability._heartbeat_observation({
        "project_id": "project-a",
        "status": "dispatch",
        "observed_at": "2026-09-06T00:00:00+00:00",
        "payload": {},
    })
    assert observation.consumer_id is None


def test_operations_stuck_reads_latest_heartbeats_and_fails_closed(monkeypatch):
    principal = Principal(
        actor_id="watchdog",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    calls = {}

    class _HeartbeatSource:
        def list_latest(self, **kwargs):
            calls.update(kwargs)
            return (
                {
                    "project_id": "project-a",
                    "heartbeat_id": "hb-1",
                    "status": "dispatch",
                    "observed_at": "2026-09-06T00:00:00+00:00",
                    "heartbeat_at": "2026-09-06T00:00:00+00:00",
                    "liveness_deadline": None,
                    "progress_cursor": None,
                    "expected_next_event": None,
                    "idempotency_key": "hb-1",
                    "compensation_action": None,
                    "recovery_ref": None,
                    "payload": {},
                },
            )

    monkeypatch.setattr(
        control_plane_observability.runtime,
        "project_heartbeat_store",
        _HeartbeatSource(),
    )
    result = control_plane_observability.operations_stuck(
        principal=principal,
        heartbeat_timeout_seconds=300,
        store_ref="store-a",
        as_of="2026-09-06T01:00:00+00:00",
    )

    assert calls == {
        "tenant_id": "tenant-a",
        "entity_id": None,
        "store_refs": ("store-a",),
        "observed_until": datetime(2026, 9, 6, 1, tzinfo=UTC),
    }
    assert result["status"] == "BLOCKED"
    assert result["quality_state"] == "BLOCKED"
    assert result["stuck_count"] == 1
    assert "heartbeat_expired" in result["tasks"][0]["reasons"]
    assert result["recovery_contract"] == "kjds-stuck-recovery-v1"
    assert result["recovery_mode"] == "proposal_only"
    assert result["tasks"][0]["recovery_plan"]["retry_allowed"] is False
    assert result["tasks"][0]["recovery_plan"]["external_write_allowed"] is False
    assert result["external_write_allowed"] is False


def test_analytics_projections_preserve_fact_quality_and_lineage(monkeypatch):
    from datetime import UTC, datetime, timedelta

    principal = Principal(
        actor_id="analyst",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    facts = TemporalFactStore(clock=lambda: t0 + timedelta(hours=4))
    facts.append(
        fact_id="order-fact-1",
        fact_type="order",
        natural_key="order-1",
        payload={"gross_sales": 12, "sku": "sku-1"},
        tenant_id="tenant-a",
        entity_id="entity-a",
        store_id="store-a",
        event_time=t0,
        observed_time=t0 + timedelta(hours=1),
        effective_time=t0,
        source_system="ozon-export",
        source_record_id="ozon-order-1",
        idempotency_key="import-1",
        lineage=[
            {
                "kind": "evidence",
                "id": "ozon-response-1",
                "sha256": "a" * 64,
                "relationship": "captured_from",
            }
        ],
    )
    monkeypatch.setattr(
        control_plane_observability.runtime,
        "temporal_fact_store",
        facts,
    )
    monkeypatch.setattr(
        control_plane_observability.runtime.scope_grants,
        "current",
        lambda **_: {"status": "ready", "entity_ref": "entity-a"},
    )
    monkeypatch.setattr(
        control_plane_observability,
        "load_data_product_registry",
        lambda: (_verified_order_product(),),
    )
    kwargs = {
        "principal": principal,
        "entity_id": "entity-a",
        "store_id": "store-a",
        "metric": ("net_sales",),
        "dimension": ("store", "sku"),
        "start_at": t0.isoformat(),
        "end_at": (t0 + timedelta(days=1)).isoformat(),
        "as_of": (t0 + timedelta(hours=2)).isoformat(),
    }

    drilldown = control_plane_observability.analytics_drilldown(
        "orders",
        **kwargs,
    )
    lineage = control_plane_observability.analytics_lineage(
        "orders",
        **kwargs,
    )

    assert drilldown["status"] == "VALID"
    assert drilldown["quality_state"] == "VALID"
    assert drilldown["transparency"]["source_count"] == 1
    assert drilldown["lineage"][0]["id"] == "ozon-response-1"
    assert drilldown["lineage_edges"][0]["to_id"] == drilldown["rows"][0]["revision_id"]
    assert drilldown["lineage_status"] == "PARTIAL"
    assert drilldown["lineage_audit"]["lineage_structurally_complete"] is False
    assert [node["stage"] for node in drilldown["lineage_chain"]["nodes"]] == [
        "metric",
        "data_product",
        "canonical_fact",
        "raw_file",
    ]
    assert [node["level"] for node in drilldown["drilldown_paths"][0]["nodes"]] == [
        "entity",
        "store",
        "sku",
        "transaction",
        "evidence",
    ]
    assert lineage["status"] == "VALID"
    assert lineage["chain"][0]["facts"][0]["fact_id"] == "order-fact-1"
    assert lineage["chain"][0]["raw_evidence"][0]["id"] == "ozon-response-1"
    assert lineage["lineage_status"] == "PARTIAL"
    assert lineage["lineage_audit"]["lineage_structurally_complete"] is False


def _analytics_adapter_fixture(monkeypatch, adapter, *, t0):
    principal = Principal(
        actor_id="analyst",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    monkeypatch.setattr(control_plane_observability.runtime, "temporal_fact_store", adapter)
    monkeypatch.setattr(
        control_plane_observability.runtime.scope_grants,
        "current",
        lambda **_: {"status": "ready", "entity_ref": "entity-a"},
    )
    monkeypatch.setattr(
        control_plane_observability,
        "load_data_product_registry",
        lambda: (_verified_order_product(),),
    )
    return {
        "principal": principal,
        "entity_id": "entity-a",
        "store_id": "store-a",
        "start_at": t0.isoformat(),
        "end_at": (t0 + timedelta(days=1)).isoformat(),
        "as_of": (t0 + timedelta(hours=2)).isoformat(),
    }


def test_analytics_adapter_foreign_scope_row_is_blocked(monkeypatch):
    from datetime import UTC, datetime, timedelta

    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    source = TemporalFactStore(clock=lambda: t0 + timedelta(hours=4))
    foreign = source.append(
        fact_id="foreign-order",
        fact_type="order",
        natural_key="foreign-order-1",
        payload={"gross_sales": 7},
        tenant_id="tenant-b",
        entity_id="entity-a",
        store_id="store-a",
        event_time=t0,
        observed_time=t0 + timedelta(hours=1),
        effective_time=t0,
        source_system="fixture",
        source_record_id="foreign-order-1",
        idempotency_key="foreign-import-1",
    )

    class _ForeignAdapter:
        def query_as_of(self, cutoff, **_kwargs):
            return TemporalFactQueryResult(
                as_of=cutoff,
                items=(foreign,),
                quality_state=QualityState.VALID,
            )

    kwargs = _analytics_adapter_fixture(monkeypatch, _ForeignAdapter(), t0=t0)
    result = control_plane_observability.analytics_drilldown("orders", **kwargs)

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "temporal_fact_scope_mismatch"
    assert result["rows"] == []
    assert result["fact_quality_state"] == "BLOCKED"
    assert result["lineage_status"] == "PARTIAL"


def test_analytics_adapter_quality_claim_drift_is_blocked(monkeypatch):
    from datetime import UTC, datetime, timedelta

    t0 = datetime(2026, 9, 1, tzinfo=UTC)
    source = TemporalFactStore(clock=lambda: t0 + timedelta(hours=4))
    valid = source.append(
        fact_id="valid-order",
        fact_type="order",
        natural_key="valid-order-1",
        payload={"gross_sales": 7},
        tenant_id="tenant-a",
        entity_id="entity-a",
        store_id="store-a",
        event_time=t0,
        observed_time=t0 + timedelta(hours=1),
        effective_time=t0,
        source_system="fixture",
        source_record_id="valid-order-1",
        idempotency_key="valid-import-1",
    )

    class _DriftAdapter:
        def query_as_of(self, cutoff, **_kwargs):
            return TemporalFactQueryResult(
                as_of=cutoff,
                items=(valid,),
                quality_state=QualityState.NO_DATA,
            )

    kwargs = _analytics_adapter_fixture(monkeypatch, _DriftAdapter(), t0=t0)
    result = control_plane_observability.analytics_lineage("orders", **kwargs)

    assert result["status"] == "BLOCKED"
    assert result["reason"] == "temporal_fact_quality_mismatch"
    assert result["chain"][0]["facts"] == []
    assert result["lineage_status"] == "PARTIAL"


def test_analytics_source_outage_is_blocked_instead_of_no_data(monkeypatch):
    from datetime import UTC, datetime

    principal = Principal(
        actor_id="analyst",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )

    class _BrokenFacts:
        def query_as_of(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(control_plane_observability.runtime, "temporal_fact_store", _BrokenFacts())
    monkeypatch.setattr(
        control_plane_observability.runtime.scope_grants,
        "current",
        lambda **_: {"status": "ready", "entity_ref": "entity-a"},
    )
    monkeypatch.setattr(
        control_plane_observability,
        "load_data_product_registry",
        lambda: (_verified_order_product(),),
    )
    result = control_plane_observability.analytics_drilldown(
        "orders",
        principal=principal,
        entity_id="entity-a",
        store_id="store-a",
        start_at=datetime(2026, 9, 1, tzinfo=UTC).isoformat(),
        end_at=datetime(2026, 9, 2, tzinfo=UTC).isoformat(),
        as_of=datetime(2026, 9, 2, tzinfo=UTC).isoformat(),
    )

    assert result["status"] == "BLOCKED"
    assert result["quality_state"] == "BLOCKED"
    assert result["reason"] == "temporal_fact_source_unavailable"
    assert result["rows"] == []
    assert result["external_write_allowed"] is False


def test_stuck_source_outage_is_blocked_and_counts_observations(monkeypatch):
    from datetime import UTC, datetime

    principal = Principal(
        actor_id="watchdog",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )

    class _BrokenHeartbeats:
        def list_latest(self, **_kwargs):
            raise RuntimeError("heartbeat store unavailable")

    monkeypatch.setattr(
        control_plane_observability.runtime,
        "project_heartbeat_store",
        _BrokenHeartbeats(),
    )
    result = control_plane_observability.operations_stuck(
        principal=principal,
        store_ref="store-a",
        as_of=datetime(2026, 9, 6, tzinfo=UTC).isoformat(),
    )

    assert result["status"] == "BLOCKED"
    assert result["quality_state"] == "BLOCKED"
    assert result["reason"] == "task_liveness_observation_source_unavailable"
    assert result["observed_count"] == 0
    assert result["stuck_count"] == 0


def test_stuck_observed_count_is_source_observation_count(monkeypatch):
    from datetime import UTC, datetime, timedelta

    principal = Principal(
        actor_id="watchdog",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )
    now = datetime(2026, 9, 6, tzinfo=UTC)

    class _HeartbeatSource:
        def list_latest(self, **_kwargs):
            return (
                {
                    "project_id": "healthy",
                    "status": "completed",
                    "heartbeat_at": now.isoformat(),
                    "payload": {},
                },
                {
                    "project_id": "stuck",
                    "status": "dispatch",
                    "heartbeat_at": (now - timedelta(hours=1)).isoformat(),
                    "payload": {},
                },
            )

    monkeypatch.setattr(
        control_plane_observability.runtime,
        "project_heartbeat_store",
        _HeartbeatSource(),
    )
    result = control_plane_observability.operations_stuck(
        principal=principal,
        store_ref="store-a",
        as_of=now.isoformat(),
    )

    assert result["observed_count"] == 2
    assert result["stuck_count"] == 1
    assert result["status"] == "BLOCKED"


def test_economic_guard_projection_keeps_blocked_quality_distinct() -> None:
    principal = Principal(
        actor_id="analyst",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )

    result = control_plane_observability.economics_guard_status(
        principal=principal,
        cash_available=-1,
        min_cash=0,
    )

    assert result["status"] == "BLOCKED"
    assert result["quality_state"] == "BLOCKED"
    assert result["external_write_allowed"] is False


def test_economic_guard_missing_cash_snapshot_has_explicit_read_only_shape() -> None:
    principal = Principal(
        actor_id="analyst",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )

    result = control_plane_observability.economics_guard_status(principal=principal)

    assert result["status"] == "UNKNOWN"
    assert result["quality_state"] == "NO_DATA"
    assert result["snapshot_sha256"] is None
    assert result["reasons"] == ["cash_snapshot_missing"]
    assert result["external_write_allowed"] is False
