from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import DBAPIError

from apps.control_plane.media_connectors import (
    ZERO_SHA256,
    MediaConnectorConflictError,
    MediaConnectorEventRow,
    MediaConnectorRegistry,
)
from apps.control_plane.security import Principal

DATABASE_URL = os.getenv("KJDS_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="PostgreSQL contract tests require KJDS_DATABASE_URL",
)
BASE = datetime(2026, 8, 3, 9, tzinfo=UTC)


def principal(tenant: str, actor: str = "admin-a", *roles: str) -> Principal:
    return Principal(
        actor_id=actor,
        roles=frozenset(roles or ("admin",)),
        tenant_ref=tenant,
    )


@pytest.fixture(scope="module")
def engine():
    target = create_engine(DATABASE_URL, pool_pre_ping=True)
    yield target
    target.dispose()


@pytest.fixture
def registry(engine):
    return MediaConnectorRegistry(engine=engine, clock=lambda: BASE)


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def register(registry, tenant: str, key: str):
    return registry.register(
        principal=principal(tenant),
        provider="codex_oauth",
        deployment_mode="hosted_isolated",
        protocol_version="codex-app-server/1",
        capabilities=["image_generation", "image_editing"],
        concurrency_limit=1,
        idempotency_key=key,
    )


def test_00_migration_replays_0090_to_0091_to_0090_to_0091(engine):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

    command.downgrade(config, "20260803_0090")
    assert "media_connectors" not in inspect(engine).get_table_names()
    command.upgrade(config, "20260803_0091")
    assert {"media_connectors", "media_connector_events"}.issubset(
        inspect(engine).get_table_names()
    )
    command.downgrade(config, "20260803_0090")
    assert "media_connectors" not in inspect(engine).get_table_names()
    command.upgrade(config, "20260803_0091")

    with engine.connect() as connection:
        assert connection.scalar(
            text("SELECT version_num FROM alembic_version")
        ) == "20260803_0091"
        triggers = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgname LIKE 'trg_media_connector%'"
                )
            )
        )
    assert triggers == {
        "trg_media_connector_event_append_guard",
        "trg_media_connector_events_immutable",
        "trg_media_connectors_immutable",
    }


def test_concurrent_registration_is_one_binding_and_one_event(engine, registry):
    tenant = unique("tenant-concurrent-register")
    key = unique("registration")
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: register(registry, tenant, key), range(8)))

    connector_refs = {
        result["connector"]["connector_ref"] for result in results
    }
    assert len(connector_refs) == 1
    connector_ref = connector_refs.pop()
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM media_connectors "
                "WHERE tenant_ref=:tenant AND connector_ref=:connector"
            ),
            {"tenant": tenant, "connector": connector_ref},
        ) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM media_connector_events "
                "WHERE tenant_ref=:tenant AND connector_ref=:connector"
            ),
            {"tenant": tenant, "connector": connector_ref},
        ) == 1


def test_concurrent_health_events_are_row_locked_and_hash_chained(engine, registry):
    tenant = unique("tenant-concurrent-events")
    connector_ref = register(registry, tenant, unique("registration"))["connector"][
        "connector_ref"
    ]

    def observe(index: int):
        return registry.observe(
            principal=principal(tenant, f"monitor-{index}", "monitor"),
            connector_ref=connector_ref,
            health="READY" if index % 2 == 0 else "BUSY",
            observed_at=BASE,
            rate_limit_status=None,
            rate_limit_observed_at=None,
            retry_after_at=None,
            idempotency_key=f"observation-{uuid4().hex}",
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(observe, range(8)))

    with engine.connect() as connection:
        events = list(
            connection.execute(
                select(MediaConnectorEventRow)
                .where(
                    MediaConnectorEventRow.tenant_ref == tenant,
                    MediaConnectorEventRow.connector_ref == connector_ref,
                )
                .order_by(MediaConnectorEventRow.sequence)
            ).mappings()
        )
    assert [event["sequence"] for event in events] == list(range(1, 10))
    assert events[0]["previous_event_sha256"] == ZERO_SHA256
    for previous, current in pairwise(events):
        assert current["previous_event_sha256"] == previous["event_sha256"]


