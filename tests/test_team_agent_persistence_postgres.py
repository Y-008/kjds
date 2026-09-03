from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from multiprocessing import get_context
from multiprocessing.queues import Queue
from threading import Barrier
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

from apps.control_plane.agent_harness import AgentHarnessService
from apps.control_plane.agent_team_orchestration import (
    OrchestrationError,
    TeamAgentCoordinator,
)
from apps.control_plane.enterprise_control import ExactScope
from apps.control_plane.security import Principal
from apps.control_plane.team_agent_checkpoint_store import (
    PostgresTeamAgentCheckpointStore,
    TeamAgentCheckpointConflict,
    TeamAgentCheckpointIntegrityError,
)
from apps.control_plane.team_agent_durable_recovery import (
    TeamAgentDurableRecoveryError,
    team_agent_durable_task_payload,
)
from apps.control_plane.team_agent_persistence import (
    DurableTaskState,
    PostgresTeamAgentPersistence,
    TeamAgentPersistenceConflict,
    TeamAgentTaskNotFound,
    TeamAgentTaskRegistration,
)
from apps.control_plane.team_agent_postgres_runtime import PostgresTeamAgentRuntime
from apps.control_plane.team_agent_result_contract import (
    TeamAgentResultContractError,
)

DATABASE_URL = os.getenv("KJDS_TEAM_AGENT_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="TeamAgent PostgreSQL contract tests require KJDS_TEAM_AGENT_DATABASE_URL",
)

SCOPE = ExactScope("tenant-pg", "entity-pg", "ozon-pg")
OTHER_SCOPE = ExactScope("tenant-other", "entity-other", "ozon-other")
T0 = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
UNSAFE_RESULTS = (
    pytest.param({"secret": "credential-material"}, id="secret-key"),
    pytest.param(
        {"message": "Authorization: Bearer abcdefghijklmnop"},
        id="bearer-value",
    ),
    pytest.param({"Fact": {"status": "minted"}}, id="fact"),
    pytest.param({"FinanceEntry": {"amount": "1.00"}}, id="finance-entry"),
    pytest.param({"Approval": {"status": "approved"}}, id="approval"),
    pytest.param({"Permit": {"status": "issued"}}, id="permit"),
    pytest.param({"external-write": True}, id="external-write"),
)
TABLES = {
    "team_agent_orchestration_tasks",
    "team_agent_orchestration_events",
    "team_agent_orchestration_checkpoints",
    "team_agent_orchestration_checkpoint_events",
}
ISSUANCE_OWNER_ROLE = "kjds_gdc_issuance_owner"
ISSUANCE_CALLER_ROLE = "kjds_gdc_issuance_runtime"
CLOE_ISSUANCE_OWNER_ROLE = "kjds_cloe_issuance_owner"
CLOE_EVENT_ISSUANCE_OWNER_ROLE = "kjds_cloe_event_issuance_owner"
CLOE_ISSUANCE_RUNTIME_ROLE = "kjds_cloe_issuance_runtime"
CLOE_ATTESTATION_ROLES = (
    "kjds_cloe_experiment_authority",
    "kjds_cloe_cost_authority",
    "kjds_cloe_outcome_authority",
    "kjds_cloe_review_authority",
)


def _claim_team_agent_in_spawned_process(
    database_url: str,
    scope_values: tuple[str, str, str],
    session_ref: str,
    task_ref: str,
    worker_id: str,
    as_of: str,
    ready: Queue,
    start: Any,
    outcomes: Queue,
) -> None:
    """Run one claim from a fresh interpreter and database connection pool."""

    process_engine = create_engine(database_url, pool_pre_ping=True)
    try:
        ready.put(worker_id)
        if not start.wait(timeout=20):
            outcomes.put(("error", worker_id, "start timeout"))
            return
        try:
            claimed = PostgresTeamAgentRuntime(process_engine).claim_task(
                scope=ExactScope(*scope_values),
                session_ref=session_ref,
                authority_sha256="a" * 64,
                task_ref=task_ref,
                worker_id=worker_id,
                lease_seconds=30,
                as_of=datetime.fromisoformat(as_of),
            )
        except TeamAgentPersistenceConflict as exc:
            outcomes.put(("conflict", worker_id, type(exc).__name__))
        else:
            outcomes.put(("winner", worker_id, claimed.lease_ref))
    except BaseException as exc:  # pragma: no cover - reported to the parent
        outcomes.put(("error", worker_id, f"{type(exc).__name__}: {exc}"))
        raise
    finally:
        process_engine.dispose()


def _claim_and_crash_after_commit_before_ack(
    database_url: str,
    scope_values: tuple[str, str, str],
    session_ref: str,
    task_ref: str,
    worker_id: str,
    lease_ref: str,
    as_of: str,
    ready: Queue,
    start: Any,
) -> None:
    """Commit a claim, then lose the worker before its acknowledgement."""

    process_engine = create_engine(database_url, pool_pre_ping=True)
    ready.put(worker_id)
    if not start.wait(timeout=20):
        os._exit(92)
    PostgresTeamAgentRuntime(process_engine).claim_task(
        scope=ExactScope(*scope_values),
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id=worker_id,
        lease_seconds=30,
        lease_id=lease_ref,
        as_of=datetime.fromisoformat(as_of),
    )
    # The database commit has completed before claim_task returns.  Simulate
    # an OS/process loss in the response/ack window; there is no child result
    # for the parent to consume or replay.
    os._exit(91)


def _complete_and_crash_after_commit_before_ack(
    database_url: str,
    scope_values: tuple[str, str, str],
    session_ref: str,
    task_ref: str,
    worker_id: str,
    lease_ref: str,
    as_of: str,
    ready: Queue,
    start: Any,
) -> None:
    """Commit completion, then lose the worker before its acknowledgement."""

    process_engine = create_engine(database_url, pool_pre_ping=True)
    ready.put(worker_id)
    if not start.wait(timeout=20):
        os._exit(94)
    PostgresTeamAgentRuntime(process_engine).complete_task(
        scope=ExactScope(*scope_values),
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id=worker_id,
        lease_ref=lease_ref,
        result={"status": "observed", "items": 2},
        evidence_refs=("ev-response-loss",),
        reviewer_id="reviewer-a",
        cost_units=3,
        as_of=datetime.fromisoformat(as_of),
    )
    os._exit(93)


def _migration_config(engine: Engine) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        engine.url.render_as_string(hide_password=False).replace("%", "%%"),
    )
    return config


def _single_migration_head(config: Config) -> str:
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"expected one Alembic head, found {heads}"
    return heads[0]


def _provision_data_coverage_roles(admin: Engine) -> None:
    with admin.connect() as connection:
        connection.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = '{ISSUANCE_OWNER_ROLE}'
                    ) THEN
                        CREATE ROLE {ISSUANCE_OWNER_ROLE}
                        NOLOGIN NOSUPERUSER NOINHERIT NOCREATEROLE NOCREATEDB
                        NOREPLICATION BYPASSRLS;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = '{ISSUANCE_CALLER_ROLE}'
                    ) THEN
                        CREATE ROLE {ISSUANCE_CALLER_ROLE}
                        LOGIN NOSUPERUSER NOINHERIT NOCREATEROLE NOCREATEDB
                        NOREPLICATION NOBYPASSRLS;
                    END IF;
                END
                $$;
                """
            )
        )


def _provision_closed_loop_roles(admin: Engine) -> None:
    runtime_roles = (
        CLOE_ISSUANCE_RUNTIME_ROLE,
        *CLOE_ATTESTATION_ROLES,
    )
    with admin.connect() as connection:
        connection.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = '{CLOE_ISSUANCE_OWNER_ROLE}'
                    ) THEN
                        CREATE ROLE {CLOE_ISSUANCE_OWNER_ROLE}
                        NOLOGIN NOSUPERUSER NOINHERIT NOCREATEROLE NOCREATEDB
                        NOREPLICATION BYPASSRLS;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles
                        WHERE rolname = '{CLOE_EVENT_ISSUANCE_OWNER_ROLE}'
                    ) THEN
                        CREATE ROLE {CLOE_EVENT_ISSUANCE_OWNER_ROLE}
                        NOLOGIN NOSUPERUSER NOINHERIT NOCREATEROLE NOCREATEDB
                        NOREPLICATION BYPASSRLS;
                    END IF;
                END
                $$;
                """
            )
        )
        for role_name in runtime_roles:
            connection.execute(
                text(
                    f"""
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_roles WHERE rolname = '{role_name}'
                        ) THEN
                            CREATE ROLE {role_name}
                            LOGIN NOSUPERUSER NOINHERIT NOCREATEROLE NOCREATEDB
                            NOREPLICATION NOBYPASSRLS;
                        END IF;
                    END
                    $$;
                    """
                )
            )


