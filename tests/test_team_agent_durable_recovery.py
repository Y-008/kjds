from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.agent_team_orchestration import TeamAgentCoordinator
from apps.control_plane.enterprise_control import ExactScope
from apps.control_plane.team_agent_checkpoint_store import (
    InMemoryTeamAgentCheckpointStore,
)
from apps.control_plane.team_agent_durable_recovery import (
    TeamAgentDurableRecovery,
    TeamAgentDurableRecoveryError,
    team_agent_durable_task_payload,
)
from apps.control_plane.team_agent_persistence import (
    InMemoryTeamAgentPersistence,
    TeamAgentTaskRegistration,
)

SCOPE = ExactScope("tenant-a", "entity-a", "ozon-primary")
AUTHORITY = "a" * 64
T0 = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)


def _coordinator() -> TeamAgentCoordinator:
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref="session-a",
        scope=SCOPE,
        objective="durable recovery",
        owner_id="operator-a",
        authority_sha256=AUTHORITY,
        created_at=T0,
    )
    coordinator.submit_task(
        session_ref="session-a",
        task_ref="catalog-read",
        thread_ref="session-a:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="read current catalog",
        idempotency_key="catalog-read-1",
        created_at=T0,
    )
    return coordinator


def _registered_runtime() -> tuple[
    TeamAgentCoordinator,
    InMemoryTeamAgentCheckpointStore,
    InMemoryTeamAgentPersistence,
]:
    coordinator = _coordinator()
    tasks = InMemoryTeamAgentPersistence()
    persisted = tasks.register_task(
        scope=SCOPE,
        task=TeamAgentTaskRegistration(
            session_ref="session-a",
            task_ref="catalog-read",
            idempotency_key="catalog-read-1",
            payload=team_agent_durable_task_payload(
                coordinator.task("catalog-read")
            ),
        ),
        as_of=T0,
    )
    coordinator.bind_durable_task_revision(
        task_ref="catalog-read",
        revision=persisted.revision,
        request_sha256=persisted.request_sha256,
    )
    checkpoints = InMemoryTeamAgentCheckpointStore()
    checkpoints.save(
        coordinator=coordinator,
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    return coordinator, checkpoints, tasks


def test_restore_requires_exact_0099_task_projection_and_revision() -> None:
    _, checkpoints, tasks = _registered_runtime()
    restored = TeamAgentDurableRecovery(
        checkpoints=checkpoints,
        tasks=tasks,
    ).restore(
        scope=SCOPE,
        session_ref="session-a",
        authority_sha256=AUTHORITY,
        as_of=T0,
    )

    assert restored.task_revisions == {"catalog-read": 0}
    assert restored.coordinator.task("catalog-read").state.value == "queued"
    assert len(restored.task_checkpoint_sha256) == 64


def test_postgres_recovery_requires_one_shared_caller_connection() -> None:
    class Adapter:
        def __init__(self, connection):
            self._connection = connection

    with pytest.raises(
        TeamAgentDurableRecoveryError,
        match="shared connection",
    ):
        TeamAgentDurableRecovery(
            checkpoints=Adapter(None),
            tasks=Adapter(None),
        )

    shared = object()
    TeamAgentDurableRecovery(
        checkpoints=Adapter(shared),
        tasks=Adapter(shared),
    )


def test_restore_rejects_revision_drift_even_when_sidecar_is_well_formed() -> None:
    coordinator, checkpoints, tasks = _registered_runtime()
    coordinator.bind_durable_task_revision(
        task_ref="catalog-read",
        revision=1,
        request_sha256=tasks.task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
        ).request_sha256,
    )
    checkpoints.save(
        coordinator=coordinator,
        session_ref="session-a",
        expected_revision=0,
        as_of=T0,
    )

    with pytest.raises(TeamAgentDurableRecoveryError, match="revision conflict"):
        TeamAgentDurableRecovery(checkpoints=checkpoints, tasks=tasks).restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
            as_of=T0,
        )


def test_restore_rejects_projection_or_task_set_drift() -> None:
    coordinator, checkpoints, tasks = _registered_runtime()
    coordinator.claim_task(
        task_ref="catalog-read",
        worker_id="reader-a",
        as_of=T0,
    )
    checkpoints.save(
        coordinator=coordinator,
        session_ref="session-a",
        expected_revision=0,
        as_of=T0,
    )
    with pytest.raises(TeamAgentDurableRecoveryError, match="projection conflict"):
        TeamAgentDurableRecovery(checkpoints=checkpoints, tasks=tasks).restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
            as_of=T0,
        )

    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-a",
        task_ref="orders-read",
        thread_ref="session-a:root",
        agent_id="reader-b",
        role="orders_reader",
        objective="read orders",
        idempotency_key="orders-read-1",
        created_at=T0,
    )
    coordinator.bind_durable_task_revision(
        task_ref="catalog-read",
        revision=0,
        request_sha256=tasks.task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
        ).request_sha256,
    )
    coordinator.bind_durable_task_revision(
        task_ref="orders-read",
        revision=0,
        request_sha256="b" * 64,
    )
    missing_task_checkpoint = InMemoryTeamAgentCheckpointStore()
    missing_task_checkpoint.save(
        coordinator=coordinator,
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )
    with pytest.raises(TeamAgentDurableRecoveryError, match="task sets"):
        TeamAgentDurableRecovery(
            checkpoints=missing_task_checkpoint,
            tasks=tasks,
        ).restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
            as_of=T0,
        )


