from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.pool import StaticPool

from apps.control_plane.autonomous_execution_profile import StandingAutonomousExecutionProfile
from apps.control_plane.autonomous_execution_profile_store import (
    AutonomousExecutionProfileRevisionRow,
    AutonomousExecutionProfileStore,
)
from apps.control_plane.sql_repository import Base


@pytest.fixture
def store():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[AutonomousExecutionProfileRevisionRow.__table__],
    )
    # Event table is part of the same metadata but is intentionally created
    # explicitly so this contract remains independent of other application
    # tables.
    from apps.control_plane.autonomous_execution_profile_store import AutonomousExecutionProfileEventRow

    Base.metadata.create_all(engine, tables=[AutonomousExecutionProfileEventRow.__table__])
    return AutonomousExecutionProfileStore(engine), engine


def profile() -> StandingAutonomousExecutionProfile:
    return StandingAutonomousExecutionProfile(
        profile_id="profile-1",
        tenant_ref="tenant-a",
        entity_ref="entity-a",
        store_refs=frozenset({"store-a"}),
        allowed_channels=frozenset({"ozon"}),
        allowed_operations=frozenset({"listing.update"}),
        enabled=False,
        max_command_amount=Decimal("10.00"),
        expires_at=datetime(2026, 10, 6, tzinfo=UTC),
    )


def test_profile_lifecycle_is_append_only_and_idempotent(store):
    service, engine = store
    created = service.create(
        profile(), idempotency_key="create-1", actor_id="owner", reviewer_id="reviewer", compliance_id="compliance"
    )
    assert created.enabled is False
    assert service.create(
        profile(), idempotency_key="create-1", actor_id="owner", reviewer_id="reviewer", compliance_id="compliance"
    ).profile_sha256 == created.profile_sha256
    assert service.current(profile_id="profile-1", tenant_ref="tenant-a", entity_ref="entity-a").enabled is False

    activated = service.activate(
        profile_id="profile-1", tenant_ref="tenant-a", entity_ref="entity-a",
        idempotency_key="activate-1", actor_id="owner", reviewer_id="reviewer", compliance_id="compliance",
        now=datetime(2026, 9, 6, tzinfo=UTC),
    )
    assert activated.enabled is True
    assert activated.activated_at == datetime(2026, 9, 6, tzinfo=UTC)
    assert service.activate(
        profile_id="profile-1", tenant_ref="tenant-a", entity_ref="entity-a",
        idempotency_key="activate-1", actor_id="owner", reviewer_id="reviewer", compliance_id="compliance",
    ).profile_sha256 == activated.profile_sha256

    suspended = service.suspend(
        profile_id="profile-1", tenant_ref="tenant-a", entity_ref="entity-a",
        idempotency_key="suspend-1", actor_id="owner", reviewer_id="reviewer", compliance_id="compliance",
    )
    assert suspended.enabled is False
    assert [item["event"] for item in service.history(profile_id="profile-1", tenant_ref="tenant-a", entity_ref="entity-a")] == [
        "created", "activated", "suspended"
    ]
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(AutonomousExecutionProfileRevisionRow)) == 3


def test_profile_governance_requires_distinct_identities_and_exact_scope(store):
    service, _engine = store
    with pytest.raises(ValueError, match="distinct"):
        service.create(profile(), idempotency_key="create-1", actor_id="same", reviewer_id="same", compliance_id="compliance")
    service.create(
        profile(), idempotency_key="create-1", actor_id="owner", reviewer_id="reviewer", compliance_id="compliance"
    )
    with pytest.raises(KeyError, match="exact scope"):
        service.current(profile_id="profile-1", tenant_ref="tenant-b", entity_ref="entity-a")
    with pytest.raises(ValueError, match="idempotency key conflicts"):
        service.create(
            profile(), idempotency_key="create-1", actor_id="other", reviewer_id="reviewer", compliance_id="compliance"
        )
