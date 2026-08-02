from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from apps.control_plane.api import app
from apps.control_plane.runtime import runtime
from apps.control_plane.security import Principal

STORE = "store-native-parity"


def _principal(*, stores: frozenset[str] = frozenset({STORE})) -> Principal:
    return Principal(
        actor_id="native-parity-reviewer",
        roles=frozenset({"reviewer"}),
        tenant_ref="tenant-native-parity",
        store_refs=stores,
    )


class ScopeProbe:
    def current(self, **_values):
        return {
            "status": "ready",
            "tenant_ref": "tenant-native-parity",
            "entity_ref": "entity-native-parity",
            "store_ref": STORE,
            "authority_sha256": "a" * 64,
        }


def test_native_parity_api_is_authenticated_exact_scope_and_get_only(monkeypatch):
    schema = app.openapi()
    assert set(schema["paths"]["/v1/native-parity-acceptance/workspace"]) == {"get"}

    client = TestClient(app)
    assert client.get("/v1/native-parity-acceptance/workspace").status_code == 401

    principal = _principal()
    monkeypatch.setattr(runtime.authenticator, "authenticate", lambda _key: principal)
    monkeypatch.setattr(runtime, "scope_grants", ScopeProbe())
    response = client.get(
        "/v1/native-parity-acceptance/workspace",
        params={
            "store_ref": STORE,
            "as_of": "2026-08-01T12:00:00Z",
            "provider_id": "dianxiaomi_erp",
        },
        headers={"X-KJDS-API-Key": "test"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["counts"]["states"]["verified_native"] == 0
    assert payload["counts"]["states"]["gated"] == payload["counts"]["items"]
    assert payload["items"]
    assert all(item["state"] == "gated" for item in payload["items"])
    assert payload["control_envelope"]["external_write_allowed"] is False


def test_native_parity_api_forbids_store_overreach(monkeypatch):
    principal = _principal(stores=frozenset({"other-store"}))
    monkeypatch.setattr(runtime.authenticator, "authenticate", lambda _key: principal)
    response = TestClient(app).get(
        "/v1/native-parity-acceptance/workspace",
        params={"store_ref": STORE},
        headers={"X-KJDS-API-Key": "test"},
    )
    assert response.status_code == 403


def test_native_parity_api_no_entity_is_explicit_no_data(monkeypatch):
    principal = _principal()
    monkeypatch.setattr(runtime.authenticator, "authenticate", lambda _key: principal)
    scope = ScopeProbe()
    value = scope.current()
    value.update(
        status="no_data",
        entity_ref=None,
        authority_sha256=None,
    )
    monkeypatch.setattr(scope, "current", lambda **_values: deepcopy(value))
    monkeypatch.setattr(runtime, "scope_grants", scope)

    response = TestClient(app).get(
        "/v1/native-parity-acceptance/workspace",
        params={"store_ref": STORE, "as_of": "2026-08-01T12:00:00Z"},
        headers={"X-KJDS-API-Key": "test"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "no_data"
    assert response.json()["counts"]["items"] == 0
