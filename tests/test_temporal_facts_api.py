from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.control_plane.api import registered_routes
from apps.control_plane.routers import temporal_facts
from apps.control_plane.routers.temporal_facts import RestateFactInput, _timestamp
from apps.control_plane.runtime import runtime
from apps.control_plane.security import Principal
from apps.control_plane.temporal_fact_store import ScopeRef, TemporalFactStore

T0 = datetime(2026, 9, 1, 8, tzinfo=UTC)


def _principal() -> Principal:
    return Principal(
        actor_id="analyst",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"store-a"}),
    )


def _fact_store() -> TemporalFactStore:
    store = TemporalFactStore(clock=lambda: T0 + timedelta(days=1))
    store.append(
        fact_id="fact-order-1",
        fact_type="order",
        natural_key="order-1",
        scope=ScopeRef(
            tenant_id="tenant-a",
            entity_id="entity-a",
            store_ids=("store-a",),
            warehouse_ids=("warehouse-a",),
            sku_ids=("sku-1",),
        ),
        sku="sku-1",
        payload={"order_id": "order-1", "amount": 0, "currency": "RUB"},
        event_time=T0,
        observed_time=T0 + timedelta(hours=1),
        effective_time=T0,
        source_system="ozon-export",
        source_record_id="ozon-order-1",
        idempotency_key="import-order-1",
        lineage=[
            {
                "kind": "evidence",
                "id": "evidence-order-1",
                "sha256": "a" * 64,
                "relationship": "captured_from",
            },
            {
                "kind": "platform_response",
                "id": "response-order-1",
                "sha256": "b" * 64,
                "relationship": "returned_by",
            },
        ],
    )
    return store


def _bind_scope(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_: {"status": "ready", "entity_ref": "entity-a"},
    )


def test_as_of_rejects_future_timestamp():
    with pytest.raises(HTTPException, match="future"):
        _timestamp("2999-01-01T00:00:00Z")


def test_temporal_fact_routes_are_registered():
    paths = {route.path for route in registered_routes()}
    assert "/v1/facts/as-of" in paths
    assert "/v1/facts/{fact_id}/versions" in paths
    assert "/v1/facts/{fact_id}/restate" in paths
    assert "/v1/facts/{fact_id}/lineage" in paths


def test_restatement_requires_idempotency_key():
    with pytest.raises(ValidationError):
        RestateFactInput(
            entity_ref="entity-a",
            payload={"value": 1},
            correction_reason="late settlement",
        )


def test_facts_as_of_exposes_scope_lineage_drilldown_and_stable_replay(monkeypatch):
    principal = _principal()
    store = _fact_store()
    _bind_scope(monkeypatch)
    monkeypatch.setattr(runtime, "temporal_fact_store", store)

    kwargs = {
        "principal": principal,
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "as_of": (T0 + timedelta(hours=2)).isoformat(),
    }
    first = temporal_facts.facts_as_of(**kwargs)
    replay = temporal_facts.facts_as_of(**kwargs)

    assert first["contract_id"] == "kjds-temporal-facts-as-of-v1"
    assert first["status"] == "ready"
    assert first["quality_state"] == "VALID"
    assert first["scope"] == {
        "tenant_id": "tenant-a",
        "entity_id": "entity-a",
        "store_ids": ["store-a"],
        "warehouse_ids": [],
    }
    assert first["facts"][0]["payload"]["amount"] == 0
    assert first["lineage"][0]["id"] == "evidence-order-1"
    revision_id = first["facts"][0]["revision_id"]
    assert {edge["to_id"] for edge in first["lineage_edges"]} == {revision_id}
    assert [node["level"] for node in first["drilldown"][0]["nodes"]] == [
        "entity",
        "store",
        "warehouse",
        "sku",
        "transaction",
        "evidence",
    ]
    assert first["lineage_audit"]["lineage_complete"] is False
    assert first["replay"]["mode"] == "historical_replay"
    assert first["replay"]["result_sha256"] == replay["replay"]["result_sha256"]
    assert first["external_write_allowed"] is False


