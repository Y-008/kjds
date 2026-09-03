"""Durable, authority-bound TeamAgent session checkpoint storage.

The module owns checkpoint validation, Coordinator hydration, revision CAS,
and immutable save history.  Callers work with a Coordinator and a revision;
they never construct checkpoint rows or SQL themselves.
"""

from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import DBAPIError, InvalidRequestError

from .agent_team_orchestration import TeamAgentCoordinator
from .enterprise_control import EnterpriseControlError, ExactScope
from .team_agent_persistence import metadata

CONTRACT_ID = "kjds-team-agent-checkpoint-store-v1"
MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024
CHECKPOINT_TABLE_NAME = "team_agent_orchestration_checkpoints"
CHECKPOINT_EVENT_TABLE_NAME = "team_agent_orchestration_checkpoint_events"
CONSISTENT_SNAPSHOT_ISOLATIONS = frozenset({"REPEATABLE READ", "SERIALIZABLE"})


class TeamAgentCheckpointError(EnterpriseControlError):
    """Base error for durable Coordinator checkpoint operations."""


class TeamAgentCheckpointConflict(TeamAgentCheckpointError):
    """The requested save lost CAS or conflicts with durable identity."""


class TeamAgentCheckpointNotFound(TeamAgentCheckpointError):
    """No checkpoint is visible in the supplied exact scope."""


class TeamAgentCheckpointIntegrityError(TeamAgentCheckpointError):
    """Durable checkpoint content or authority failed validation."""


@dataclass(frozen=True, slots=True)
class DurableTeamAgentCheckpoint:
    scope: ExactScope
    session_ref: str
    authority_sha256: str
    checkpoint: dict[str, Any]
    checkpoint_sha256: str
    last_control_cursor: str
    last_control_event_sha256: str
    revision: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class HydratedTeamAgentSession:
    coordinator: TeamAgentCoordinator
    durable: DurableTeamAgentCheckpoint


class TeamAgentCheckpointStore(Protocol):
    """Small interface for save-CAS and authority-checked restart hydration."""

    def save(
        self,
        *,
        coordinator: TeamAgentCoordinator,
        session_ref: str,
        expected_revision: int | None,
        as_of: datetime | None = None,
    ) -> DurableTeamAgentCheckpoint: ...

    def restore(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        for_update: bool = False,
    ) -> HydratedTeamAgentSession: ...


checkpoints = Table(
    CHECKPOINT_TABLE_NAME,
    metadata,
    Column("tenant_ref", String(160), nullable=False),
    Column("entity_ref", String(160), nullable=False),
    Column("store_ref", String(160), nullable=False),
    Column("session_ref", String(160), nullable=False),
    Column("authority_sha256", String(64), nullable=False),
    Column("checkpoint_json", JSONB, nullable=False),
    Column("checkpoint_sha256", String(64), nullable=False),
    Column("last_control_cursor", String(160), nullable=False),
    Column("last_control_event_sha256", String(64), nullable=False),
    Column("revision", BigInteger, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "session_ref",
        name="pk_team_agent_orchestration_checkpoint",
    ),
    CheckConstraint(
        "authority_sha256 ~ '^[0-9a-f]{64}$' AND "
        "checkpoint_sha256 ~ '^[0-9a-f]{64}$' AND "
        "last_control_event_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_team_agent_checkpoint_hashes",
    ),
    CheckConstraint(
        "revision >= 0 AND updated_at >= created_at",
        name="ck_team_agent_checkpoint_revision_time",
    ),
)
Index(
    "ix_team_agent_checkpoint_updated",
    checkpoints.c.tenant_ref,
    checkpoints.c.entity_ref,
    checkpoints.c.store_ref,
    checkpoints.c.updated_at,
)