def test_restore_rejects_request_identity_drift() -> None:
    coordinator = _coordinator()
    tasks = InMemoryTeamAgentPersistence()
    persisted = tasks.register_task(
        scope=SCOPE,
        task=TeamAgentTaskRegistration(
            session_ref="session-a",
            task_ref="catalog-read",
            idempotency_key="catalog-read-1",
            payload={
                **team_agent_durable_task_payload(
                    coordinator.task("catalog-read")
                ),
                "objective": "different durable request",
            },
        ),
        as_of=T0,
    )
    coordinator.bind_durable_task_revision(
        task_ref="catalog-read",
        revision=persisted.revision,
        request_sha256="b" * 64,
    )
    checkpoints = InMemoryTeamAgentCheckpointStore()
    checkpoints.save(
        coordinator=coordinator,
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )

    with pytest.raises(TeamAgentDurableRecoveryError, match="request identity"):
        TeamAgentDurableRecovery(checkpoints=checkpoints, tasks=tasks).restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
            as_of=T0,
        )


def test_restore_rejects_terminal_result_evidence_and_reviewer_drift() -> None:
    coordinator = _coordinator()
    tasks = InMemoryTeamAgentPersistence()
    persisted = tasks.register_task(
        scope=SCOPE,
        task=TeamAgentTaskRegistration(
            session_ref="session-a",
            task_ref="catalog-read",
            idempotency_key="catalog-read-1",
            payload=team_agent_durable_task_payload(
                coordinator.task("catalog-read")
            ),
        ),
        as_of=T0,
    )
    sidecar_claim = coordinator.claim_task(
        task_ref="catalog-read",
        worker_id="sidecar-worker",
        as_of=T0,
    )
    coordinator.complete_task(
        task_ref="catalog-read",
        worker_id="sidecar-worker",
        lease_ref=sidecar_claim.lease_ref,
        result={"status": "sidecar"},
        evidence_refs=("ev-sidecar",),
        reviewer_id="reviewer-sidecar",
        as_of=T0,
    )
    durable_claim = tasks.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="durable-worker",
        lease_seconds=120,
        as_of=T0,
    )
    durable_completed = tasks.complete_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="durable-worker",
        lease_ref=durable_claim.lease_ref or "missing",
        result={"status": "durable"},
        evidence_refs=("ev-durable",),
        reviewer_id="reviewer-durable",
        as_of=T0,
    )
    coordinator.bind_durable_task_revision(
        task_ref="catalog-read",
        revision=durable_completed.revision,
        request_sha256=persisted.request_sha256,
    )
    checkpoints = InMemoryTeamAgentCheckpointStore()
    checkpoints.save(
        coordinator=coordinator,
        session_ref="session-a",
        expected_revision=None,
        as_of=T0,
    )

    with pytest.raises(TeamAgentDurableRecoveryError, match="projection conflict"):
        TeamAgentDurableRecovery(checkpoints=checkpoints, tasks=tasks).restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
            as_of=T0,
        )


def test_expired_lease_is_only_admitted_for_locked_controlled_recovery() -> None:
    coordinator, checkpoints, tasks = _registered_runtime()
    durable = tasks.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="reader-a",
        lease_seconds=2,
        as_of=T0,
    )
    coordinator.claim_task(
        task_ref="catalog-read",
        worker_id="reader-a",
        lease_seconds=2,
        lease_id=durable.lease_ref,
        as_of=T0,
    )
    coordinator.bind_durable_task_revision(
        task_ref="catalog-read",
        revision=durable.revision,
        request_sha256=durable.request_sha256,
    )
    checkpoints.save(
        coordinator=coordinator,
        session_ref="session-a",
        expected_revision=0,
        as_of=T0,
    )
    recovery = TeamAgentDurableRecovery(checkpoints=checkpoints, tasks=tasks)

    with pytest.raises(TeamAgentDurableRecoveryError, match="controlled recovery"):
        recovery.restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
            as_of=T0 + timedelta(seconds=2),
        )
    with pytest.raises(ValueError, match="caller-owned locked recovery"):
        recovery.restore(
            scope=SCOPE,
            session_ref="session-a",
            authority_sha256=AUTHORITY,
            as_of=T0 + timedelta(seconds=2),
            allow_expired_leases=True,
        )

    admitted = recovery.restore(
        scope=SCOPE,
        session_ref="session-a",
        authority_sha256=AUTHORITY,
        as_of=T0 + timedelta(seconds=2),
        for_update=True,
        allow_expired_leases=True,
    )
    assert admitted.coordinator.task("catalog-read").state.value == "running"
