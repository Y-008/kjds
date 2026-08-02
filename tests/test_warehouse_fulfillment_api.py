from __future__ import annotations

from fastapi.testclient import TestClient

from apps.control_plane.api import app
from apps.control_plane.runtime import runtime
from apps.control_plane.security import AuthenticationFailure, Principal


def test_warehouse_openapi_is_protected_and_closed():
    schema = app.openapi()
    workspace = schema["paths"][
        "/v1/warehouse-fulfillment/workspace"
    ]
    events = schema["paths"]["/v1/warehouse-fulfillment/events"]
    assert set(workspace) == {"get"}
    assert set(events) == {"post"}
    assert workspace["get"]["security"] == [{"KjdsApiKey": []}]
    assert events["post"]["security"] == [{"KjdsApiKey": []}]
    event_schema = schema["components"]["schemas"][
        "WarehouseExecutionEventInput"
    ]
    assert event_schema["additionalProperties"] is False
    assert "warehouse_ref" in event_schema["required"]
    assert "event_type" in event_schema["required"]
    assert "evidence_id" in event_schema["required"]


def test_warehouse_workspace_requires_authentication(monkeypatch):
    def reject(_key):
        raise AuthenticationFailure("API key required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    response = TestClient(app).get(
        "/v1/warehouse-fulfillment/workspace"
        "?warehouse_ref=warehouse-cn-1"
    )
    assert response.status_code == 401


def test_warehouse_workspace_exact_scope_no_data_and_cross_store_403(
    monkeypatch,
):
    principal = Principal(
        actor_id="warehouse-operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-cn-1",
        store_refs=frozenset({"store-cn-1"}),
    )
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal,
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: {
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
    )
    client = TestClient(app)
    headers = {"X-KJDS-API-Key": "test-key"}
    response = client.get(
        "/v1/warehouse-fulfillment/workspace"
        "?store_ref=store-cn-1&warehouse_ref=warehouse-cn-1"
        "&as_of=2026-07-29T01%3A00%3A00Z",
        headers=headers,
    )
    forbidden = client.get(
        "/v1/warehouse-fulfillment/workspace"
        "?store_ref=other-store&warehouse_ref=warehouse-cn-1",
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_data"
    assert payload["scope"]["entity_ref"] is None
    assert payload["scope"]["warehouse_ref"] == "warehouse-cn-1"
    assert payload["counts"]["total"] == 0
    assert payload["fulfillment_items"] == []
    assert payload["control_envelope"]["upstream_reads"] == []
    assert payload["control_envelope"]["external_write_allowed"] is False
    assert (
        payload["control_envelope"]["private_erp_interface_allowed"]
        is False
    )
    assert forbidden.status_code == 403