@pytest.fixture(scope="module")
def engine() -> Engine:
    schema = f"team_agent_pg_{uuid4().hex}"
    admin = create_engine(DATABASE_URL, isolation_level="AUTOCOMMIT")
    _provision_data_coverage_roles(admin)
    _provision_closed_loop_roles(admin)
    with admin.connect() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(
            text(
                f'CREATE TABLE "{schema}".alembic_version '
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
    url = make_url(DATABASE_URL)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema}"
    target = create_engine(
        url.set(query=query),
        pool_pre_ping=True,
        pool_size=8,
        max_overflow=8,
    )
    previous = os.environ.get("KJDS_DATABASE_URL")
    # migrations/env.py assigns this environment URL through Alembic's
    # ConfigParser, so percent-encoded query parameters must remain escaped.
    os.environ["KJDS_DATABASE_URL"] = target.url.render_as_string(
        hide_password=False
    ).replace("%", "%%")
    config = _migration_config(target)
    migration_head = _single_migration_head(config)
    try:
        command.upgrade(config, "20260809_0098")
        command.upgrade(config, migration_head)
        assert TABLES.issubset(inspect(target).get_table_names())
        with target.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                migration_head
            )
        command.downgrade(config, "20260819_0100")
        command.downgrade(config, "20260809_0098")
        assert not TABLES.intersection(inspect(target).get_table_names())
        command.upgrade(config, migration_head)
        yield target
    finally:
        if previous is None:
            os.environ.pop("KJDS_DATABASE_URL", None)
        else:
            os.environ["KJDS_DATABASE_URL"] = previous
        target.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def store(engine: Engine) -> PostgresTeamAgentPersistence:
    return PostgresTeamAgentPersistence(engine)


def _registration(
    tag: str,
    *,
    idempotency_key: str | None = None,
    objective: str | None = None,
    max_attempts: int = 3,
    payload_extra: dict[str, object] | None = None,
) -> TeamAgentTaskRegistration:
    payload = {
        "objective": objective or f"read {tag}",
        "dependencies": [],
        **(payload_extra or {}),
    }
    return TeamAgentTaskRegistration(
        session_ref=f"session-{tag}",
        task_ref=f"task-{tag}",
        idempotency_key=idempotency_key or f"idem-{tag}",
        payload=payload,
        max_attempts=max_attempts,
    )


def test_postgres_two_workers_have_one_cas_winner_and_expiry_reclaims(
    store: PostgresTeamAgentPersistence,
) -> None:
    tag = uuid4().hex
    registration = _registration(tag)
    store.register_task(scope=SCOPE, task=registration, as_of=T0)
    barrier = Barrier(2)

    def claim(worker_id: str):
        barrier.wait(timeout=10)
        try:
            return store.claim_task(
                scope=SCOPE,
                session_ref=registration.session_ref,
                task_ref=registration.task_ref,
                worker_id=worker_id,
                lease_seconds=30,
                as_of=T0,
            )
        except TeamAgentPersistenceConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, ("worker-a", "worker-b")))

    winners = [item for item in outcomes if not isinstance(item, Exception)]
    conflicts = [item for item in outcomes if isinstance(item, Exception)]
    assert len(winners) == 1
    assert len(conflicts) == 1
    assert winners[0].attempt_count == 1
    assert winners[0].revision == 1

    reclaimed = store.claim_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-recovery",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=30),
    )
    assert reclaimed.claimed_by == "worker-recovery"
    assert reclaimed.attempt_count == 2
    assert reclaimed.revision == 2
    checkpoint = store.checkpoint(
        scope=SCOPE,
        session_ref=registration.session_ref,
    )
    assert [event["event_type"] for event in checkpoint["events"]] == [
        "registered",
        "claimed",
        "claimed",
    ]


def test_postgres_checkpointed_state_blocks_0100_downgrade(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-downgrade-{tag}"
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="checkpoint downgrade guard",
        owner_id="owner-a",
        authority_sha256="a" * 64,
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref=session_ref,
        thread_ref=f"{session_ref}:work",
        title="work",
        created_at=T0,
    )
    checkpoint_store = PostgresTeamAgentCheckpointStore(engine)
    checkpoint_store.save(
        coordinator=coordinator,
        session_ref=session_ref,
        expected_revision=None,
        as_of=T0,
    )
    config = _migration_config(engine)

    with pytest.raises(Exception, match="0100 downgrade blocked"):
        command.downgrade(config, "20260809_0098")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _single_migration_head(_migration_config(engine))
        )
        assert connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_checkpoints "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_checkpoint_events "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 1


def test_postgres_same_worker_concurrent_claim_is_idempotent(
    store: PostgresTeamAgentPersistence,
) -> None:
    tag = uuid4().hex
    registration = _registration(tag)
    store.register_task(scope=SCOPE, task=registration, as_of=T0)
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=10)
        return store.claim_task(
            scope=SCOPE,
            session_ref=registration.session_ref,
            task_ref=registration.task_ref,
            worker_id="worker-a",
            lease_seconds=30,
            as_of=T0,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: claim(), range(2)))

    assert outcomes[0].lease_ref == outcomes[1].lease_ref
    assert outcomes[0].revision == outcomes[1].revision == 1
    checkpoint = store.checkpoint(
        scope=SCOPE,
        session_ref=registration.session_ref,
    )
    assert [event["event_type"] for event in checkpoint["events"]] == [
        "registered",
        "claimed",
    ]


def test_postgres_same_worker_concurrent_claim_fences_conflicting_lease_ids(
    store: PostgresTeamAgentPersistence,
) -> None:
    tag = uuid4().hex
    registration = _registration(tag)
    store.register_task(scope=SCOPE, task=registration, as_of=T0)
    barrier = Barrier(2)

    def claim(marker: str):
        barrier.wait(timeout=10)
        try:
            return store.claim_task(
                scope=SCOPE,
                session_ref=registration.session_ref,
                task_ref=registration.task_ref,
                worker_id="worker-a",
                lease_seconds=30,
                lease_ref=f"lease-{tag}-{marker}",
                as_of=T0,
            )
        except TeamAgentPersistenceConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(claim, ("a", "b")))

    winners = [
        item for item in outcomes if not isinstance(item, Exception)
    ]
    conflicts = [item for item in outcomes if isinstance(item, Exception)]
    assert len(winners) == len(conflicts) == 1
    assert "lease identity conflicts" in str(conflicts[0])
    current = store.task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
    )
    assert current.lease_ref == winners[0].lease_ref
    checkpoint = store.checkpoint(
        scope=SCOPE,
        session_ref=registration.session_ref,
    )
    assert [event["event_type"] for event in checkpoint["events"]] == [
        "registered",
        "claimed",
    ]


def test_postgres_exact_scope_and_idempotency_conflicts_fail_closed(
    store: PostgresTeamAgentPersistence,
) -> None:
    tag = uuid4().hex
    registration = _registration(tag)
    created = store.register_task(scope=SCOPE, task=registration, as_of=T0)
    assert store.register_task(scope=SCOPE, task=registration, as_of=T0) == created

    with pytest.raises(TeamAgentPersistenceConflict, match="payload conflict"):
        store.register_task(
            scope=SCOPE,
            task=_registration(
                tag,
                idempotency_key=registration.idempotency_key,
                objective="drifted objective",
            ),
            as_of=T0,
        )
    with pytest.raises(TeamAgentTaskNotFound):
        store.claim_task(
            scope=OTHER_SCOPE,
            session_ref=registration.session_ref,
            task_ref=registration.task_ref,
            worker_id="worker-a",
            lease_seconds=30,
            as_of=T0,
        )


def test_postgres_heartbeat_release_and_event_append_are_atomic(
    store: PostgresTeamAgentPersistence,
) -> None:
    tag = uuid4().hex
    registration = _registration(tag)
    store.register_task(scope=SCOPE, task=registration, as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None
    heartbeat = store.heartbeat_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        extend_seconds=60,
        as_of=T0 + timedelta(seconds=5),
    )
    assert heartbeat.revision == 2
    with pytest.raises(TeamAgentPersistenceConflict):
        store.release_task(
            scope=SCOPE,
            session_ref=registration.session_ref,
            task_ref=registration.task_ref,
            worker_id="worker-b",
            lease_ref=claimed.lease_ref,
            as_of=T0 + timedelta(seconds=6),
        )
    released = store.release_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        as_of=T0 + timedelta(seconds=6),
    )
    assert released.revision == 3
    checkpoint = store.checkpoint(scope=SCOPE, session_ref=registration.session_ref)
    assert [event["event_type"] for event in checkpoint["events"]] == [
        "registered",
        "claimed",
        "heartbeat",
        "released",
    ]