checkpoint_events = Table(
    CHECKPOINT_EVENT_TABLE_NAME,
    metadata,
    Column("event_id", BigInteger, Identity(), primary_key=True),
    Column("tenant_ref", String(160), nullable=False),
    Column("entity_ref", String(160), nullable=False),
    Column("store_ref", String(160), nullable=False),
    Column("session_ref", String(160), nullable=False),
    Column("checkpoint_revision", BigInteger, nullable=False),
    Column("authority_sha256", String(64), nullable=False),
    Column("checkpoint_sha256", String(64), nullable=False),
    Column("last_control_cursor", String(160), nullable=False),
    Column("last_control_event_sha256", String(64), nullable=False),
    Column("saved_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_ref", "entity_ref", "store_ref", "session_ref"],
        [
            f"{CHECKPOINT_TABLE_NAME}.tenant_ref",
            f"{CHECKPOINT_TABLE_NAME}.entity_ref",
            f"{CHECKPOINT_TABLE_NAME}.store_ref",
            f"{CHECKPOINT_TABLE_NAME}.session_ref",
        ],
        name="fk_team_agent_checkpoint_event_checkpoint",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "session_ref",
        "checkpoint_revision",
        name="uq_team_agent_checkpoint_event_revision",
    ),
    CheckConstraint(
        "checkpoint_revision >= 0",
        name="ck_team_agent_checkpoint_event_revision",
    ),
)
Index(
    "ix_team_agent_checkpoint_event_cursor",
    checkpoint_events.c.tenant_ref,
    checkpoint_events.c.entity_ref,
    checkpoint_events.c.store_ref,
    checkpoint_events.c.session_ref,
    checkpoint_events.c.event_id,
)


