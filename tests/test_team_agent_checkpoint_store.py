from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.control_plane.agent_team_orchestration import TeamAgentCoordinator
from apps.control_plane.enterprise_control import ExactScope
from apps.control_plane.team_agent_checkpoint_store import (
    InMemoryTeamAgentCheckpointStore,
    TeamAgentCheckpointConflict,
    TeamAgentCheckpointIntegrityError,
    TeamAgentCheckpointNotFound,
)

SCOPE = ExactScope("tenant-a", "entity-a", "ozon-primary")
OTHER_SCOPE = ExactScope("tenant-b", "entity-b", "ozon-secondary")
AUTHORITY = "a" * 64
T0 = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)


def coordinator() -> TeamAgentCoordinator:
    value = TeamAgentCoordinator()
    value.create_session(
        session_ref="session-a",
        scope=SCOPE,
        objective="durable Ozon read orchestration",
        owner_id="operator-a",
        authority_sha256=AUTHORITY,
        created_at=T0,
    )
    value.submit_task(
        session_ref="session-a",
        task_ref="catalog-read",
        thread_ref="session-a:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="read current catalog",
        idempotency_key="catalog-read-1",
        created_at=T0,
    )
    return value


def test_checkpoint_save_cas_and_restart_hydration_roundtrip() -> None:
    store = InMemoryTeamAgentCheckpointStore()
    active = coordinator()
    initial = store.save(
        coordinator=active,
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    active.claim_task(
        task_ref="catalog-read",
        worker_id="reader-a",
        lease_seconds=120,
        as_of=T0,
    )
    claimed = store.save(
        coordinator=active,
        session_ref="session-a",
        expected_revision=initial.revision,
        as_of=T0,
    )

    hydrated = store.restore(
        scope=SCOPE,
        session_ref="session-a",
        authority_sha256=AUTHORITY,
    )
    restored_task = hydrated.coordinator.task("catalog-read")
    assert initial.revision == 0
    assert claimed.revision == hydrated.durable.revision == 1
    assert restored_task.state.value == "running"
    assert restored_task.claimed_by == "reader-a"
    assert hydrated.coordinator.checkpoint(session_ref="session-a") == active.checkpoint(
        session_ref="session-a"
    )


def test_initial_save_is_idempotent_but_stale_revision_loses_cas() -> None:
    store = InMemoryTeamAgentCheckpointStore()
    active = coordinator()
    initial = store.save(
        coordinator=active,
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    assert (
        store.save(
            coordinator=active,
            session_ref="session-a",
            expected_revision=None,
            as_of=T0,
        )
        == initial
    )
    assert (
        store.save(
            coordinator=active,
            session_ref="session-a",
            expected_revision=initial.revision,
            as_of=T0,
        )
        == initial
    )
    active.pause(
        session_ref="session-a",
        reason="controlled restart",
        actor_id="operator-a",
        as_of=T0,
    )
    current = store.save(
        coordinator=active,
        session_ref="session-a",
        expected_revision=0,
        as_of=T0,
    )
    assert current.revision == 1
    with pytest.raises(TeamAgentCheckpointConflict, match="CAS lost"):
        store.save(
            coordinator=active,
            session_ref="session-a",
            expected_revision=0,
            as_of=T0,
        )


def test_restore_rejects_checkpoint_history_gap_and_time_regression() -> None:
    store = InMemoryTeamAgentCheckpointStore()
    active = coordinator()
    initial = store.save(
        coordinator=active,
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    active.pause(
        session_ref="session-a",
        reason="controlled restart",
        actor_id="operator-a",
        as_of=T0,
    )
    store.save(
        coordinator=active,
        session_ref="session-a",
        expected_revision=initial.revision,
        as_of=T0,
    )
    store._history.pop(0)
    with pytest.raises(TeamAgentCheckpointIntegrityError, match="history"):
        store.restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
        )

    empty_history = InMemoryTeamAgentCheckpointStore()
    empty_active = coordinator()
    empty_history.save(
        coordinator=empty_active,
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    empty_history._history.clear()
    with pytest.raises(TeamAgentCheckpointIntegrityError, match="history"):
        empty_history.restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
        )

    clean = InMemoryTeamAgentCheckpointStore()
    created = clean.save(
        coordinator=coordinator(),
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    with pytest.raises(TeamAgentCheckpointConflict, match="timestamp regresses"):
        clean.save(
            coordinator=active,
            session_ref="session-a",
            expected_revision=created.revision,
            as_of=T0.replace(hour=8),
        )


def test_restore_fails_closed_for_scope_or_authority_drift() -> None:
    store = InMemoryTeamAgentCheckpointStore()
    store.save(
        coordinator=coordinator(),
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    with pytest.raises(TeamAgentCheckpointNotFound):
        store.restore(
            scope=OTHER_SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
        )
    with pytest.raises(TeamAgentCheckpointIntegrityError, match="authority is stale"):
        store.restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256="b" * 64,
        )


def test_save_rejects_session_without_current_authority() -> None:
    active = TeamAgentCoordinator()
    active.create_session(
        session_ref="session-a",
        scope=SCOPE,
        objective="missing authority",
        owner_id="operator-a",
        created_at=T0,
    )
    with pytest.raises(
        TeamAgentCheckpointIntegrityError,
        match="authority_sha256",
    ):
        InMemoryTeamAgentCheckpointStore().save(
            coordinator=active,
            session_ref="session-a",
            expected_revision=None,
            as_of=T0,
        )


def test_public_checkpoint_records_are_defensive_copies() -> None:
    store = InMemoryTeamAgentCheckpointStore()
    saved = store.save(
        coordinator=coordinator(),
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    saved.checkpoint["sessions"][0]["objective"] = "caller tamper"

    first_restore = store.restore(
        scope=SCOPE,
        session_ref="session-a",
        authority_sha256=AUTHORITY,
    )
    assert first_restore.coordinator.session("session-a").objective == (
        "durable Ozon read orchestration"
    )

    first_restore.durable.checkpoint["sessions"][0]["objective"] = (
        "restore result tamper"
    )
    second_restore = store.restore(
        scope=SCOPE,
        session_ref="session-a",
        authority_sha256=AUTHORITY,
    )
    assert second_restore.coordinator.session("session-a").objective == (
        "durable Ozon read orchestration"
    )