def test_postgres_terminal_lifecycle_roundtrips_and_stale_lease_loses(
    store: PostgresTeamAgentPersistence,
) -> None:
    tag = uuid4().hex
    registration = _registration(tag, max_attempts=2)
    store.register_task(scope=SCOPE, task=registration, as_of=T0)
    first = store.claim_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert first.lease_ref is not None
    reclaimed = store.claim_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-b",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=30),
    )
    assert reclaimed.lease_ref is not None
    with pytest.raises(TeamAgentPersistenceConflict):
        store.complete_task(
            scope=SCOPE,
            session_ref=registration.session_ref,
            task_ref=registration.task_ref,
            worker_id="worker-a",
            lease_ref=first.lease_ref,
            result={"status": "stale"},
            as_of=T0 + timedelta(seconds=31),
        )

    completed = store.complete_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-b",
        lease_ref=reclaimed.lease_ref,
        result={"status": "ok", "items": 2},
        evidence_refs=("evd-1", "evd-2"),
        reviewer_id="reviewer-a",
        as_of=T0 + timedelta(seconds=31),
    )
    assert completed.state is DurableTaskState.COMPLETED
    assert completed.result == {"items": 2, "status": "ok"}
    assert completed.evidence_refs == ("evd-1", "evd-2")
    assert completed.reviewer_id == "reviewer-a"
    assert completed.completed_at == T0 + timedelta(seconds=31)

    checkpoint = store.checkpoint(scope=SCOPE, session_ref=registration.session_ref)
    task = checkpoint["tasks"][0]
    assert task["result"] == {"items": 2, "status": "ok"}
    assert task["evidence_refs"] == ["evd-1", "evd-2"]
    assert task["reviewer_id"] == "reviewer-a"
    assert [event["event_type"] for event in checkpoint["events"]] == [
        "registered",
        "claimed",
        "claimed",
        "completed",
    ]


@pytest.mark.parametrize("unsafe_result", UNSAFE_RESULTS)
def test_postgres_complete_rejects_unsafe_results_without_consuming_the_lease(
    store: PostgresTeamAgentPersistence,
    unsafe_result: dict[str, object],
) -> None:
    tag = uuid4().hex
    registration = _registration(tag)
    store.register_task(scope=SCOPE, task=registration, as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None

    with pytest.raises(TeamAgentResultContractError):
        store.complete_task(
            scope=SCOPE,
            session_ref=registration.session_ref,
            task_ref=registration.task_ref,
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            result=unsafe_result,
            as_of=T0 + timedelta(seconds=1),
        )

    persisted = store.task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
    )
    assert persisted.state is DurableTaskState.RUNNING
    assert persisted.revision == claimed.revision
    assert [
        event["event_type"]
        for event in store.checkpoint(
            scope=SCOPE,
            session_ref=registration.session_ref,
        )["events"]
    ] == ["registered", "claimed"]


def test_postgres_retry_pause_and_expiry_transitions_are_guarded(
    store: PostgresTeamAgentPersistence,
) -> None:
    retry_tag = uuid4().hex
    retry_registration = _registration(retry_tag, max_attempts=2)
    store.register_task(scope=SCOPE, task=retry_registration, as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref=retry_registration.session_ref,
        task_ref=retry_registration.task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None
    retry_wait = store.fail_task(
        scope=SCOPE,
        session_ref=retry_registration.session_ref,
        task_ref=retry_registration.task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        failure_code="provider_timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=T0 + timedelta(seconds=45),
        retry_after_seconds=30,
        as_of=T0 + timedelta(seconds=15),
    )
    assert retry_wait.state is DurableTaskState.RETRY_WAIT
    assert retry_wait.retry_after_seconds == 30.0
    retry_replay = store.fail_task(
        scope=SCOPE,
        session_ref=retry_registration.session_ref,
        task_ref=retry_registration.task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        failure_code="provider_timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=T0 + timedelta(seconds=45),
        retry_after_seconds=30,
        as_of=T0 + timedelta(seconds=16),
    )
    assert retry_replay == retry_wait
    with pytest.raises(TeamAgentPersistenceConflict):
        store.claim_task(
            scope=SCOPE,
            session_ref=retry_registration.session_ref,
            task_ref=retry_registration.task_ref,
            worker_id="worker-b",
            lease_seconds=30,
            as_of=T0 + timedelta(seconds=44),
        )
    resumed = store.claim_task(
        scope=SCOPE,
        session_ref=retry_registration.session_ref,
        task_ref=retry_registration.task_ref,
        worker_id="worker-b",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=45),
    )
    assert resumed.lease_ref is not None
    assert resumed.failure_code is None
    assert resumed.failure_kind is None
    assert resumed.result is None
    assert resumed.evidence_refs == ()
    assert resumed.reviewer_id is None
    completed = store.complete_task(
        scope=SCOPE,
        session_ref=retry_registration.session_ref,
        task_ref=retry_registration.task_ref,
        worker_id="worker-b",
        lease_ref=resumed.lease_ref,
        result={"status": "observed"},
        evidence_refs=("evd-retry",),
        reviewer_id="reviewer-retry",
        as_of=T0 + timedelta(seconds=46),
    )
    assert completed.failure_code is None
    assert completed.failure_kind is None
    assert completed.evidence_refs == ("evd-retry",)
    assert completed.completed_at == completed.updated_at
    retry_checkpoint = store.checkpoint(
        scope=SCOPE,
        session_ref=retry_registration.session_ref,
    )
    assert retry_checkpoint["events"][-1]["occurred_at"] == completed.updated_at.isoformat()

    paused_retry_tag = uuid4().hex
    paused_retry_registration = _registration(paused_retry_tag, max_attempts=2)
    store.register_task(scope=SCOPE, task=paused_retry_registration, as_of=T0)
    paused_retry_claim = store.claim_task(
        scope=SCOPE,
        session_ref=paused_retry_registration.session_ref,
        task_ref=paused_retry_registration.task_ref,
        worker_id="worker-pause-retry",
        lease_seconds=30,
        as_of=T0,
    )
    assert paused_retry_claim.lease_ref is not None
    paused_retry_wait = store.fail_task(
        scope=SCOPE,
        session_ref=paused_retry_registration.session_ref,
        task_ref=paused_retry_registration.task_ref,
        worker_id="worker-pause-retry",
        lease_ref=paused_retry_claim.lease_ref,
        failure_code="provider_429",
        failure_kind="rate_limited",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=T0 + timedelta(seconds=45),
        retry_after_seconds=30,
        as_of=T0 + timedelta(seconds=1),
    )
    paused_retry = store.pause_task(
        scope=SCOPE,
        session_ref=paused_retry_registration.session_ref,
        task_ref=paused_retry_registration.task_ref,
        reason="operator pause during retry backoff",
        as_of=T0 + timedelta(seconds=2),
    )
    assert paused_retry.state is DurableTaskState.PAUSED
    assert paused_retry.retry_wait_until is None
    assert paused_retry.retry_after_seconds is None
    assert paused_retry.paused_retry_wait_until == paused_retry_wait.retry_wait_until
    assert paused_retry.paused_retry_after_seconds == paused_retry_wait.retry_after_seconds
    resumed_retry = store.resume_task(
        scope=SCOPE,
        session_ref=paused_retry_registration.session_ref,
        task_ref=paused_retry_registration.task_ref,
        as_of=T0 + timedelta(seconds=3),
    )
    assert resumed_retry.state is DurableTaskState.RETRY_WAIT
    assert resumed_retry.retry_wait_until == paused_retry_wait.retry_wait_until
    assert resumed_retry.retry_after_seconds == paused_retry_wait.retry_after_seconds
    assert resumed_retry.paused_retry_wait_until is None
    assert resumed_retry.paused_retry_after_seconds is None

    paused_tag = uuid4().hex
    paused_registration = _registration(paused_tag)
    store.register_task(scope=SCOPE, task=paused_registration, as_of=T0)
    paused = store.pause_task(
        scope=SCOPE,
        session_ref=paused_registration.session_ref,
        task_ref=paused_registration.task_ref,
        reason="controlled_pause",
        as_of=T0,
    )
    assert paused.state is DurableTaskState.PAUSED
    assert paused.blocked_reason == "controlled_pause"
    resumed_paused = store.resume_task(
        scope=SCOPE,
        session_ref=paused_registration.session_ref,
        task_ref=paused_registration.task_ref,
        as_of=T0 + timedelta(seconds=1),
    )
    assert resumed_paused.state is DurableTaskState.QUEUED
    assert resumed_paused.blocked_reason is None

    expired_tag = uuid4().hex
    expired_registration = _registration(expired_tag, max_attempts=2)
    store.register_task(scope=SCOPE, task=expired_registration, as_of=T0)
    expiring = store.claim_task(
        scope=SCOPE,
        session_ref=expired_registration.session_ref,
        task_ref=expired_registration.task_ref,
        worker_id="worker-expire",
        lease_seconds=30,
        as_of=T0,
    )
    assert expiring.lease_ref is not None
    with pytest.raises(TeamAgentPersistenceConflict):
        store.expire_task(
            scope=SCOPE,
            session_ref=expired_registration.session_ref,
            task_ref=expired_registration.task_ref,
            as_of=T0 + timedelta(seconds=29),
        )
    expired = store.expire_task(
        scope=SCOPE,
        session_ref=expired_registration.session_ref,
        task_ref=expired_registration.task_ref,
        as_of=T0 + timedelta(seconds=30),
    )
    assert expired.state is DurableTaskState.EXPIRED
    assert expired.blocked_reason == "lease_expired"

    blocked_tag = uuid4().hex
    blocked_registration = _registration(blocked_tag, max_attempts=1)
    store.register_task(scope=SCOPE, task=blocked_registration, as_of=T0)
    blocked_running = store.claim_task(
        scope=SCOPE,
        session_ref=blocked_registration.session_ref,
        task_ref=blocked_registration.task_ref,
        worker_id="worker-block",
        lease_seconds=30,
        as_of=T0,
    )
    assert blocked_running.lease_ref is not None
    blocked = store.expire_task(
        scope=SCOPE,
        session_ref=blocked_registration.session_ref,
        task_ref=blocked_registration.task_ref,
        as_of=T0 + timedelta(seconds=30),
    )
    assert blocked.state is DurableTaskState.BLOCKED
    assert blocked.blocked_reason == "retry_budget_exhausted"

    revoked_tag = uuid4().hex
    revoked_registration = _registration(revoked_tag)
    store.register_task(scope=SCOPE, task=revoked_registration, as_of=T0)
    revoking = store.claim_task(
        scope=SCOPE,
        session_ref=revoked_registration.session_ref,
        task_ref=revoked_registration.task_ref,
        worker_id="worker-revoked",
        lease_seconds=30,
        as_of=T0,
    )
    assert revoking.lease_ref is not None
    revoked = store.revoke_task(
        scope=SCOPE,
        session_ref=revoked_registration.session_ref,
        task_ref=revoked_registration.task_ref,
        reason="session kill switch",
        as_of=T0 + timedelta(seconds=1),
    )
    assert revoked.state is DurableTaskState.EXPIRED
    assert revoked.blocked_reason == "session kill switch"


