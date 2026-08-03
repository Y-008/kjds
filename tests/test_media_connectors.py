from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from apps.control_plane.media_connectors import (
    CONTRACT_ID,
    ZERO_SHA256,
    MediaConnectorConflictError,
    MediaConnectorContract,
    MediaConnectorEventRow,
    MediaConnectorRegistry,
    MediaConnectorRow,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

NOW = datetime(2026, 8, 3, 8, tzinfo=UTC)
DESCRIPTOR_FIELDS = {
    "connector_ref",
    "derived_tenant_ref",
    "provider",
    "deployment_mode",
    "binding_sha256",
    "protocol_version",
    "capabilities",
    "health",
    "concurrency_limit",
    "rate_limit_summary",
    "last_heartbeat_at",
    "created_at",
    "revoked_at",
}


def principal(tenant: str, actor: str = "actor-a", *roles: str) -> Principal:
    return Principal(
        actor_id=actor,
        roles=frozenset(roles or ("admin",)),
        tenant_ref=tenant,
    )


@pytest.fixture
def registry():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[MediaConnectorRow.__table__, MediaConnectorEventRow.__table__],
    )
    return MediaConnectorRegistry(engine=engine, clock=lambda: NOW)


def register(
    registry: MediaConnectorRegistry,
    tenant: str = "tenant-a",
    *,
    idempotency_key: str = "register-a",
    capabilities: list[str] | None = None,
):
    return registry.register(
        principal=principal(tenant),
        provider="codex_oauth",
        deployment_mode="customer_local",
        protocol_version="codex-app-server/1",
        capabilities=capabilities or ["image_generation", "image_editing"],
        concurrency_limit=1,
        idempotency_key=idempotency_key,
    )


def test_registration_is_descriptor_only_and_tenant_derived(registry):
    result = register(registry)
    descriptor = result["connector"]

    assert result["contract_id"] == CONTRACT_ID
    assert set(descriptor) == DESCRIPTOR_FIELDS
    assert descriptor["derived_tenant_ref"] == "tenant-a"
    assert descriptor["health"] == "ENROLLING"
    assert descriptor["concurrency_limit"] == 1
    assert not {
        "cookie",
        "token",
        "secret",
        "password",
        "credential",
        "oauth",
    }.intersection(descriptor)


def test_registry_contract_drift_fails_closed(registry):
    payload = deepcopy(registry.contract.payload)
    payload["connector_contract"]["shared_pool"] = True
    with pytest.raises(RuntimeError, match="shared_pool"):
        MediaConnectorContract(payload=payload)


def test_registration_replays_same_payload_and_rejects_drift(registry):
    first = register(registry)
    assert register(registry) == first

    with pytest.raises(MediaConnectorConflictError, match="payload drifted"):
        register(registry, capabilities=["image_generation"])

    with registry.engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(MediaConnectorRow)
        ) == 1


def test_health_history_is_append_only_hash_chain(registry):
    connector_ref = register(registry)["connector"]["connector_ref"]
    ready = registry.observe(
        principal=principal("tenant-a", "monitor-a", "monitor"),
        connector_ref=connector_ref,
        health="READY",
        observed_at=NOW + timedelta(seconds=1),
        rate_limit_status="ok",
        rate_limit_observed_at=NOW + timedelta(seconds=1),
        retry_after_at=None,
        idempotency_key="ready-a",
    )
    limited = registry.observe(
        principal=principal("tenant-a", "monitor-a", "monitor"),
        connector_ref=connector_ref,
        health="LIMITED",
        observed_at=NOW + timedelta(seconds=2),
        rate_limit_status="limited",
        rate_limit_observed_at=NOW + timedelta(seconds=2),
        retry_after_at=NOW + timedelta(minutes=1),
        idempotency_key="limited-a",
    )

    assert ready["connector"]["health"] == "READY"
    assert limited["connector"]["health"] == "LIMITED"
    assert limited["connector"]["rate_limit_summary"]["status"] == "limited"
    with registry.engine.connect() as connection:
        events = list(
            connection.execute(
                select(MediaConnectorEventRow)
                .where(MediaConnectorEventRow.connector_ref == connector_ref)
                .order_by(MediaConnectorEventRow.sequence)
            ).mappings()
        )
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert events[0]["previous_event_sha256"] == ZERO_SHA256
    assert events[1]["previous_event_sha256"] == events[0]["event_sha256"]
    assert events[2]["previous_event_sha256"] == events[1]["event_sha256"]


