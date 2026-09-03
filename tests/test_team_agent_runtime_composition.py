from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import DBAPIError

from apps.control_plane.agent_team_orchestration import TeamAgentCoordinator
from apps.control_plane.enterprise_control import ExactScope
from apps.control_plane.runtime import _build_team_agent_runtime
from apps.control_plane.runtime import runtime as composed_runtime
from apps.control_plane.team_agent_persistence import TeamAgentTransactionConflict
from apps.control_plane.team_agent_postgres_runtime import PostgresTeamAgentRuntime
from apps.control_plane.team_agent_reviewer_authority import (
    UnavailableTeamAgentReviewerAuthority,
)


class _PostgresConflict(Exception):
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate
        super().__init__(sqlstate)


class _FailingConnection:
    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate

    def execution_options(self, **_: object):
        return self

    def __enter__(self):
        raise DBAPIError(
            statement=None,
            params=None,
            orig=_PostgresConflict(self.sqlstate),
            connection_invalidated=False,
        )

    def __exit__(self, *_: object) -> None:
        return None


class _FailingEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, sqlstate: str) -> None:
        self.sqlstate = sqlstate

    def connect(self) -> _FailingConnection:
        return _FailingConnection(self.sqlstate)


class _NoIoEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self) -> None:
        self.connect_calls = 0

    def connect(self):
        self.connect_calls += 1
        raise AssertionError("unscoped durable reads must fail before database I/O")


def test_non_postgres_runtime_keeps_in_process_team_agent_pilot() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        assert isinstance(_build_team_agent_runtime(engine), TeamAgentCoordinator)
    finally:
        engine.dispose()


def test_postgres_runtime_selects_transactional_team_agent_facade() -> None:
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    runtime = _build_team_agent_runtime(engine)

    assert isinstance(runtime, PostgresTeamAgentRuntime)
    assert runtime.engine is engine
    assert runtime.requires_durable_scope is True


def test_production_runtime_defaults_reviewer_appointments_to_fail_closed() -> None:
    assert isinstance(
        composed_runtime.agent_team_reviewer_authority,
        UnavailableTeamAgentReviewerAuthority,
    )
    assert callable(composed_runtime.agent_team_terminal_outbox_factory)


@pytest.mark.parametrize("sqlstate", ["40001", "40P01"])
def test_postgres_aborted_transaction_requires_fresh_restore_before_retry(
    sqlstate: str,
) -> None:
    runtime = PostgresTeamAgentRuntime(_FailingEngine(sqlstate))

    with pytest.raises(TeamAgentTransactionConflict) as exc_info, runtime._transaction():
        raise AssertionError("connection entry must fail first")

    assert exc_info.value.sqlstate == sqlstate
    assert exc_info.value.retryable is True
    assert exc_info.value.transaction_outcome == "rolled_back"
    assert exc_info.value.retry_requires_fresh_restore is True


def test_non_retryable_database_error_is_not_reclassified() -> None:
    runtime = PostgresTeamAgentRuntime(_FailingEngine("08006"))

    with pytest.raises(DBAPIError) as exc_info, runtime._transaction():
        raise AssertionError("connection entry must fail first")

    assert exc_info.value.orig.sqlstate == "08006"


@pytest.mark.parametrize(
    "read",
    [
        lambda runtime: runtime.session("session-a"),
        lambda runtime: runtime.task("task-a"),
        lambda runtime: runtime.snapshot(session_ref="session-a"),
        lambda runtime: runtime.observations(session_ref="session-a"),
        lambda runtime: runtime.session_coordinator("session-a"),
    ],
)
def test_postgres_runtime_rejects_bare_global_read_ids_before_io(read) -> None:
    engine = _NoIoEngine()
    runtime = PostgresTeamAgentRuntime(engine)

    with pytest.raises(ValueError, match="requires .*scope.*authority"):
        read(runtime)

    assert engine.connect_calls == 0


def test_postgres_runtime_scoped_read_helpers_restore_exact_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = PostgresTeamAgentRuntime(_NoIoEngine())
    scope = ExactScope("tenant-a", "entity-a", "store-a")
    coordinator = SimpleNamespace(
        session=lambda session_ref: ("session", session_ref),
        task=lambda task_ref: ("task", task_ref),
        snapshot=lambda *, session_ref: {"session_ref": session_ref},
        observations=lambda *, session_ref: [("observation", session_ref)],
    )
    admissions: list[dict[str, object]] = []

    def restore_session(**values: object):
        admissions.append(values)
        return coordinator

    monkeypatch.setattr(runtime, "restore_session", restore_session)
    kwargs = {
        "scope": scope,
        "authority_sha256": "a" * 64,
    }

    assert runtime.session("session-a", **kwargs) == ("session", "session-a")
    assert runtime.task(
        "task-a",
        session_ref="session-a",
        **kwargs,
    ) == ("task", "task-a")
    assert runtime.snapshot(session_ref="session-a", **kwargs) == {
        "session_ref": "session-a"
    }
    assert runtime.observations(session_ref="session-a", **kwargs) == [
        ("observation", "session-a")
    ]
    assert all(
        admission
        == {
            "scope": scope,
            "session_ref": "session-a",
            "authority_sha256": "a" * 64,
            "for_update": False,
        }
        for admission in admissions
    )