def test_postgres_paused_retry_schedule_blocks_0103_downgrade(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    registration = _registration(tag, max_attempts=2)
    store = PostgresTeamAgentPersistence(engine)
    store.register_task(scope=SCOPE, task=registration, as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-downgrade",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None
    store.fail_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-downgrade",
        lease_ref=claimed.lease_ref,
        failure_code="provider_429",
        failure_kind="rate_limited",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=T0 + timedelta(seconds=45),
        retry_after_seconds=30,
        as_of=T0 + timedelta(seconds=1),
    )
    store.pause_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        reason="retain retry schedule",
        as_of=T0 + timedelta(seconds=2),
    )

    with pytest.raises(Exception, match="0103 downgrade blocked"):
        command.downgrade(_migration_config(engine), "20260819_0102")

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            _single_migration_head(_migration_config(engine))
        )


def test_postgres_retry_wait_rejects_an_exhausted_attempt_budget(
    store: PostgresTeamAgentPersistence,
) -> None:
    tag = uuid4().hex
    registration = _registration(tag, max_attempts=1)
    store.register_task(scope=SCOPE, task=registration, as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None

    with pytest.raises(TeamAgentPersistenceConflict, match="retry budget"):
        store.fail_task(
            scope=SCOPE,
            session_ref=registration.session_ref,
            task_ref=registration.task_ref,
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            failure_code="provider_timeout",
            failure_kind="timeout",
            next_state=DurableTaskState.RETRY_WAIT,
            retry_wait_until=T0 + timedelta(seconds=20),
            as_of=T0 + timedelta(seconds=1),
        )

    still_running = store.task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
    )
    assert still_running.state is DurableTaskState.RUNNING
    assert still_running.revision == claimed.revision
    failed = store.fail_task(
        scope=SCOPE,
        session_ref=registration.session_ref,
        task_ref=registration.task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        failure_code="provider_timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.FAILED,
        as_of=T0 + timedelta(seconds=1),
    )
    assert failed.state is DurableTaskState.FAILED


def _coordinator(tag: str) -> TeamAgentCoordinator:
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref=f"session-checkpoint-{tag}",
        scope=SCOPE,
        objective="durable checkpoint",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        created_at=T0,
    )
    return coordinator


def test_postgres_checkpoint_cas_has_one_winner_and_restores(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-checkpoint-{tag}"
    coordinator = _coordinator(tag)
    store = PostgresTeamAgentCheckpointStore(engine)
    initial = store.save(
        coordinator=coordinator,
        session_ref=session_ref,
        expected_revision=None,
        as_of=T0,
    )
    coordinator.pause(
        session_ref=session_ref,
        reason="restart test",
        actor_id="operator-a",
        as_of=T0 + timedelta(seconds=1),
    )
    barrier = Barrier(2)

    def save():
        barrier.wait(timeout=10)
        try:
            return store.save(
                coordinator=coordinator,
                session_ref=session_ref,
                expected_revision=initial.revision,
                as_of=T0 + timedelta(seconds=1),
            )
        except TeamAgentCheckpointConflict as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: save(), range(2)))
    winners = [item for item in outcomes if not isinstance(item, Exception)]
    conflicts = [item for item in outcomes if isinstance(item, Exception)]
    assert len(winners) == len(conflicts) == 1
    hydrated = store.restore(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
    )
    assert hydrated.durable.revision == 1
    assert hydrated.coordinator.session(session_ref).state.value == "paused"
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_checkpoint_events "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 2


def test_postgres_checkpoint_tamper_fails_restore(engine: Engine) -> None:
    tag = uuid4().hex
    session_ref = f"session-checkpoint-{tag}"
    store = PostgresTeamAgentCheckpointStore(engine)
    store.save(
        coordinator=_coordinator(tag),
        session_ref=session_ref,
        expected_revision=None,
        as_of=T0,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE team_agent_orchestration_checkpoints "
                "SET checkpoint_json = checkpoint_json || "
                "jsonb_build_object('tampered', true) "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        )
    with pytest.raises(
        TeamAgentCheckpointIntegrityError,
        match="restore validation|metadata mismatch",
    ):
        store.restore(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
        )


def test_postgres_checkpoint_history_gap_fails_restore(engine: Engine) -> None:
    tag = uuid4().hex
    session_ref = f"session-checkpoint-history-{tag}"
    coordinator = _coordinator(f"history-{tag}")
    store = PostgresTeamAgentCheckpointStore(engine)
    initial = store.save(
        coordinator=coordinator,
        session_ref=session_ref,
        expected_revision=None,
        as_of=T0,
    )
    coordinator.pause(
        session_ref=session_ref,
        reason="history test",
        actor_id="operator-a",
        as_of=T0 + timedelta(seconds=1),
    )
    store.save(
        coordinator=coordinator,
        session_ref=session_ref,
        expected_revision=initial.revision,
        as_of=T0 + timedelta(seconds=1),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE team_agent_orchestration_checkpoint_events "
                "DISABLE TRIGGER trg_team_agent_checkpoint_event_immutable"
            )
        )
        connection.execute(
            text(
                "DELETE FROM team_agent_orchestration_checkpoint_events "
                "WHERE session_ref=:session_ref AND checkpoint_revision=0"
            ),
            {"session_ref": session_ref},
        )
        connection.execute(
            text(
                "ALTER TABLE team_agent_orchestration_checkpoint_events "
                "ENABLE TRIGGER trg_team_agent_checkpoint_event_immutable"
            )
        )
    with pytest.raises(TeamAgentCheckpointIntegrityError, match="history"):
        store.restore(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
        )


