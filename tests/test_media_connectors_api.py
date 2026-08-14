from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.api import app
from apps.control_plane.media_connectors import (
    CONTRACT_ID,
    MediaConnectorEventRow,
    MediaConnectorRegistry,
    MediaConnectorRow,
)
from apps.control_plane.runtime import runtime
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

NOW = datetime(2026, 8, 3, 8, tzinfo=UTC)
REGISTER_BODY = {
    "provider": "codex_oauth",
    "deployment_mode": "customer_local",
    "protocol_version": "codex-app-server/1",
    "capabilities": ["image_generation", "image_editing"],
    "concurrency_limit": 1,
}


def principal(tenant: str, *roles: str) -> Principal:
    return Principal(
        actor_id=f"actor-{tenant}",
        roles=frozenset(roles or ("admin",)),
        tenant_ref=tenant,
    )


@pytest.fixture
def api_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[MediaConnectorRow.__table__, MediaConnectorEventRow.__table__],
    )
    registry = MediaConnectorRegistry(engine=engine, clock=lambda: NOW)
    active = {"principal": principal("tenant-a")}
    monkeypatch.setattr(runtime, "media_connectors", registry)
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: active["principal"],
    )
    monkeypatch.setattr(runtime.kill_switch, "ensure_writes_allowed", lambda: None)
    return TestClient(app), registry, active


def post_registration(client: TestClient, key: str = "registration-a"):
    return client.post(
        "/v1/media-connectors",
        headers={"X-KJDS-API-Key": "test", "Idempotency-Key": key},
        json=REGISTER_BODY,
    )


def test_media_connector_openapi_is_frozen_and_tenant_implicit():
    schema = app.openapi()
    snapshot = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "project"
            / "contracts"
            / "openapi-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert schema == snapshot
    expected = {
        "/v1/media-connectors": {"get", "post"},
        "/v1/media-connectors/{connector_ref}": {"get"},
        "/v1/media-connectors/{connector_ref}/observations": {"post"},
        "/v1/media-connectors/{connector_ref}/revoke": {"post"},
    }
    for path, methods in expected.items():
        assert set(schema["paths"][path]) == methods
        for method in methods:
            operation = schema["paths"][path][method]
            assert operation["security"] == [{"KjdsApiKey": []}]
            parameters = operation.get("parameters", [])
            assert all(item["name"] != "tenant_ref" for item in parameters)
    register_parameters = schema["paths"]["/v1/media-connectors"]["post"][
        "parameters"
    ]
    assert any(
        item["name"] == "Idempotency-Key"
        and item["in"] == "header"
        and item["required"]
        for item in register_parameters
    )


def test_api_register_observe_list_and_revoke(api_client):
    client, _registry, _active = api_client
    response = post_registration(client)
    assert response.status_code == 201
    assert response.json()["contract_id"] == CONTRACT_ID
    descriptor = response.json()["connector"]
    connector_ref = descriptor["connector_ref"]
    assert descriptor["derived_tenant_ref"] == "tenant-a"

    observed_at = (NOW + timedelta(seconds=1)).isoformat()
    response = client.post(
        f"/v1/media-connectors/{connector_ref}/observations",
        headers={"X-KJDS-API-Key": "test", "Idempotency-Key": "ready-a"},
        json={"health": "READY", "observed_at": observed_at},
    )
    assert response.status_code == 200
    assert response.json()["connector"]["health"] == "READY"

    response = client.get(
        "/v1/media-connectors?provider=codex_oauth&health=READY",
        headers={"X-KJDS-API-Key": "test"},
    )
    assert response.status_code == 200
    assert [item["connector_ref"] for item in response.json()["items"]] == [
        connector_ref
    ]

    response = client.post(
        f"/v1/media-connectors/{connector_ref}/revoke",
        headers={"X-KJDS-API-Key": "test", "Idempotency-Key": "revoke-a"},
        json={"observed_at": (NOW + timedelta(seconds=2)).isoformat()},
    )
    assert response.status_code == 200
    assert response.json()["connector"]["health"] == "REVOKED"


def test_api_cross_tenant_reads_and_writes_are_404(api_client):
    client, _registry, active = api_client
    connector_ref = post_registration(client).json()["connector"]["connector_ref"]
    active["principal"] = principal("tenant-b", "monitor")

    response = client.get(
        f"/v1/media-connectors/{connector_ref}",
        headers={"X-KJDS-API-Key": "test"},
    )
    assert response.status_code == 404
    response = client.post(
        f"/v1/media-connectors/{connector_ref}/observations",
        headers={"X-KJDS-API-Key": "test", "Idempotency-Key": "cross-a"},
        json={
            "health": "READY",
            "observed_at": (NOW + timedelta(seconds=1)).isoformat(),
        },
    )
    assert response.status_code == 404


def test_api_idempotency_replay_and_drift_is_409(api_client):
    client, _registry, _active = api_client
    first = post_registration(client)
    replay = post_registration(client)
    assert replay.status_code == 201
    assert replay.json() == first.json()
    response = client.post(
        "/v1/media-connectors",
        headers={"X-KJDS-API-Key": "test", "Idempotency-Key": "registration-a"},
        json={**REGISTER_BODY, "capabilities": ["image_generation"]},
    )
    assert response.status_code == 409


def test_api_rejects_tenant_or_secret_material_and_wrong_roles(api_client):
    client, _registry, active = api_client
    response = client.post(
        "/v1/media-connectors",
        headers={"X-KJDS-API-Key": "test", "Idempotency-Key": "registration-a"},
        json={**REGISTER_BODY, "tenant_ref": "tenant-b", "cookie": "hidden"},
    )
    assert response.status_code == 422
    response = client.post(
        "/v1/media-connectors",
        headers={
            "X-KJDS-API-Key": "test",
            "Idempotency-Key": "sk-secret-value",
        },
        json=REGISTER_BODY,
    )
    assert response.status_code == 422

    active["principal"] = principal("tenant-a", "operator")
    response = post_registration(client, "operator-register")
    assert response.status_code == 403