def _utc(value: datetime | None = None) -> datetime:
    parsed = value or datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _required_text(value: Any, name: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{name} must be 1 to {maximum} characters")
    return normalized


def _sha256(value: Any, name: str) -> str:
    try:
        normalized = _required_text(value, name, 64).lower()
    except ValueError as exc:
        raise TeamAgentCheckpointIntegrityError(
            f"{name} must be lowercase SHA-256"
        ) from exc
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise TeamAgentCheckpointIntegrityError(f"{name} must be lowercase SHA-256")
    return normalized


def _scope_values(scope: ExactScope) -> dict[str, str]:
    return {
        "tenant_ref": _required_text(scope.tenant_ref, "tenant_ref", 160),
        "entity_ref": _required_text(scope.entity_ref, "entity_ref", 160),
        "store_ref": _required_text(scope.store_ref, "store_ref", 160),
    }


def _canonical_checkpoint(value: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise TeamAgentCheckpointIntegrityError(
            "Coordinator checkpoint must be canonical JSON"
        ) from exc
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise TeamAgentCheckpointIntegrityError("Coordinator checkpoint is too large")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise TeamAgentCheckpointIntegrityError("Coordinator checkpoint must be an object")
    return decoded


def _validated_snapshot(
    coordinator: TeamAgentCoordinator,
    session_ref: str,
) -> dict[str, Any]:
    session = coordinator.session(_required_text(session_ref, "session_ref", 160))
    authority = _sha256(session.authority_sha256, "authority_sha256")
    checkpoint = _canonical_checkpoint(coordinator.checkpoint(session_ref=session_ref))
    try:
        restored = TeamAgentCoordinator.restore(checkpoint, scope=session.scope)
        restored_session = restored.session(session_ref)
    except Exception as exc:
        raise TeamAgentCheckpointIntegrityError(
            "Coordinator checkpoint failed restore validation"
        ) from exc
    if restored_session.authority_sha256 != authority:
        raise TeamAgentCheckpointIntegrityError("checkpoint authority mismatch")
    events = checkpoint.get("events")
    if not isinstance(events, list) or not events:
        raise TeamAgentCheckpointIntegrityError("checkpoint control event chain is empty")
    last_event = events[-1]
    if not isinstance(last_event, dict) or last_event.get("session_ref") != session_ref:
        raise TeamAgentCheckpointIntegrityError("checkpoint control tail is invalid")
    cursor = _required_text(last_event.get("cursor"), "last_control_cursor", 160)
    event_hash = _sha256(
        last_event.get("event_hash"),
        "last_control_event_sha256",
    )
    checkpoint_sha = _sha256(
        checkpoint.get("checkpoint_sha256"),
        "checkpoint_sha256",
    )
    return {
        **_scope_values(session.scope),
        "session_ref": session_ref,
        "authority_sha256": authority,
        "checkpoint_json": checkpoint,
        "checkpoint_sha256": checkpoint_sha,
        "last_control_cursor": cursor,
        "last_control_event_sha256": event_hash,
    }


def _record_from_mapping(row: dict[str, Any] | RowMapping) -> DurableTeamAgentCheckpoint:
    checkpoint = _canonical_checkpoint(dict(row["checkpoint_json"]))
    return DurableTeamAgentCheckpoint(
        scope=ExactScope(row["tenant_ref"], row["entity_ref"], row["store_ref"]),
        session_ref=row["session_ref"],
        authority_sha256=_sha256(row["authority_sha256"], "authority_sha256"),
        checkpoint=checkpoint,
        checkpoint_sha256=_sha256(row["checkpoint_sha256"], "checkpoint_sha256"),
        last_control_cursor=_required_text(
            row["last_control_cursor"], "last_control_cursor", 160
        ),
        last_control_event_sha256=_sha256(
            row["last_control_event_sha256"],
            "last_control_event_sha256",
        ),
        revision=int(row["revision"]),
        created_at=_utc(row["created_at"]),
        updated_at=_utc(row["updated_at"]),
    )


def _copy_checkpoint_record(
    record: DurableTeamAgentCheckpoint,
) -> DurableTeamAgentCheckpoint:
    """Detach mutable checkpoint JSON from a store-owned canonical record."""

    return replace(
        record,
        checkpoint=_canonical_checkpoint(record.checkpoint),
    )


def _restore_record(
    record: DurableTeamAgentCheckpoint,
    *,
    scope: ExactScope,
    session_ref: str,
    authority_sha256: str,
) -> HydratedTeamAgentSession:
    authority = _sha256(authority_sha256, "authority_sha256")
    if record.scope != scope or record.session_ref != session_ref:
        raise TeamAgentCheckpointNotFound("TeamAgent checkpoint not found in exact scope")
    if record.authority_sha256 != authority:
        raise TeamAgentCheckpointIntegrityError("checkpoint authority is stale")
    try:
        coordinator = TeamAgentCoordinator.restore(record.checkpoint, scope=scope)
    except Exception as exc:
        raise TeamAgentCheckpointIntegrityError(
            "durable checkpoint failed restore validation"
        ) from exc
    validated = _validated_snapshot(coordinator, session_ref)
    if (
        validated["checkpoint_sha256"] != record.checkpoint_sha256
        or validated["authority_sha256"] != record.authority_sha256
        or validated["last_control_cursor"] != record.last_control_cursor
        or validated["last_control_event_sha256"]
        != record.last_control_event_sha256
    ):
        raise TeamAgentCheckpointIntegrityError("durable checkpoint metadata mismatch")
    return HydratedTeamAgentSession(
        coordinator=coordinator,
        durable=_copy_checkpoint_record(record),
    )


def _assert_checkpoint_history(
    record: DurableTeamAgentCheckpoint,
    history: list[dict[str, Any]],
) -> None:
    revisions = [int(item["checkpoint_revision"]) for item in history]
    if revisions != list(range(record.revision + 1)):
        raise TeamAgentCheckpointIntegrityError(
            "durable checkpoint save history is not conserved"
        )
    previous_saved_at: datetime | None = None
    for item in history:
        if _sha256(item["authority_sha256"], "authority_sha256") != record.authority_sha256:
            raise TeamAgentCheckpointIntegrityError(
                "durable checkpoint save history authority mismatch"
            )
        _sha256(item["checkpoint_sha256"], "checkpoint_sha256")
        _required_text(item["last_control_cursor"], "last_control_cursor", 160)
        _sha256(
            item["last_control_event_sha256"],
            "last_control_event_sha256",
        )
        saved_at = _utc(item["saved_at"])
        if previous_saved_at is not None and saved_at < previous_saved_at:
            raise TeamAgentCheckpointIntegrityError(
                "durable checkpoint save history time regressed"
            )
        previous_saved_at = saved_at
    tail = history[-1]
    if (
        tail["checkpoint_sha256"] != record.checkpoint_sha256
        or tail["last_control_cursor"] != record.last_control_cursor
        or tail["last_control_event_sha256"] != record.last_control_event_sha256
        or _utc(tail["saved_at"]) != record.updated_at
    ):
        raise TeamAgentCheckpointIntegrityError(
            "durable checkpoint save history tail mismatch"
        )


class InMemoryTeamAgentCheckpointStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, str], DurableTeamAgentCheckpoint] = {}
        self._history: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def save(
        self,
        *,
        coordinator: TeamAgentCoordinator,
        session_ref: str,
        expected_revision: int | None,
        as_of: datetime | None = None,
    ) -> DurableTeamAgentCheckpoint:
        values = _validated_snapshot(coordinator, session_ref)
        key = (
            values["tenant_ref"],
            values["entity_ref"],
            values["store_ref"],
            values["session_ref"],
        )
        now = _utc(as_of)
        with self._lock:
            current = self._rows.get(key)
            if current is None:
                if expected_revision is not None:
                    raise TeamAgentCheckpointConflict("checkpoint CAS target is missing")
                revision = 0
                created_at = now
            else:
                if expected_revision is None:
                    if current.checkpoint_sha256 == values["checkpoint_sha256"]:
                        return _copy_checkpoint_record(current)
                    raise TeamAgentCheckpointConflict("checkpoint already exists")
                if current.revision != expected_revision:
                    raise TeamAgentCheckpointConflict("checkpoint revision CAS lost")
                if current.authority_sha256 != values["authority_sha256"]:
                    raise TeamAgentCheckpointConflict("checkpoint authority changed")
                if current.checkpoint_sha256 == values["checkpoint_sha256"]:
                    return _copy_checkpoint_record(current)
                if now < current.updated_at:
                    raise TeamAgentCheckpointConflict(
                        "checkpoint mutation timestamp regresses updated_at"
                    )
                revision = current.revision + 1
                created_at = current.created_at
            record = _record_from_mapping(
                {
                    **values,
                    "revision": revision,
                    "created_at": created_at,
                    "updated_at": now,
                }
            )
            self._rows[key] = record
            self._history.append(
                {
                    "key": key,
                    "checkpoint_revision": revision,
                    "authority_sha256": record.authority_sha256,
                    "checkpoint_sha256": record.checkpoint_sha256,
                    "last_control_cursor": record.last_control_cursor,
                    "last_control_event_sha256": record.last_control_event_sha256,
                    "saved_at": record.updated_at,
                }
            )
            return _copy_checkpoint_record(record)

    def restore(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        for_update: bool = False,
    ) -> HydratedTeamAgentSession:
        del for_update
        values = _scope_values(scope)
        key = (
            values["tenant_ref"],
            values["entity_ref"],
            values["store_ref"],
            _required_text(session_ref, "session_ref", 160),
        )
        with self._lock:
            record = self._rows.get(key)
        if record is None:
            raise TeamAgentCheckpointNotFound("TeamAgent checkpoint not found in exact scope")
        history = [item for item in self._history if item["key"] == key]
        _assert_checkpoint_history(record, history)
        return _restore_record(
            record,
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
        )