def test_postgres_checkpoint_empty_history_fails_restore(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-checkpoint-empty-history-{tag}"
    coordinator = _coordinator(f"empty-history-{tag}")
    store = PostgresTeamAgentCheckpointStore(engine)
    store.save(
        coordinator=coordinator,
        session_ref=session_ref,
        expected_revision=None,
        as_of=T0,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE team_agent_orchestration_checkpoint_events "
                "DISABLE TRIGGER trg_team_agent_checkpoint_event_immutable"
            )
        )
        connection.execute(
            text(
                "DELETE FROM team_agent_orchestration_checkpoint_events "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        )
        connection.execute(
            text(
                "ALTER TABLE team_agent_orchestration_checkpoint_events "
                "ENABLE TRIGGER trg_team_agent_checkpoint_event_immutable"
            )
        )
    with pytest.raises(TeamAgentCheckpointIntegrityError, match="history"):
        store.restore(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
        )


def test_postgres_runtime_mutation_rolls_back_task_when_sidecar_save_fails(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-rollback-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="atomic rollback",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    original_save = PostgresTeamAgentCheckpointStore.save

    def fail_existing_save(self, **kwargs):
        if kwargs.get("expected_revision") is not None:
            raise TeamAgentCheckpointConflict("injected sidecar save failure")
        return original_save(self, **kwargs)

    monkeypatch.setattr(
        PostgresTeamAgentCheckpointStore,
        "save",
        fail_existing_save,
    )
    with pytest.raises(TeamAgentCheckpointConflict, match="injected"):
        runtime.submit_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=f"task-{tag}",
            thread_ref=f"{session_ref}:root",
            agent_id="reader-a",
            role="catalog_reader",
            objective="must roll back",
            idempotency_key=f"idem-{tag}",
            as_of=T0,
        )

    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_tasks "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 0
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_checkpoints "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 0


def test_postgres_runtime_roundtrips_one_transaction_task_lifecycle(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-{tag}"
    task_ref = f"task-runtime-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="transactional lifecycle",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="read current catalog",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    claimed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None
    heartbeat = runtime.heartbeat_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        extend_seconds=30,
        as_of=T0 + timedelta(seconds=1),
    )
    completed = runtime.complete_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_ref=heartbeat.lease_ref or "missing",
        result={"status": "observed"},
        evidence_refs=("ev-runtime",),
        reviewer_id="reviewer-a",
        as_of=T0 + timedelta(seconds=2),
    )
    restored = runtime.restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=2),
    )

    assert completed.state.value == "completed"
    assert restored.task(task_ref).result == {"status": "observed"}
    with engine.connect() as connection:
        task_revision = connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_tasks "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        )
        checkpoint_revision = connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_checkpoints "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        )
    assert task_revision == 3
    assert checkpoint_revision == 4
    with engine.connect() as connection:
        outbox_payload = connection.scalar(
            text(
                "SELECT payload_json FROM outbox_events "
                "WHERE event_type='team_agent.terminal_observation.ready' "
                "AND aggregate_id=:aggregate_id"
            ),
            {"aggregate_id": f"team-agent:{session_ref}:{task_ref}"},
        )
    assert outbox_payload["contract_id"] == "team-agent-terminal-observation-outbox@1"
    assert outbox_payload["session_ref"] == session_ref
    assert outbox_payload["task_ref"] == task_ref
    assert "result" not in outbox_payload


def test_postgres_runtime_release_roundtrips_and_fences_old_lease(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-release-{tag}"
    task_ref = f"task-runtime-release-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="durable lease release",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="release active work",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    claimed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None
    released = runtime.release_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        as_of=T0 + timedelta(seconds=1),
    )

    assert released.state.value == "queued"
    assert released.lease_ref is None
    with pytest.raises((OrchestrationError, TeamAgentPersistenceConflict)):
        runtime.heartbeat_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=task_ref,
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            extend_seconds=30,
            as_of=T0 + timedelta(seconds=2),
        )
    restored = PostgresTeamAgentRuntime(engine).restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=2),
    )
    assert restored.task(task_ref).state.value == "queued"
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_tasks "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ) == 2
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_checkpoints "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 3


def test_postgres_two_runtime_instances_emit_one_terminal_transition(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-terminal-race-{tag}"
    task_ref = f"task-runtime-terminal-race-{tag}"
    first_runtime = PostgresTeamAgentRuntime(engine)
    second_runtime = PostgresTeamAgentRuntime(engine)
    first_runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="single terminal winner",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    first_runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="concurrent terminal transition",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    claimed = first_runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None
    barrier = Barrier(2)

    def complete(runtime: PostgresTeamAgentRuntime, marker: str):
        barrier.wait()
        try:
            runtime.complete_task(
                scope=SCOPE,
                session_ref=session_ref,
                authority_sha256="a" * 64,
                task_ref=task_ref,
                worker_id="worker-a",
                lease_ref=claimed.lease_ref or "missing",
                result={"winner": marker},
                as_of=T0 + timedelta(seconds=1),
            )
        except (OrchestrationError, TeamAgentPersistenceConflict) as exc:
            return "conflict", type(exc).__name__, marker
        return "completed", "", marker

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            future.result()
            for future in (
                executor.submit(complete, first_runtime, "a"),
                executor.submit(complete, second_runtime, "b"),
            )
        )

    assert sorted(item[0] for item in outcomes) == ["completed", "conflict"]
    winner = next(item[2] for item in outcomes if item[0] == "completed")
    restored = PostgresTeamAgentRuntime(engine).restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=1),
    )
    assert restored.task(task_ref).result == {"winner": winner}
    with engine.connect() as connection:
        events = connection.execute(
            text(
                "SELECT task_revision, event_type "
                "FROM team_agent_orchestration_events "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref "
                "ORDER BY task_revision"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ).all()
    assert [row.task_revision for row in events] == list(range(len(events)))
    assert [row.event_type for row in events].count("completed") == 1


def test_postgres_spawned_workers_and_restart_recover_after_process_loss(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-process-race-{tag}"
    task_ref = f"task-runtime-process-race-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="multi-process claim and restart recovery",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="survive winner process loss",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )

    context = get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    outcomes = context.Queue()
    database_url = engine.url.render_as_string(hide_password=False)
    processes = [
        context.Process(
            target=_claim_team_agent_in_spawned_process,
            args=(
                database_url,
                (SCOPE.tenant_ref, SCOPE.entity_ref, SCOPE.store_ref),
                session_ref,
                task_ref,
                worker_id,
                T0.isoformat(),
                ready,
                start,
                outcomes,
            ),
        )
        for worker_id in ("worker-process-a", "worker-process-b")
    ]
    for process in processes:
        process.start()
    assert {ready.get(timeout=20) for _ in processes} == {
        "worker-process-a",
        "worker-process-b",
    }
    start.set()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0

    process_outcomes = [outcomes.get(timeout=10) for _ in processes]
    assert sorted(item[0] for item in process_outcomes) == ["conflict", "winner"]
    winner = next(item[1] for item in process_outcomes if item[0] == "winner")

    restarted = PostgresTeamAgentRuntime(engine)
    active = restarted.restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=1),
    ).task(task_ref)
    assert active.state.value == "running"
    assert active.claimed_by == winner

    recovered = restarted.recover_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=31),
    ).task(task_ref)
    assert recovered.state.value == "expired"
    assert recovered.claimed_by is None
    assert PostgresTeamAgentPersistence(engine).task(
        scope=SCOPE,
        session_ref=session_ref,
        task_ref=task_ref,
    ).state is DurableTaskState.EXPIRED
    with engine.connect() as connection:
        event_types = connection.scalars(
            text(
                "SELECT event_type FROM team_agent_orchestration_events "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref "
                "ORDER BY task_revision"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ).all()
    assert event_types.count("claimed") == 1
    assert event_types.count("expired") == 1


def test_postgres_spawned_worker_crash_after_commit_before_ack_is_idempotent(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-crash-ack-{tag}"
    task_ref = f"task-runtime-crash-ack-{tag}"
    worker_id = f"worker-crash-{tag}"
    lease_ref = f"lease-crash-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="claim survives response loss",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="commit before acknowledgement is lost",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )

    context = get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    process = context.Process(
        target=_claim_and_crash_after_commit_before_ack,
        args=(
            engine.url.render_as_string(hide_password=False),
            (SCOPE.tenant_ref, SCOPE.entity_ref, SCOPE.store_ref),
            session_ref,
            task_ref,
            worker_id,
            lease_ref,
            T0.isoformat(),
            ready,
            start,
        ),
    )
    process.start()
    assert ready.get(timeout=20) == worker_id
    start.set()
    process.join(timeout=30)
    assert process.exitcode == 91

    replayed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id=worker_id,
        lease_seconds=30,
        lease_id=lease_ref,
        as_of=T0 + timedelta(seconds=1),
    )
    assert replayed.lease_ref == lease_ref
    assert replayed.claimed_by == worker_id
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_tasks "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ) == 1
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_checkpoints "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 2
        assert connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_events "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref "
                "AND event_type='claimed'"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ) == 1

    restored = PostgresTeamAgentRuntime(engine).restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=1),
    )
    assert restored.task(task_ref).lease_ref == lease_ref