def test_event_idempotency_drift_and_backwards_time_fail(registry):
    connector_ref = register(registry)["connector"]["connector_ref"]
    values = dict(
        principal=principal("tenant-a", "operator-a", "operator"),
        connector_ref=connector_ref,
        health="READY",
        observed_at=NOW + timedelta(seconds=1),
        rate_limit_status=None,
        rate_limit_observed_at=None,
        retry_after_at=None,
        idempotency_key="observation-a",
    )
    first = registry.observe(**values)
    assert registry.observe(**values) == first
    with pytest.raises(MediaConnectorConflictError, match="payload drifted"):
        registry.observe(**{**values, "health": "BUSY"})
    with pytest.raises(ValueError, match="moved backwards"):
        registry.observe(
            **{
                **values,
                "observed_at": NOW,
                "idempotency_key": "observation-b",
            }
        )


def test_revoke_is_terminal_but_same_command_replays(registry):
    connector_ref = register(registry)["connector"]["connector_ref"]
    command = dict(
        principal=principal("tenant-a"),
        connector_ref=connector_ref,
        observed_at=NOW + timedelta(seconds=1),
        idempotency_key="revoke-a",
    )
    first = registry.revoke(**command)
    assert first["connector"]["health"] == "REVOKED"
    assert registry.revoke(**command) == first
    with pytest.raises(MediaConnectorConflictError, match="already revoked"):
        registry.observe(
            principal=principal("tenant-a", "monitor-a", "monitor"),
            connector_ref=connector_ref,
            health="READY",
            observed_at=NOW + timedelta(seconds=2),
            rate_limit_status=None,
            rate_limit_observed_at=None,
            retry_after_at=None,
            idempotency_key="post-revoke",
        )


def test_cross_tenant_access_is_not_found_and_list_is_exact(registry):
    connector_ref = register(registry, "tenant-a")["connector"]["connector_ref"]
    register(registry, "tenant-b", idempotency_key="register-b")
    outsider = principal("tenant-b", "monitor-b", "monitor")

    assert len(registry.list(principal=outsider)["items"]) == 1
    with pytest.raises(KeyError, match="not found"):
        registry.get(principal=outsider, connector_ref=connector_ref)
    with pytest.raises(KeyError, match="not found"):
        registry.observe(
            principal=outsider,
            connector_ref=connector_ref,
            health="READY",
            observed_at=NOW + timedelta(seconds=1),
            rate_limit_status=None,
            rate_limit_observed_at=None,
            retry_after_at=None,
            idempotency_key="cross-tenant",
        )


def test_eligibility_requires_exact_binding_capability_and_ready(registry):
    connector_ref = register(registry)["connector"]["connector_ref"]
    with pytest.raises(PermissionError, match="not ready"):
        registry.require_eligible(
            tenant_ref="tenant-a",
            connector_ref=connector_ref,
            provider="codex_oauth",
            required_capabilities={"image_generation"},
            as_of=NOW,
        )
    registry.observe(
        principal=principal("tenant-a", "monitor-a", "monitor"),
        connector_ref=connector_ref,
        health="READY",
        observed_at=NOW + timedelta(seconds=1),
        rate_limit_status=None,
        rate_limit_observed_at=None,
        retry_after_at=None,
        idempotency_key="ready-a",
    )
    eligible = registry.require_eligible(
        tenant_ref="tenant-a",
        connector_ref=connector_ref,
        provider="codex_oauth",
        required_capabilities={"image_generation"},
        as_of=NOW + timedelta(seconds=2),
    )
    assert eligible["connector"]["health"] == "READY"
    with pytest.raises(PermissionError, match="Provider binding"):
        registry.require_eligible(
            tenant_ref="tenant-a",
            connector_ref=connector_ref,
            provider="comfyui",
            required_capabilities={"image_generation"},
            as_of=NOW + timedelta(seconds=2),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocol_version", "Bearer hidden"),
        ("idempotency_key", "sk-secret-value"),
        ("protocol_version", "cookie=session"),
    ],
)
def test_secret_shaped_registration_values_are_rejected(registry, field, value):
    values = {
        "principal": principal("tenant-a"),
        "provider": "codex_oauth",
        "deployment_mode": "customer_local",
        "protocol_version": "codex-app-server/1",
        "capabilities": ["image_generation"],
        "concurrency_limit": 1,
        "idempotency_key": "registration-a",
    }
    values[field] = value
    with pytest.raises(ValueError):
        registry.register(**values)