def test_database_rejects_cross_tenant_event_and_mutation(engine, registry):
    tenant = unique("tenant-exact")
    connector_ref = register(registry, tenant, unique("registration"))["connector"][
        "connector_ref"
    ]
    with engine.connect() as connection:
        source = connection.execute(
            text(
                "SELECT * FROM media_connector_events "
                "WHERE connector_ref=:connector AND tenant_ref=:tenant"
            ),
            {"connector": connector_ref, "tenant": tenant},
        ).mappings().one()
    forged = dict(source)
    forged.update(
        event_ref=f"mce_{uuid4().hex}",
        tenant_ref=unique("tenant-forged"),
        observation_request_sha256="a" * 64,
        idempotency_sha256="b" * 64,
        event_sha256="c" * 64,
    )
    columns = ",".join(forged)
    parameters = ",".join(f":{name}" for name in forged)
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO media_connector_events ({columns}) "
                f"VALUES ({parameters})"
            ),
            forged,
        )
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE media_connectors SET protocol_version='drift/2' "
                "WHERE connector_ref=:connector"
            ),
            {"connector": connector_ref},
        )


def test_database_and_read_model_contain_no_secret_columns(engine, registry):
    tenant = unique("tenant-descriptor")
    result = register(registry, tenant, unique("registration"))
    banned = {"cookie", "token", "secret", "password", "credential", "api_key"}
    inspector = inspect(engine)
    for table in ("media_connectors", "media_connector_events"):
        names = {column["name"].lower() for column in inspector.get_columns(table)}
        assert not any(marker in name for name in names for marker in banned)
    descriptor_names = set(result["connector"])
    assert not any(marker in name for name in descriptor_names for marker in banned)


def test_revoked_is_terminal_in_service_and_database(engine, registry):
    tenant = unique("tenant-revoked")
    connector_ref = register(registry, tenant, unique("registration"))["connector"][
        "connector_ref"
    ]
    registry.revoke(
        principal=principal(tenant),
        connector_ref=connector_ref,
        observed_at=BASE,
        idempotency_key=unique("revoke"),
    )
    with pytest.raises(MediaConnectorConflictError, match="revoked"):
        registry.observe(
            principal=principal(tenant, "monitor-a", "monitor"),
            connector_ref=connector_ref,
            health="READY",
            observed_at=BASE + timedelta(seconds=1),
            rate_limit_status=None,
            rate_limit_observed_at=None,
            retry_after_at=None,
            idempotency_key=unique("post-revoke"),
        )
    with engine.connect() as connection:
        latest = connection.execute(
            text(
                "SELECT * FROM media_connector_events "
                "WHERE connector_ref=:connector AND tenant_ref=:tenant "
                "ORDER BY sequence DESC LIMIT 1"
            ),
            {"connector": connector_ref, "tenant": tenant},
        ).mappings().one()
    forged = dict(latest)
    forged.update(
        event_ref=f"mce_{uuid4().hex}",
        sequence=latest["sequence"] + 1,
        event_type="health_observed",
        health="READY",
        rate_limit_status=None,
        rate_limit_observed_at=None,
        retry_after_at=None,
        observation_request_sha256="d" * 64,
        idempotency_sha256="e" * 64,
        previous_event_sha256=latest["event_sha256"],
        event_sha256="f" * 64,
        observed_at=BASE + timedelta(seconds=1),
        recorded_at=BASE + timedelta(seconds=1),
    )
    columns = ",".join(forged)
    parameters = ",".join(f":{name}" for name in forged)
    with pytest.raises(DBAPIError, match="terminal"), engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO media_connector_events ({columns}) "
                f"VALUES ({parameters})"
            ),
            forged,
        )