def test_postgres_completed_response_loss_replay_converges_without_new_event(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-complete-ack-{tag}"
    task_ref = f"task-runtime-complete-ack-{tag}"
    worker_id = f"worker-complete-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="completion survives response loss",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="commit terminal result before acknowledgement is lost",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    claimed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id=worker_id,
        lease_seconds=30,
        lease_id=f"lease-complete-{tag}",
        as_of=T0 + timedelta(seconds=1),
    )
    assert claimed.lease_ref is not None

    context = get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    process = context.Process(
        target=_complete_and_crash_after_commit_before_ack,
        args=(
            engine.url.render_as_string(hide_password=False),
            (SCOPE.tenant_ref, SCOPE.entity_ref, SCOPE.store_ref),
            session_ref,
            task_ref,
            worker_id,
            claimed.lease_ref,
            (T0 + timedelta(seconds=2)).isoformat(),
            ready,
            start,
        ),
    )
    process.start()
    assert ready.get(timeout=20) == worker_id
    start.set()
    process.join(timeout=30)
    assert process.exitcode == 93

    replay_runtime = PostgresTeamAgentRuntime(engine)
    replayed = replay_runtime.complete_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id=worker_id,
        lease_ref=claimed.lease_ref,
        result={"status": "observed", "items": 2},
        evidence_refs=("ev-response-loss",),
        reviewer_id="reviewer-a",
        cost_units=3,
        as_of=T0 + timedelta(seconds=3),
    )
    assert replayed.state.value == "completed"
    assert replayed.result == {"items": 2, "status": "observed"}
    with engine.connect() as connection:
        task_revision = connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_tasks "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        )
        checkpoint_revision = connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_checkpoints "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        )
        completed_events = connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_events "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref "
                "AND event_type='completed'"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        )
    assert task_revision == 2
    assert checkpoint_revision == 3
    assert completed_events == 1
    with pytest.raises(
        (OrchestrationError, TeamAgentPersistenceConflict),
        match="completion replay conflict",
    ):
        replay_runtime.complete_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=task_ref,
            worker_id=worker_id,
            lease_ref=claimed.lease_ref,
            result={"status": "different"},
            evidence_refs=("ev-response-loss",),
            reviewer_id="reviewer-a",
            cost_units=3,
            as_of=T0 + timedelta(seconds=3),
        )
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_events "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref "
                "AND event_type='completed'"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ) == 1


def test_postgres_failed_response_loss_replay_converges_without_new_event(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-failed-ack-{tag}"
    task_ref = f"task-runtime-failed-ack-{tag}"
    worker_id = f"worker-failed-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="failure survives response loss",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="commit failed terminal state before acknowledgement is lost",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    claimed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id=worker_id,
        lease_seconds=30,
        lease_id=f"lease-failed-{tag}",
        as_of=T0 + timedelta(seconds=1),
    )
    assert claimed.lease_ref is not None
    failed = runtime.fail_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id=worker_id,
        lease_ref=claimed.lease_ref,
        failure_code="business_validation_failed",
        status_code=400,
        as_of=T0 + timedelta(seconds=2),
    )
    assert failed.state.value == "failed"
    replayed = PostgresTeamAgentRuntime(engine).fail_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id=worker_id,
        lease_ref=claimed.lease_ref,
        failure_code="business_validation_failed",
        status_code=400,
        as_of=T0 + timedelta(seconds=3),
    )
    assert replayed == failed
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_tasks "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ) == 2
        assert connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_events "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref "
                "AND event_type='failed'"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ) == 1
    with pytest.raises(OrchestrationError, match="failure replay conflict"):
        PostgresTeamAgentRuntime(engine).fail_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=task_ref,
            worker_id=worker_id,
            lease_ref=claimed.lease_ref,
            failure_code="different_failure",
            status_code=400,
            as_of=T0 + timedelta(seconds=3),
        )


def test_postgres_runtime_active_claim_replay_is_a_noop(engine: Engine) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-claim-replay-{tag}"
    task_ref = f"task-runtime-claim-replay-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="idempotent active claim",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="read current catalog",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    first = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        lease_id=f"lease-{tag}",
        as_of=T0,
    )
    replay = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        lease_id=f"lease-{tag}",
        as_of=T0 + timedelta(seconds=1),
    )

    assert replay == first
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_tasks "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ) == 1
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_checkpoints "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 2


def test_postgres_runtime_handoff_lineage_reconciles_after_restart(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-handoff-{tag}"
    task_ref = f"task-runtime-handoff-{tag}"
    source_thread_ref = f"{session_ref}:root"
    target_thread_ref = f"{session_ref}:review"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="durable handoff lineage",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=source_thread_ref,
        agent_id="reader-a",
        role="catalog_reader",
        objective="produce reviewed evidence",
        idempotency_key=f"idem-{tag}",
        trace_id=f"trace-{tag}",
        evidence_required=True,
        as_of=T0,
    )
    claimed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        as_of=T0,
    )
    runtime.complete_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref or "missing",
        result={"status": "observed"},
        evidence_refs=("ev-runtime",),
        as_of=T0 + timedelta(seconds=1),
    )
    runtime.fork_thread(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        thread_ref=target_thread_ref,
        title="independent review",
        parent_thread_ref=source_thread_ref,
        parent_task_ref=task_ref,
        as_of=T0 + timedelta(seconds=2),
    )
    handoff = runtime.handoff_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        source_task_ref=task_ref,
        source_thread_ref=source_thread_ref,
        target_thread_ref=target_thread_ref,
        target_role="independent_reviewer",
        input_evidence_refs=("ev-runtime",),
        acceptance_contract={"decision": "accept_or_reject"},
        trace_id=f"trace-{tag}",
        as_of=T0 + timedelta(seconds=3),
    )
    replayed_handoff = runtime.handoff_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        source_task_ref=task_ref,
        source_thread_ref=source_thread_ref,
        target_thread_ref=target_thread_ref,
        target_role="independent_reviewer",
        input_evidence_refs=("ev-runtime",),
        acceptance_contract={"decision": "accept_or_reject"},
        trace_id=f"trace-{tag}",
        as_of=T0 + timedelta(seconds=4),
    )
    assert replayed_handoff == handoff

    restored = runtime.restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=3),
    )
    restored_handoff = restored.handoffs(session_ref=session_ref)[0]
    restored_threads = {
        item["thread_ref"]: item
        for item in restored.snapshot(session_ref=session_ref)["threads"]
    }

    assert restored_handoff == handoff
    assert restored.task(task_ref).handoff_ref == handoff.handoff_ref
    assert restored_threads[target_thread_ref]["handoff_ref"] == handoff.handoff_ref
    assert restored_threads[target_thread_ref]["target_role"] == "independent_reviewer"
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_tasks "
                "WHERE session_ref=:session_ref AND task_ref=:task_ref"
            ),
            {"session_ref": session_ref, "task_ref": task_ref},
        ) == 2
        assert connection.scalar(
            text(
                "SELECT revision FROM team_agent_orchestration_checkpoints "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 5


def test_postgres_runtime_session_controls_reconcile_after_restart(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-controls-{tag}"
    task_ref = f"task-runtime-controls-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="durable session controls",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="read current catalog",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    runtime.pause(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        reason="operator pause",
        actor_id="operator-a",
        as_of=T0 + timedelta(seconds=1),
    )
    assert runtime.restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=1),
    ).task(task_ref).state.value == "paused"
    runtime.resume(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        reason="operator resume",
        actor_id="operator-a",
        as_of=T0 + timedelta(seconds=2),
    )
    claimed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=3),
    )
    assert claimed.state.value == "running"
    runtime.engage_kill_switch(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        reason="revoke all work",
        actor_id="operator-a",
        as_of=T0 + timedelta(seconds=4),
    )
    restored = runtime.restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=4),
    )
    assert restored.session(session_ref).state.value == "closed"
    assert restored.task(task_ref).state.value == "expired"
    assert PostgresTeamAgentPersistence(engine).task(
        scope=SCOPE,
        session_ref=session_ref,
        task_ref=task_ref,
    ).state is DurableTaskState.EXPIRED