class PostgresTeamAgentCheckpointStore:
    def __init__(
        self,
        engine: Engine,
        *,
        connection: Connection | None = None,
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgresTeamAgentCheckpointStore requires PostgreSQL")
        if connection is not None and connection.engine is not engine:
            raise ValueError("TeamAgent checkpoint connection belongs to another engine")
        self.engine = engine
        self._connection = connection

    def _begin(self):
        if self._connection is not None:
            return nullcontext(self._connection)
        return self.engine.begin()

    def _connect(self):
        if self._connection is not None:
            return nullcontext(self._connection)
        return self.engine.connect()

    def save(
        self,
        *,
        coordinator: TeamAgentCoordinator,
        session_ref: str,
        expected_revision: int | None,
        as_of: datetime | None = None,
    ) -> DurableTeamAgentCheckpoint:
        values = _validated_snapshot(coordinator, session_ref)
        now = _utc(as_of)
        with self._begin() as connection:
            if expected_revision is None:
                row = connection.execute(
                    postgresql_insert(checkpoints)
                    .values(
                        **values,
                        revision=0,
                        created_at=now,
                        updated_at=now,
                    )
                    .on_conflict_do_nothing()
                    .returning(*checkpoints.c)
                ).mappings().one_or_none()
                if row is None:
                    existing = connection.execute(
                        select(checkpoints).where(*self._predicates(values))
                    ).mappings().one_or_none()
                    if existing is None:
                        raise TeamAgentCheckpointConflict(
                            "checkpoint creation lost its conflict winner"
                        )
                    record = _record_from_mapping(existing)
                    if record.checkpoint_sha256 == values["checkpoint_sha256"]:
                        return _copy_checkpoint_record(record)
                    raise TeamAgentCheckpointConflict("checkpoint already exists")
            else:
                existing = connection.execute(
                    select(checkpoints).where(
                        *self._predicates(values),
                        checkpoints.c.revision == expected_revision,
                        checkpoints.c.authority_sha256
                        == values["authority_sha256"],
                    )
                ).mappings().one_or_none()
                if existing is not None:
                    current = _record_from_mapping(existing)
                    if current.checkpoint_sha256 == values["checkpoint_sha256"]:
                        return _copy_checkpoint_record(current)
                row = connection.execute(
                    update(checkpoints)
                    .where(
                        *self._predicates(values),
                        checkpoints.c.revision == expected_revision,
                        checkpoints.c.updated_at <= now,
                        checkpoints.c.authority_sha256
                        == values["authority_sha256"],
                    )
                    .values(
                        checkpoint_json=values["checkpoint_json"],
                        checkpoint_sha256=values["checkpoint_sha256"],
                        last_control_cursor=values["last_control_cursor"],
                        last_control_event_sha256=values[
                            "last_control_event_sha256"
                        ],
                        revision=checkpoints.c.revision + 1,
                        updated_at=now,
                    )
                    .returning(*checkpoints.c)
                ).mappings().one_or_none()
                if row is None:
                    raise TeamAgentCheckpointConflict("checkpoint revision CAS lost")
            record = _record_from_mapping(row)
            connection.execute(
                insert(checkpoint_events).values(
                    tenant_ref=record.scope.tenant_ref,
                    entity_ref=record.scope.entity_ref,
                    store_ref=record.scope.store_ref,
                    session_ref=record.session_ref,
                    checkpoint_revision=record.revision,
                    authority_sha256=record.authority_sha256,
                    checkpoint_sha256=record.checkpoint_sha256,
                    last_control_cursor=record.last_control_cursor,
                    last_control_event_sha256=record.last_control_event_sha256,
                    saved_at=record.updated_at,
                )
            )
            return _copy_checkpoint_record(record)

    def restore(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        for_update: bool = False,
    ) -> HydratedTeamAgentSession:
        values = {**_scope_values(scope), "session_ref": session_ref}
        if self._connection is not None:
            return self._restore_on_connection(
                self._connection,
                values=values,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                for_update=for_update,
            )
        if for_update:
            raise ValueError("for_update requires a caller-owned transaction")
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection, connection.begin():
            return self._restore_on_connection(
                connection,
                values=values,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                for_update=False,
            )

    def _restore_on_connection(
        self,
        connection: Connection,
        *,
        values: dict[str, Any],
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        for_update: bool,
    ) -> HydratedTeamAgentSession:
        # Restore reads the current checkpoint and its immutable history in
        # separate statements.  A caller-owned READ COMMITTED transaction
        # could otherwise observe a new checkpoint row and an older history
        # (or vice versa).  Use one repeatable-read snapshot whenever the
        # transaction has not started; if it has already started at a weaker
        # isolation level, fail closed rather than hydrating torn state.
        try:
            isolation = str(connection.get_isolation_level()).upper()
        except (AttributeError, InvalidRequestError):
            isolation = ""
        if isolation not in CONSISTENT_SNAPSHOT_ISOLATIONS:
            if connection.in_transaction():
                # ``engine.begin()`` starts SQLAlchemy's transaction wrapper
                # before the first SQL statement.  Changing the connection
                # execution option at that point raises InvalidRequestError,
                # even though PostgreSQL can still safely set the isolation
                # level for the as-yet-unstarted database transaction.  Use a
                # transaction-local SET so caller-owned transactions retain a
                # single repeatable snapshot without opening a second one.
                try:
                    connection.exec_driver_sql(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
                    )
                    effective_isolation = str(
                        connection.exec_driver_sql(
                            "SHOW transaction_isolation"
                        ).scalar_one()
                    ).upper()
                except (DBAPIError, InvalidRequestError) as exc:
                    raise TeamAgentCheckpointIntegrityError(
                        "checkpoint restore requires a repeatable-read caller transaction"
                    ) from exc
                if effective_isolation not in CONSISTENT_SNAPSHOT_ISOLATIONS:
                    raise TeamAgentCheckpointIntegrityError(
                        "checkpoint restore requires a repeatable-read caller transaction"
                    )
            else:
                try:
                    connection.execution_options(isolation_level="REPEATABLE READ")
                except InvalidRequestError as exc:
                    raise TeamAgentCheckpointIntegrityError(
                        "checkpoint restore requires a repeatable-read caller transaction"
                    ) from exc
        statement = select(checkpoints).where(*self._predicates(values))
        if for_update:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise TeamAgentCheckpointNotFound("TeamAgent checkpoint not found in exact scope")
        history = connection.execute(
            select(checkpoint_events)
            .where(
                checkpoint_events.c.tenant_ref == values["tenant_ref"],
                checkpoint_events.c.entity_ref == values["entity_ref"],
                checkpoint_events.c.store_ref == values["store_ref"],
                checkpoint_events.c.session_ref
                == _required_text(session_ref, "session_ref", 160),
            )
            .order_by(checkpoint_events.c.checkpoint_revision)
        ).mappings().all()
        record = _record_from_mapping(row)
        _assert_checkpoint_history(record, [dict(item) for item in history])
        return _restore_record(
            record,
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
        )

    @staticmethod
    def _predicates(values: dict[str, Any]) -> tuple[Any, ...]:
        return (
            checkpoints.c.tenant_ref == values["tenant_ref"],
            checkpoints.c.entity_ref == values["entity_ref"],
            checkpoints.c.store_ref == values["store_ref"],
            checkpoints.c.session_ref
            == _required_text(values["session_ref"], "session_ref", 160),
        )


__all__ = [
    "CONTRACT_ID",
    "DurableTeamAgentCheckpoint",
    "HydratedTeamAgentSession",
    "InMemoryTeamAgentCheckpointStore",
    "PostgresTeamAgentCheckpointStore",
    "TeamAgentCheckpointConflict",
    "TeamAgentCheckpointError",
    "TeamAgentCheckpointIntegrityError",
    "TeamAgentCheckpointNotFound",
    "TeamAgentCheckpointStore",
    "checkpoint_events",
    "checkpoints",
]