def test_fact_versions_allows_optional_warehouse_and_sku_dimensions(monkeypatch):
    principal = _principal()
    _bind_scope(monkeypatch)
    monkeypatch.setattr(runtime, "temporal_fact_store", _fact_store())

    result = temporal_facts.fact_versions(
        "fact-order-1",
        principal=principal,
        entity_ref="entity-a",
        store_ref="store-a",
        as_of=(T0 + timedelta(hours=2)).isoformat(),
    )

    assert result["version_count"] == 1
    assert result["versions"][0]["scope"]["warehouse_ids"] == ["warehouse-a"]
    assert result["lineage_chain"]["nodes"]
    assert result["replay"]["history_sha256"]
    assert result["external_write_allowed"] is False


def test_fact_lineage_can_replay_a_historical_revision(monkeypatch):
    principal = _principal()
    store = _fact_store()
    corrected = store.restate(
        "fact-order-1",
        {"order_id": "order-1", "amount": 9, "currency": "RUB"},
        correction_reason="late settlement",
        observed_time=T0 + timedelta(hours=3),
        idempotency_key="correction-order-1",
    )
    _bind_scope(monkeypatch)
    monkeypatch.setattr(runtime, "temporal_fact_store", store)

    result = temporal_facts.fact_lineage(
        "fact-order-1",
        principal=principal,
        entity_ref="entity-a",
        store_ref="store-a",
        as_of=(T0 + timedelta(hours=2)).isoformat(),
    )

    assert corrected.revision == 2
    assert result["revision"] == 1
    assert result["fact"]["payload"]["amount"] == 0
    assert result["replay"]["mode"] == "historical_replay"
    assert result["drilldown_path"]["nodes"][-1]["level"] == "evidence"

    with pytest.raises(HTTPException, match="revision and as_of"):
        temporal_facts.fact_lineage(
            "fact-order-1",
            principal=principal,
            entity_ref="entity-a",
            store_ref="store-a",
            revision=1,
            as_of=(T0 + timedelta(hours=2)).isoformat(),
        )


def test_temporal_source_outage_is_explicitly_blocked(monkeypatch):
    principal = _principal()
    _bind_scope(monkeypatch)

    class BrokenStore:
        def query_as_of(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(runtime, "temporal_fact_store", BrokenStore())
    result = temporal_facts.facts_as_of(
        principal=principal,
        entity_ref="entity-a",
        store_ref="store-a",
        as_of=(T0 + timedelta(hours=2)).isoformat(),
    )

    assert result["status"] == "blocked"
    assert result["quality_state"] == "BLOCKED"
    assert result["facts"] == []
    assert result["reason"] == "temporal_fact_source_unavailable"
    assert result["data_envelope"]["status"] == "blocked"
    assert result["external_write_allowed"] is False


def test_scope_authority_outage_fails_closed(monkeypatch):
    principal = _principal()

    def broken_authority(**_kwargs):
        raise RuntimeError("scope database unavailable")

    monkeypatch.setattr(runtime.scope_grants, "current", broken_authority)
    with pytest.raises(HTTPException) as caught:
        temporal_facts.facts_as_of(
            principal=principal,
            entity_ref="entity-a",
            store_ref="store-a",
            as_of=(T0 + timedelta(hours=2)).isoformat(),
        )
    assert caught.value.status_code == 503


def test_versions_deny_foreign_scope_before_lineage_read(monkeypatch):
    principal = _principal()
    foreign = _fact_store()
    foreign_fact = foreign.get("fact-order-1").model_copy(
        update={
            "scope": ScopeRef(
                tenant_id="tenant-b",
                entity_id="entity-b",
                store_ids=("store-a",),
                warehouse_ids=("warehouse-a",),
                sku_ids=("sku-1",),
            ),
            "permission_scope": "tenant-b:entity-b:store-a:warehouse-a:sku-1",
        },
        deep=True,
    )
    isolated = TemporalFactStore()
    isolated.append(foreign_fact)
    _bind_scope(monkeypatch)
    monkeypatch.setattr(runtime, "temporal_fact_store", isolated)

    with pytest.raises(HTTPException) as caught:
        temporal_facts.fact_versions(
            "fact-order-1",
            principal=principal,
            entity_ref="entity-a",
            store_ref="store-a",
        )
    assert caught.value.status_code == 403