def test_postgres_runtime_pause_preserves_retry_schedule_across_restart(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-retry-pause-{tag}"
    task_ref = f"task-runtime-retry-pause-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="preserve bounded retry through operator pause",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="read current catalog",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    claimed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=1),
    )
    assert claimed.lease_ref is not None
    retry_wait = runtime.fail_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        failure_code="provider_429",
        status_code=429,
        retry_after_seconds=30,
        as_of=T0 + timedelta(seconds=2),
    )
    assert retry_wait.state.value == "retry_wait"
    assert retry_wait.retry_wait_until is not None
    runtime.pause(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        reason="operator pause during provider backoff",
        actor_id="operator-a",
        as_of=T0 + timedelta(seconds=3),
    )
    restarted = PostgresTeamAgentRuntime(engine)
    paused = restarted.restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=3),
    ).task(task_ref)
    assert paused.state.value == "paused"
    assert paused.retry_wait_until == retry_wait.retry_wait_until
    restarted.resume(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        reason="operator resume",
        actor_id="operator-a",
        as_of=T0 + timedelta(seconds=4),
    )
    resumed = PostgresTeamAgentRuntime(engine).restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=4),
    ).task(task_ref)
    assert resumed.state.value == "retry_wait"
    assert resumed.retry_wait_until == retry_wait.retry_wait_until


def test_durable_kill_switch_fences_stale_replica_claim_and_complete(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-kill-fence-{tag}"
    running_ref = f"task-running-{tag}"
    queued_ref = f"task-queued-{tag}"
    controller = PostgresTeamAgentRuntime(engine)
    stale_replica = PostgresTeamAgentRuntime(engine)
    controller.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="durable kill fence",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    for task_ref in (running_ref, queued_ref):
        controller.submit_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=task_ref,
            thread_ref=f"{session_ref}:root",
            agent_id="reader-a",
            role="catalog_reader",
            objective=f"control {task_ref}",
            idempotency_key=f"idem-{task_ref}",
            as_of=T0,
        )
    claimed = controller.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=running_ref,
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None
    stale_replica.restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0,
    )

    controller.engage_kill_switch(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        reason="stop all work",
        actor_id="operator-a",
        as_of=T0 + timedelta(seconds=1),
    )

    with pytest.raises((OrchestrationError, TeamAgentPersistenceConflict)):
        stale_replica.claim_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=queued_ref,
            worker_id="worker-b",
            lease_seconds=30,
            as_of=T0 + timedelta(seconds=2),
        )
    with pytest.raises((OrchestrationError, TeamAgentPersistenceConflict)):
        stale_replica.complete_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=running_ref,
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            result={"status": "stale"},
            as_of=T0 + timedelta(seconds=2),
        )

    restarted = PostgresTeamAgentRuntime(engine).restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=2),
    )
    assert restarted.session(session_ref).kill_switch_engaged is True
    assert restarted.task(queued_ref).state.value == "paused"
    assert restarted.task(running_ref).state.value == "expired"


def test_postgres_runtime_atomically_recovers_expired_lease_before_stale_heartbeat(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-expiry-{tag}"
    task_ref = f"task-runtime-expiry-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="durable expired lease recovery",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="recover expired lease",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )
    claimed = runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=2,
        as_of=T0,
    )
    assert claimed.lease_ref is not None

    with pytest.raises(OrchestrationError, match="running task"):
        runtime.heartbeat_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=task_ref,
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            extend_seconds=30,
            as_of=T0 + timedelta(seconds=2),
        )

    restarted = PostgresTeamAgentRuntime(engine).restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=2),
    )
    projected = restarted.task(task_ref)
    durable = PostgresTeamAgentPersistence(engine).task(
        scope=SCOPE,
        session_ref=session_ref,
        task_ref=task_ref,
    )
    assert projected.state.value == "expired"
    assert durable.state is DurableTaskState.EXPIRED
    assert projected.lease_ref is durable.lease_ref is None
    assert projected.expired_at == durable.expired_at == T0 + timedelta(seconds=2)


def test_postgres_runtime_claim_commits_queued_time_budget_terminal(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-budget-{tag}"
    task_ref = f"task-runtime-budget-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="durable time budget",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        time_budget_seconds=1,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="close at the time boundary",
        idempotency_key=f"idem-{tag}",
        as_of=T0,
    )

    with pytest.raises(OrchestrationError, match="time budget exhausted"):
        runtime.claim_task(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            task_ref=task_ref,
            worker_id="worker-a",
            lease_seconds=30,
            as_of=T0 + timedelta(seconds=1),
        )

    durable = PostgresTeamAgentPersistence(engine).task(
        scope=SCOPE,
        session_ref=session_ref,
        task_ref=task_ref,
    )
    restored = runtime.restore_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=1),
    ).task(task_ref)
    assert durable.state is DurableTaskState.BLOCKED
    assert restored.state.value == "blocked"
    assert durable.blocked_reason == restored.blocked_reason == "time_budget_exhausted"


def test_postgres_runtime_expiry_blocks_exhausted_attempt_without_expired_at(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-runtime-expiry-blocked-{tag}"
    task_ref = f"task-runtime-expiry-blocked-{tag}"
    runtime = PostgresTeamAgentRuntime(engine)
    runtime.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="bounded expired lease recovery",
        owner_id="operator-a",
        authority_sha256="a" * 64,
        as_of=T0,
    )
    runtime.submit_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="block exhausted lease",
        idempotency_key=f"idem-{tag}",
        max_attempts=1,
        as_of=T0,
    )
    runtime.claim_task(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        task_ref=task_ref,
        worker_id="worker-a",
        lease_seconds=2,
        as_of=T0,
    )

    with pytest.raises(TeamAgentDurableRecoveryError, match="expired durable lease"):
        runtime.restore_session(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            as_of=T0 + timedelta(seconds=2),
        )
    before_recovery = PostgresTeamAgentPersistence(engine).task(
        scope=SCOPE,
        session_ref=session_ref,
        task_ref=task_ref,
    )
    assert before_recovery.state is DurableTaskState.RUNNING

    restored = runtime.recover_session(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
        as_of=T0 + timedelta(seconds=2),
    )
    projected = restored.task(task_ref)
    durable = PostgresTeamAgentPersistence(engine).task(
        scope=SCOPE,
        session_ref=session_ref,
        task_ref=task_ref,
    )
    assert projected.state.value == "blocked"
    assert durable.state is DurableTaskState.BLOCKED
    assert projected.blocked_reason == durable.blocked_reason == "retry_budget_exhausted"
    assert projected.expired_at is durable.expired_at is None


def test_postgres_harness_observation_replay_converges_across_workers(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    project_id = f"project-publish-{tag}"
    verifier_id = f"verifier-publish-{tag}"
    now = T0 + timedelta(minutes=1)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO graph_projects "
                "(id, tenant_ref, entity_ref, store_ref, title, lifecycle, "
                "baseline_sha256, goal_contract_sha256, created_at) VALUES "
                "(:id, :tenant, :entity, :store, :title, 'active', "
                ":baseline, :goal, :created_at)"
            ),
            {
                "id": project_id,
                "tenant": "tenant-publish",
                "entity": "entity-publish",
                "store": "store-publish",
                "title": "concurrent TeamAgent publication",
                "baseline": "b" * 64,
                "goal": "c" * 64,
                "created_at": now,
            },
        )
    service = AgentHarnessService(engine)
    service.register_verifier(
        {
            "id": verifier_id,
            "version": "1",
            "source_type": "process_log",
            "authority": "external_verifier",
            "success_states": ["passed"],
            "freshness_seconds": 3600,
        }
    )
    principal = Principal(
        actor_id="monitor-publish",
        roles=frozenset({"monitor"}),
        tenant_ref="tenant-publish",
        store_refs=frozenset({"store-publish"}),
    )
    payload = {
        "project_id": project_id,
        "verifier_id": verifier_id,
        "verifier_version": "1",
        "source": "postgres-concurrency-contract",
        "store_ref": "store-publish",
        "scope": {
            "tenant_ref": "tenant-publish",
            "entity_ref": "entity-publish",
            "store_ref": "store-publish",
        },
        "state": "passed",
        "summary": "one terminal observation",
        "input_sha256": "d" * 64,
        "artifact_ref": f"team-agent://{tag}/task/observation",
        "observed_at": now.isoformat(),
    }

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: service.record_observation(
                    payload,
                    principal=principal,
                ),
                range(4),
            )
        )

    assert results == [results[0]] * 4
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM harness_observations "
                "WHERE project_id=:project_id"
            ),
            {"project_id": project_id},
        ) == 1


def test_task_mutation_and_checkpoint_share_one_commit_boundary(engine: Engine) -> None:
    tag = uuid4().hex
    session_ref = f"session-checkpoint-{tag}"
    task_ref = f"task-checkpoint-{tag}"
    coordinator = _coordinator(tag)
    coordinator.submit_task(
        session_ref=session_ref,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:root",
        agent_id="reader-a",
        role="catalog_reader",
        objective="read current catalog",
        idempotency_key=f"idem-{tag}",
        created_at=T0,
    )
    registration = TeamAgentTaskRegistration(
        session_ref=session_ref,
        task_ref=task_ref,
        idempotency_key=f"idem-{tag}",
        payload=team_agent_durable_task_payload(coordinator.task(task_ref)),
    )

    with engine.begin() as connection:
        tasks = PostgresTeamAgentPersistence(engine, connection=connection)
        checkpoints = PostgresTeamAgentCheckpointStore(engine, connection=connection)
        registered = tasks.register_task(scope=SCOPE, task=registration, as_of=T0)
        coordinator.bind_durable_task_revision(
            task_ref=task_ref,
            revision=registered.revision,
            request_sha256=registered.request_sha256,
        )
        checkpoints.save(
            coordinator=coordinator,
            session_ref=session_ref,
            expected_revision=None,
            as_of=T0,
        )

    class RollbackProbe(RuntimeError):
        pass

    rolled_back = TeamAgentCoordinator.restore(
        coordinator.checkpoint(session_ref=session_ref),
        scope=SCOPE,
    )
    with pytest.raises(RollbackProbe), engine.begin() as connection:
        tasks = PostgresTeamAgentPersistence(engine, connection=connection)
        checkpoints = PostgresTeamAgentCheckpointStore(
            engine,
            connection=connection,
        )
        locked = checkpoints.restore(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            for_update=True,
        )
        claimed = tasks.claim_task(
            scope=SCOPE,
            session_ref=session_ref,
            task_ref=task_ref,
            worker_id="reader-a",
            lease_seconds=30,
            as_of=T0 + timedelta(seconds=1),
        )
        rolled_back.claim_task(
            task_ref=task_ref,
            worker_id="reader-a",
            lease_seconds=30,
            lease_id=claimed.lease_ref,
            as_of=T0 + timedelta(seconds=1),
        )
        rolled_back.bind_durable_task_revision(
            task_ref=task_ref,
            revision=claimed.revision,
        )
        checkpoints.save(
            coordinator=rolled_back,
            session_ref=session_ref,
            expected_revision=locked.durable.revision,
            as_of=T0 + timedelta(seconds=1),
        )
        raise RollbackProbe

    durable_after_rollback = PostgresTeamAgentPersistence(engine).task(
        scope=SCOPE,
        session_ref=session_ref,
        task_ref=task_ref,
    )
    checkpoint_after_rollback = PostgresTeamAgentCheckpointStore(engine).restore(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
    )
    assert durable_after_rollback.state is DurableTaskState.QUEUED
    assert durable_after_rollback.revision == 0
    assert checkpoint_after_rollback.durable.revision == 0
    assert checkpoint_after_rollback.coordinator.task(task_ref).state.value == "queued"
    durable_checkpoint = PostgresTeamAgentPersistence(engine).checkpoint(
        scope=SCOPE,
        session_ref=session_ref,
    )
    assert [event["event_type"] for event in durable_checkpoint["events"]] == [
        "registered"
    ]
    with engine.connect() as connection:
        assert connection.scalar(
            text(
                "SELECT count(*) FROM team_agent_orchestration_checkpoint_events "
                "WHERE session_ref=:session_ref"
            ),
            {"session_ref": session_ref},
        ) == 1
    committed = TeamAgentCoordinator.restore(
        coordinator.checkpoint(session_ref=session_ref),
        scope=SCOPE,
    )
    with engine.begin() as connection:
        tasks = PostgresTeamAgentPersistence(engine, connection=connection)
        checkpoints = PostgresTeamAgentCheckpointStore(engine, connection=connection)
        locked = checkpoints.restore(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            for_update=True,
        )
        claimed = tasks.claim_task(
            scope=SCOPE,
            session_ref=session_ref,
            task_ref=task_ref,
            worker_id="reader-a",
            lease_seconds=30,
            as_of=T0 + timedelta(seconds=1),
        )
        committed.claim_task(
            task_ref=task_ref,
            worker_id="reader-a",
            lease_seconds=30,
            lease_id=claimed.lease_ref,
            as_of=T0 + timedelta(seconds=1),
        )
        committed.bind_durable_task_revision(
            task_ref=task_ref,
            revision=claimed.revision,
        )
        saved = checkpoints.save(
            coordinator=committed,
            session_ref=session_ref,
            expected_revision=locked.durable.revision,
            as_of=T0 + timedelta(seconds=1),
        )

    durable_after_commit = PostgresTeamAgentPersistence(engine).task(
        scope=SCOPE,
        session_ref=session_ref,
        task_ref=task_ref,
    )
    checkpoint_after_commit = PostgresTeamAgentCheckpointStore(engine).restore(
        scope=SCOPE,
        session_ref=session_ref,
        authority_sha256="a" * 64,
    )
    assert saved.revision == checkpoint_after_commit.durable.revision == 1
    assert durable_after_commit.revision == 1
    assert durable_after_commit.state is DurableTaskState.RUNNING
    assert checkpoint_after_commit.coordinator.task(task_ref).state.value == "running"
    assert (
        checkpoint_after_commit.coordinator.task(task_ref).lease_ref
        == durable_after_commit.lease_ref
    )


def test_checkpoint_restore_keeps_stronger_serializable_caller_transaction(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    seed = f"serializable-{tag}"
    session_ref = f"session-checkpoint-{seed}"
    coordinator = _coordinator(seed)
    PostgresTeamAgentCheckpointStore(engine).save(
        coordinator=coordinator,
        session_ref=session_ref,
        expected_revision=None,
        as_of=T0,
    )

    with engine.connect().execution_options(
        isolation_level="SERIALIZABLE"
    ) as connection, connection.begin():
        restored = PostgresTeamAgentCheckpointStore(
            engine,
            connection=connection,
        ).restore(
            scope=SCOPE,
            session_ref=session_ref,
            authority_sha256="a" * 64,
            for_update=True,
        )
        effective = connection.exec_driver_sql(
            "SHOW transaction_isolation"
        ).scalar_one()

    assert restored.durable.revision == 0
    assert str(effective).lower() == "serializable"


def test_task_event_checkpoint_upgrades_default_caller_transaction(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-task-checkpoint-{tag}"
    task_ref = f"task-checkpoint-{tag}"
    store = PostgresTeamAgentPersistence(engine)
    store.register_task(
        scope=SCOPE,
        task=TeamAgentTaskRegistration(
            session_ref=session_ref,
            task_ref=task_ref,
            idempotency_key=f"idem-{tag}",
            payload={"agent_id": "reader-a", "objective": "consistent snapshot"},
        ),
        as_of=T0,
    )

    with engine.begin() as connection:
        checkpoint = PostgresTeamAgentPersistence(
            engine,
            connection=connection,
        ).checkpoint(
            scope=SCOPE,
            session_ref=session_ref,
        )
        effective = connection.exec_driver_sql(
            "SHOW transaction_isolation"
        ).scalar_one()

    assert [item["task_ref"] for item in checkpoint["tasks"]] == [task_ref]
    assert [item["event_type"] for item in checkpoint["events"]] == [
        "registered"
    ]
    assert str(effective).lower() == "repeatable read"


def test_task_event_checkpoint_keeps_stronger_serializable_transaction(
    engine: Engine,
) -> None:
    tag = uuid4().hex
    session_ref = f"session-task-serializable-{tag}"
    store = PostgresTeamAgentPersistence(engine)
    store.register_task(
        scope=SCOPE,
        task=TeamAgentTaskRegistration(
            session_ref=session_ref,
            task_ref=f"task-{tag}",
            idempotency_key=f"idem-{tag}",
            payload={"agent_id": "reader-a", "objective": "strong snapshot"},
        ),
        as_of=T0,
    )

    with engine.connect().execution_options(
        isolation_level="SERIALIZABLE"
    ) as connection, connection.begin():
        PostgresTeamAgentPersistence(
            engine,
            connection=connection,
        ).checkpoint(
            scope=SCOPE,
            session_ref=session_ref,
        )
        effective = connection.exec_driver_sql(
            "SHOW transaction_isolation"
        ).scalar_one()

    assert str(effective).lower() == "serializable"
