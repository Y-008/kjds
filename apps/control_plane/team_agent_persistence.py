"""Durable TeamAgent task persistence and lease compare-and-swap semantics.

The seam deliberately owns revisions, lease identities, conditional updates,
and transition events.  Callers register tasks and operate on lease results;
they never construct SQL or perform a read-modify-write sequence themselves.

PostgreSQL runtime composition consumes this seam through
``PostgresTeamAgentRuntime``; non-PostgreSQL local composition intentionally
keeps the in-process Pilot.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    and_,
    insert,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import DBAPIError, InvalidRequestError

from .enterprise_control import EnterpriseControlError, ExactScope
from .team_agent_result_contract import normalize_team_agent_result

CONTRACT_ID = "kjds-team-agent-persistence-v1"
MAX_ATTEMPTS = 3
MAX_PAYLOAD_BYTES = 65_536
MAX_TEXT_BYTES = 4_096
MAX_RETRY_AFTER_SECONDS = 30.0
TASK_TABLE_NAME = "team_agent_orchestration_tasks"
EVENT_TABLE_NAME = "team_agent_orchestration_events"
CONSISTENT_SNAPSHOT_ISOLATIONS = frozenset({"REPEATABLE READ", "SERIALIZABLE"})


class DurableTaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    EXPIRED = "expired"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class TeamAgentPersistenceError(EnterpriseControlError):
    """Base error for the persistence seam."""


class TeamAgentPersistenceConflict(TeamAgentPersistenceError):
    """The requested mutation conflicts with durable state."""


class TeamAgentReplayConflict(TeamAgentPersistenceConflict):
    """A committed terminal operation was replayed with different inputs."""

    http_status_code = 409

    @property
    def http_detail(self) -> dict[str, str]:
        return {"code": "idempotency_conflict", "message": str(self)}


class TeamAgentTransactionConflict(TeamAgentPersistenceConflict):
    """PostgreSQL aborted the whole transaction before a durable outcome."""

    http_status_code = 409

    def __init__(self, *, sqlstate: str) -> None:
        self.sqlstate = sqlstate
        self.retryable = True
        self.transaction_outcome = "rolled_back"
        self.retry_requires_fresh_restore = True
        super().__init__("TeamAgent session transaction must be retried after restore")

    @property
    def http_detail(self) -> dict[str, object]:
        return {
            "code": "team_agent_transaction_conflict",
            "message": str(self),
            "sqlstate": self.sqlstate,
            "retryable": self.retryable,
            "transaction_outcome": self.transaction_outcome,
            "retry_requires_fresh_restore": self.retry_requires_fresh_restore,
        }


class TeamAgentTaskNotFound(TeamAgentPersistenceError):
    """No task is visible in the supplied exact scope."""


@dataclass(frozen=True, slots=True)
class TeamAgentTaskRegistration:
    session_ref: str
    task_ref: str
    idempotency_key: str
    payload: Mapping[str, Any]
    max_attempts: int = MAX_ATTEMPTS


@dataclass(frozen=True, slots=True)
class PersistedTeamAgentTask:
    scope: ExactScope
    session_ref: str
    task_ref: str
    idempotency_key: str
    request_sha256: str
    payload: dict[str, Any]
    state: DurableTaskState
    claimed_by: str | None
    lease_ref: str | None
    lease_expires_at: datetime | None
    attempt_count: int
    max_attempts: int
    retry_wait_until: datetime | None
    retry_after_seconds: float | None
    reviewer_id: str | None
    result: dict[str, Any] | None
    evidence_refs: tuple[str, ...]
    failure_code: str | None
    failure_kind: str | None
    blocked_reason: str | None
    revision: int
    completed_at: datetime | None
    expired_at: datetime | None
    created_at: datetime
    updated_at: datetime
    paused_retry_wait_until: datetime | None = None
    paused_retry_after_seconds: float | None = None


class TeamAgentPersistence(Protocol):
    """Small persistence interface shared by the memory and PostgreSQL adapters."""

    def register_task(
        self,
        *,
        scope: ExactScope,
        task: TeamAgentTaskRegistration,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
    ) -> PersistedTeamAgentTask: ...

    def claim_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_seconds: int,
        lease_ref: str | None = None,
        lease_expires_at: datetime | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def heartbeat_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        extend_seconds: int,
        lease_expires_at: datetime | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def release_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def complete_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        result: Mapping[str, Any],
        evidence_refs: Sequence[str] = (),
        reviewer_id: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def fail_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        failure_code: str,
        failure_kind: str,
        next_state: DurableTaskState | str = DurableTaskState.FAILED,
        retry_wait_until: datetime | None = None,
        retry_after_seconds: float | None = None,
        blocked_reason: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def pause_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        worker_id: str | None = None,
        lease_ref: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def resume_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def revoke_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def block_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def expire_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        next_state: DurableTaskState | str | None = None,
        blocked_reason: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask: ...

    def checkpoint(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
    ) -> dict[str, Any]: ...


metadata = MetaData()
json_object_type = JSON(none_as_null=True).with_variant(
    JSONB(none_as_null=True),
    "postgresql",
)

team_agent_tasks = Table(
    TASK_TABLE_NAME,
    metadata,
    Column("tenant_ref", String(160), nullable=False),
    Column("entity_ref", String(160), nullable=False),
    Column("store_ref", String(160), nullable=False),
    Column("session_ref", String(160), nullable=False),
    Column("task_ref", String(160), nullable=False),
    Column("idempotency_key", String(300), nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("payload_json", json_object_type, nullable=False),
    Column("state", String(32), nullable=False),
    Column("claimed_by", String(240), nullable=True),
    Column("lease_ref", String(80), nullable=True),
    Column("lease_expires_at", DateTime(timezone=True), nullable=True),
    Column("attempt_count", Integer, nullable=False),
    Column("max_attempts", Integer, nullable=False),
    Column("retry_wait_until", DateTime(timezone=True), nullable=True),
    Column("retry_after_seconds", Float, nullable=True),
    Column("paused_retry_wait_until", DateTime(timezone=True), nullable=True),
    Column("paused_retry_after_seconds", Float, nullable=True),
    Column("reviewer_id", String(240), nullable=True),
    Column("result_json", json_object_type, nullable=True),
    Column("evidence_refs_json", json_object_type, nullable=False, default=list),
    Column("failure_code", String(120), nullable=True),
    Column("failure_kind", String(120), nullable=True),
    Column("blocked_reason", String(500), nullable=True),
    Column("revision", BigInteger, nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("expired_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint(
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "session_ref",
        "task_ref",
        name="pk_team_agent_orchestration_task",
    ),
    UniqueConstraint(
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "session_ref",
        "idempotency_key",
        name="uq_team_agent_orchestration_idempotency",
    ),
    CheckConstraint(
        "length(btrim(tenant_ref)) > 0 AND length(btrim(entity_ref)) > 0 "
        "AND length(btrim(store_ref)) > 0 AND length(btrim(session_ref)) > 0 "
        "AND length(btrim(task_ref)) > 0 AND length(btrim(idempotency_key)) > 0",
        name="ck_team_agent_orchestration_required_text",
    ),
    CheckConstraint(
        "request_sha256 ~ '^[0-9a-f]{64}$'",
        name="ck_team_agent_orchestration_request_sha256",
    ),
    CheckConstraint(
        "(result_json IS NULL OR jsonb_typeof(result_json) = 'object') AND "
        "(result_json IS NULL OR octet_length(result_json::text) <= 65536)",
        name="ck_team_agent_orchestration_result",
    ),
    CheckConstraint(
        "jsonb_typeof(evidence_refs_json) = 'array' AND "
        "jsonb_array_length(evidence_refs_json) <= 50 AND "
        "octet_length(evidence_refs_json::text) <= 65536",
        name="ck_team_agent_orchestration_evidence_refs",
    ),
    CheckConstraint(
        "state IN ('queued','running','retry_wait','expired','blocked',"
        "'completed','failed','paused')",
        name="ck_team_agent_orchestration_state",
    ),
    CheckConstraint(
        "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 3 "
        "AND attempt_count <= max_attempts AND revision >= 0",
        name="ck_team_agent_orchestration_counters",
    ),
    CheckConstraint(
        "retry_after_seconds IS NULL OR "
        "(retry_after_seconds >= 0 AND retry_after_seconds <= 30)",
        name="ck_team_agent_orchestration_retry_after",
    ),
    CheckConstraint(
        "(state = 'running' AND claimed_by IS NOT NULL AND lease_ref IS NOT NULL "
        "AND lease_expires_at IS NOT NULL) OR "
        "(state <> 'running' AND claimed_by IS NULL AND lease_ref IS NULL "
        "AND lease_expires_at IS NULL)",
        name="ck_team_agent_orchestration_lease_shape",
    ),
    CheckConstraint(
        "(state = 'retry_wait' AND retry_wait_until IS NOT NULL) OR "
        "(state <> 'retry_wait' AND retry_wait_until IS NULL)",
        name="ck_team_agent_orchestration_retry_shape",
    ),
    CheckConstraint(
        "(state = 'completed' AND completed_at IS NOT NULL AND result_json IS NOT NULL) OR "
        "(state <> 'completed' AND completed_at IS NULL)",
        name="ck_team_agent_orchestration_completed_shape",
    ),
    CheckConstraint(
        "(state = 'expired' AND expired_at IS NOT NULL) OR "
        "(state <> 'expired' AND expired_at IS NULL)",
        name="ck_team_agent_orchestration_expired_shape",
    ),
    CheckConstraint(
        "updated_at >= created_at AND "
        "(completed_at IS NULL OR completed_at >= created_at) AND "
        "(expired_at IS NULL OR expired_at >= created_at) AND "
        "(lease_expires_at IS NULL OR lease_expires_at > updated_at)",
        name="ck_team_agent_orchestration_time_order",
    ),
)
Index(
    "uq_team_agent_orchestration_lease_ref",
    team_agent_tasks.c.lease_ref,
    unique=True,
    postgresql_where=team_agent_tasks.c.lease_ref.is_not(None),
)
Index(
    "ix_team_agent_orchestration_claimable",
    team_agent_tasks.c.tenant_ref,
    team_agent_tasks.c.entity_ref,
    team_agent_tasks.c.store_ref,
    team_agent_tasks.c.session_ref,
    team_agent_tasks.c.state,
    team_agent_tasks.c.retry_wait_until,
    team_agent_tasks.c.lease_expires_at,
)

team_agent_events = Table(
    EVENT_TABLE_NAME,
    metadata,
    Column("event_id", BigInteger, Identity(), primary_key=True),
    Column("tenant_ref", String(160), nullable=False),
    Column("entity_ref", String(160), nullable=False),
    Column("store_ref", String(160), nullable=False),
    Column("session_ref", String(160), nullable=False),
    Column("task_ref", String(160), nullable=False),
    Column("task_revision", BigInteger, nullable=False),
    Column("event_type", String(32), nullable=False),
    Column("worker_id", String(240), nullable=True),
    Column("lease_ref", String(80), nullable=True),
    Column("payload_json", json_object_type, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["tenant_ref", "entity_ref", "store_ref", "session_ref", "task_ref"],
        [
            f"{TASK_TABLE_NAME}.tenant_ref",
            f"{TASK_TABLE_NAME}.entity_ref",
            f"{TASK_TABLE_NAME}.store_ref",
            f"{TASK_TABLE_NAME}.session_ref",
            f"{TASK_TABLE_NAME}.task_ref",
        ],
        name="fk_team_agent_orchestration_event_task",
        ondelete="RESTRICT",
    ),
    UniqueConstraint(
        "tenant_ref",
        "entity_ref",
        "store_ref",
        "session_ref",
        "task_ref",
        "task_revision",
        name="uq_team_agent_orchestration_event_revision",
    ),
    CheckConstraint(
        "task_revision >= 0 AND event_type IN "
        "('registered','claimed','heartbeat','released','completed',"
        "'failed','retry_wait','blocked','paused','resumed','expired')",
        name="ck_team_agent_orchestration_event_shape",
    ),
)
Index(
    "ix_team_agent_orchestration_event_cursor",
    team_agent_events.c.tenant_ref,
    team_agent_events.c.entity_ref,
    team_agent_events.c.store_ref,
    team_agent_events.c.session_ref,
    team_agent_events.c.event_id,
)


def _required_text(value: Any, name: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{name} must be 1 to {maximum} characters")
    return normalized


def _utc(value: datetime | None = None) -> datetime:
    parsed = value or datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _json_object(
    value: Mapping[str, Any],
    *,
    field_name: str,
    maximum_bytes: int = MAX_PAYLOAD_BYTES,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be canonical JSON") from exc
    if len(encoded) > maximum_bytes:
        raise ValueError(f"{field_name} exceeds the bounded size")
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise ValueError(f"{field_name} must be an object")
    return decoded


def _payload(value: Mapping[str, Any]) -> dict[str, Any]:
    return _json_object(value, field_name="payload")


def _result(value: Mapping[str, Any]) -> dict[str, Any]:
    return _json_object(
        normalize_team_agent_result(value),
        field_name="result",
    )


def _evidence_refs(values: Sequence[str] | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise ValueError("evidence_refs must be a sequence")
    normalized = tuple(_required_text(value, "evidence_ref", 240) for value in values)
    if len(normalized) > 50:
        raise ValueError("evidence_refs exceeds the bounded size")
    if len(normalized) != len(set(normalized)):
        raise ValueError("evidence_refs must be unique")
    return normalized


def _retry_after_seconds(value: float | int | None) -> float | None:
    if value is None:
        return None
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError("retry_after_seconds cannot be negative")
    if normalized > MAX_RETRY_AFTER_SECONDS:
        raise ValueError("retry_after_seconds exceeds the bounded size")
    return normalized


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _scope_values(scope: ExactScope) -> dict[str, str]:
    return {
        "tenant_ref": _required_text(scope.tenant_ref, "tenant_ref", 160),
        "entity_ref": _required_text(scope.entity_ref, "entity_ref", 160),
        "store_ref": _required_text(scope.store_ref, "store_ref", 160),
    }


def _registration_values(
    scope: ExactScope,
    registration: TeamAgentTaskRegistration,
    now: datetime,
) -> dict[str, Any]:
    scope_data = _scope_values(scope)
    session_ref = _required_text(registration.session_ref, "session_ref", 160)
    task_ref = _required_text(registration.task_ref, "task_ref", 160)
    idempotency_key = _required_text(
        registration.idempotency_key,
        "idempotency_key",
        300,
    )
    if registration.max_attempts < 1 or registration.max_attempts > MAX_ATTEMPTS:
        raise ValueError("max_attempts must be between 1 and 3")
    payload = _payload(registration.payload)
    request = {
        **scope_data,
        "session_ref": session_ref,
        "task_ref": task_ref,
        "idempotency_key": idempotency_key,
        "payload": payload,
        "max_attempts": registration.max_attempts,
    }
    return {
        **scope_data,
        "session_ref": session_ref,
        "task_ref": task_ref,
        "idempotency_key": idempotency_key,
        "request_sha256": _sha256(request),
        "payload_json": payload,
        "state": DurableTaskState.QUEUED.value,
        "claimed_by": None,
        "lease_ref": None,
        "lease_expires_at": None,
        "attempt_count": 0,
        "max_attempts": registration.max_attempts,
        "retry_wait_until": None,
        "retry_after_seconds": None,
        "paused_retry_wait_until": None,
        "paused_retry_after_seconds": None,
        "reviewer_id": None,
        "result_json": None,
        "evidence_refs_json": [],
        "failure_code": None,
        "failure_kind": None,
        "blocked_reason": None,
        "revision": 0,
        "completed_at": None,
        "expired_at": None,
        "created_at": now,
        "updated_at": now,
    }


def _task_key(
    scope: ExactScope,
    session_ref: str,
    task_ref: str,
) -> tuple[str, str, str, str, str]:
    values = _scope_values(scope)
    return (
        values["tenant_ref"],
        values["entity_ref"],
        values["store_ref"],
        _required_text(session_ref, "session_ref", 160),
        _required_text(task_ref, "task_ref", 160),
    )


def _task_from_mapping(row: Mapping[str, Any]) -> PersistedTeamAgentTask:
    return PersistedTeamAgentTask(
        scope=ExactScope(row["tenant_ref"], row["entity_ref"], row["store_ref"]),
        session_ref=row["session_ref"],
        task_ref=row["task_ref"],
        idempotency_key=row["idempotency_key"],
        request_sha256=row["request_sha256"],
        payload=_payload(row["payload_json"]),
        state=DurableTaskState(row["state"]),
        claimed_by=row["claimed_by"],
        lease_ref=row["lease_ref"],
        lease_expires_at=_utc(row["lease_expires_at"])
        if row["lease_expires_at"] is not None
        else None,
        attempt_count=int(row["attempt_count"]),
        max_attempts=int(row["max_attempts"]),
        retry_wait_until=_utc(row["retry_wait_until"])
        if row["retry_wait_until"] is not None
        else None,
        retry_after_seconds=(
            float(row["retry_after_seconds"])
            if row["retry_after_seconds"] is not None
            else None
        ),
        paused_retry_wait_until=(
            _utc(row["paused_retry_wait_until"])
            if row.get("paused_retry_wait_until") is not None
            else None
        ),
        paused_retry_after_seconds=(
            float(row["paused_retry_after_seconds"])
            if row.get("paused_retry_after_seconds") is not None
            else None
        ),
        reviewer_id=row.get("reviewer_id"),
        result=(
            _result(row["result_json"])
            if row.get("result_json") is not None
            else None
        ),
        evidence_refs=_evidence_refs(row.get("evidence_refs_json")),
        failure_code=row.get("failure_code"),
        failure_kind=row.get("failure_kind"),
        blocked_reason=row.get("blocked_reason"),
        revision=int(row["revision"]),
        completed_at=_utc(row["completed_at"]) if row.get("completed_at") is not None else None,
        expired_at=_utc(row["expired_at"]) if row.get("expired_at") is not None else None,
        created_at=_utc(row["created_at"]),
        updated_at=_utc(row["updated_at"]),
    )


def _copy_task(task: PersistedTeamAgentTask) -> PersistedTeamAgentTask:
    return replace(
        task,
        payload=_payload(task.payload),
        result=_result(task.result) if task.result is not None else None,
    )


def _serialized_task(task: PersistedTeamAgentTask) -> dict[str, Any]:
    return {
        "task_ref": task.task_ref,
        "idempotency_key": task.idempotency_key,
        "request_sha256": task.request_sha256,
        "payload": task.payload,
        "state": task.state.value,
        "claimed_by": task.claimed_by,
        "lease_ref": task.lease_ref,
        "lease_expires_at": task.lease_expires_at.isoformat()
        if task.lease_expires_at
        else None,
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
        "retry_wait_until": task.retry_wait_until.isoformat()
        if task.retry_wait_until
        else None,
        "retry_after_seconds": task.retry_after_seconds,
        "paused_retry_wait_until": task.paused_retry_wait_until.isoformat()
        if task.paused_retry_wait_until
        else None,
        "paused_retry_after_seconds": task.paused_retry_after_seconds,
        "reviewer_id": task.reviewer_id,
        "result": task.result,
        "evidence_refs": list(task.evidence_refs),
        "failure_code": task.failure_code,
        "failure_kind": task.failure_kind,
        "blocked_reason": task.blocked_reason,
        "revision": task.revision,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "expired_at": task.expired_at.isoformat() if task.expired_at else None,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
    }


def _checkpoint(
    *,
    scope: ExactScope,
    session_ref: str,
    tasks: list[PersistedTeamAgentTask],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    _assert_checkpoint_conservation(tasks, events)
    payload = {
        "contract_id": CONTRACT_ID,
        "scope": _scope_values(scope),
        "session_ref": _required_text(session_ref, "session_ref", 160),
        "tasks": [_serialized_task(task) for task in tasks],
        "events": events,
    }
    payload["checkpoint_sha256"] = _sha256(payload)
    return payload


def _assert_checkpoint_conservation(
    tasks: Sequence[PersistedTeamAgentTask],
    events: Sequence[Mapping[str, Any]],
) -> None:
    tasks_by_ref = {task.task_ref: task for task in tasks}
    events_by_task: dict[str, list[Mapping[str, Any]]] = {}
    for event in events:
        task_ref = str(event.get("task_ref") or "")
        if task_ref not in tasks_by_ref:
            raise TeamAgentPersistenceConflict(
                "checkpoint event references an unknown task"
            )
        events_by_task.setdefault(task_ref, []).append(event)
    if set(events_by_task) != set(tasks_by_ref):
        raise TeamAgentPersistenceConflict(
            "checkpoint task/event set is not conserved"
        )
    for task_ref, task in tasks_by_ref.items():
        task_events = sorted(
            events_by_task[task_ref],
            key=lambda event: int(event["task_revision"]),
        )
        revisions = [int(event["task_revision"]) for event in task_events]
        if revisions != list(range(task.revision + 1)):
            raise TeamAgentPersistenceConflict(
                "checkpoint task revision history is not conserved"
            )
        tail = task_events[-1]
        tail_payload = tail.get("payload")
        if (
            not isinstance(tail_payload, Mapping)
            or tail_payload.get("state") != task.state.value
        ):
            raise TeamAgentPersistenceConflict(
                "checkpoint task state and event tail conflict"
            )


def _assert_claimable(task: PersistedTeamAgentTask, now: datetime) -> None:
    if task.state is DurableTaskState.RUNNING:
        if task.lease_expires_at is not None and task.lease_expires_at <= now:
            pass
        else:
            raise TeamAgentPersistenceConflict("task already has an active lease")
    elif task.state is DurableTaskState.RETRY_WAIT:
        if task.retry_wait_until is None or task.retry_wait_until > now:
            raise TeamAgentPersistenceConflict("task is waiting for retry")
    elif task.state not in {DurableTaskState.QUEUED, DurableTaskState.EXPIRED}:
        raise TeamAgentPersistenceConflict("task is not claimable")
    if task.attempt_count >= task.max_attempts:
        raise TeamAgentPersistenceConflict("task retry budget is exhausted")


def _event_payload(
    task: PersistedTeamAgentTask,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base = {
        "request_sha256": task.request_sha256,
        "state": task.state.value,
    }
    if payload:
        base.update(dict(payload))
    return _json_object(base, field_name="event_payload", maximum_bytes=MAX_TEXT_BYTES)


def _failed_state(value: DurableTaskState | str) -> DurableTaskState:
    normalized = DurableTaskState(value)
    if normalized not in {
        DurableTaskState.FAILED,
        DurableTaskState.RETRY_WAIT,
        DurableTaskState.BLOCKED,
    }:
        raise ValueError("next_state must be failed, retry_wait, or blocked")
    return normalized


def _expiry_outcome(
    task: PersistedTeamAgentTask,
    *,
    next_state: DurableTaskState | str | None,
    blocked_reason: str | None,
) -> tuple[DurableTaskState, str]:
    default_state = (
        DurableTaskState.BLOCKED
        if task.attempt_count >= task.max_attempts
        else DurableTaskState.EXPIRED
    )
    state = default_state if next_state is None else DurableTaskState(next_state)
    if state not in {DurableTaskState.EXPIRED, DurableTaskState.BLOCKED}:
        raise ValueError("expired lease next_state must be expired or blocked")
    reason = (
        _required_text(blocked_reason, "blocked_reason", 500)
        if blocked_reason is not None
        else (
            "retry_budget_exhausted"
            if state is DurableTaskState.BLOCKED
            else "lease_expired"
        )
    )
    if state is DurableTaskState.EXPIRED and reason != "lease_expired":
        raise TeamAgentPersistenceConflict(
            "expired task requires lease_expired reason"
        )
    if state is DurableTaskState.BLOCKED:
        if reason not in {"retry_budget_exhausted", "time_budget_exhausted"}:
            raise TeamAgentPersistenceConflict(
                "blocked expiry reason is not a terminal budget condition"
            )
        if (
            reason == "retry_budget_exhausted"
            and task.attempt_count < task.max_attempts
        ):
            raise TeamAgentPersistenceConflict(
                "retry budget is not exhausted"
            )
    return state, reason


def _unleased_block_reason(task: PersistedTeamAgentTask, reason: str) -> str:
    normalized = _required_text(reason, "reason", 500)
    if normalized not in {"retry_budget_exhausted", "time_budget_exhausted"}:
        raise TeamAgentPersistenceConflict(
            "unleased task can only close for an exhausted budget"
        )
    if (
        normalized == "retry_budget_exhausted"
        and task.attempt_count < task.max_attempts
    ):
        raise TeamAgentPersistenceConflict("retry budget is not exhausted")
    return normalized


def _retry_schedule(
    *,
    state: DurableTaskState,
    retry_wait_until: datetime | None,
    retry_after_seconds: float | None,
    now: datetime,
) -> tuple[datetime | None, float | None]:
    if state is not DurableTaskState.RETRY_WAIT:
        return None, None
    retry_at = _utc(retry_wait_until) if retry_wait_until is not None else None
    if retry_at is None or retry_at <= now:
        raise ValueError("retry_wait_until must be in the future")
    retry_after = _retry_after_seconds(retry_after_seconds)
    delay = (
        retry_after
        if retry_after is not None
        else (retry_at - now).total_seconds()
    )
    delay = min(MAX_RETRY_AFTER_SECONDS, delay)
    return now + timedelta(seconds=delay), delay


def _assert_completion_policy(
    task: PersistedTeamAgentTask,
    *,
    worker_id: str,
    evidence_refs: Sequence[str],
    reviewer_id: str | None,
) -> None:
    payload = task.payload
    evidence_required = payload.get(
        "requires_evidence",
        payload.get("evidence_required", False),
    )
    if not isinstance(evidence_required, bool):
        raise TeamAgentPersistenceConflict(
            "completion Evidence policy is invalid"
        )
    if evidence_required and not evidence_refs:
        raise TeamAgentPersistenceConflict(
            "completion requires Evidence"
        )
    reviewer_required = any(
        payload.get(key) is not None
        for key in ("reviewer_role", "reviewer_agent_id", "reviewer_required")
    )
    if reviewer_required and reviewer_id is None:
        raise TeamAgentPersistenceConflict(
            "completion requires an independent reviewer"
        )
    if reviewer_id is not None:
        author_id = payload.get("agent_id")
        if reviewer_id in {worker_id, author_id}:
            raise TeamAgentPersistenceConflict(
                "completion reviewer must be independent"
            )


class InMemoryTeamAgentPersistence:
    """Deterministic adapter with the same observable lease semantics as PostgreSQL."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str, str, str], PersistedTeamAgentTask] = {}
        self._idempotency: dict[tuple[str, str, str, str, str], tuple[str, str, str, str, str]] = {}
        self._events: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def register_task(
        self,
        *,
        scope: ExactScope,
        task: TeamAgentTaskRegistration,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        values = _registration_values(scope, task, now)
        key = _task_key(scope, values["session_ref"], values["task_ref"])
        idempotency_key = (*key[:4], values["idempotency_key"])
        with self._lock:
            existing_key = self._idempotency.get(idempotency_key)
            if existing_key is not None:
                existing = self._rows[existing_key]
                if existing.request_sha256 != values["request_sha256"]:
                    raise TeamAgentPersistenceConflict("idempotency key payload conflict")
                return _copy_task(existing)
            existing = self._rows.get(key)
            if existing is not None:
                if existing.request_sha256 != values["request_sha256"]:
                    raise TeamAgentPersistenceConflict("task identity payload conflict")
                return _copy_task(existing)
            persisted = _task_from_mapping(values)
            self._rows[key] = persisted
            self._idempotency[idempotency_key] = key
            self._append_event(persisted, "registered", worker_id=None, lease_ref=None)
            return _copy_task(persisted)

    def task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
    ) -> PersistedTeamAgentTask:
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            try:
                return _copy_task(self._rows[key])
            except KeyError as exc:
                raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope") from exc

    def claim_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_seconds: int,
        lease_ref: str | None = None,
        lease_expires_at: datetime | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        worker = _required_text(worker_id, "worker_id", 240)
        requested_lease = (
            _required_text(lease_ref, "lease_ref", 80)
            if lease_ref is not None
            else None
        )
        if lease_seconds < 1 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        claimed_expiry = (
            _utc(lease_expires_at)
            if lease_expires_at is not None
            else now + timedelta(seconds=lease_seconds)
        )
        if claimed_expiry <= now or claimed_expiry > now + timedelta(
            seconds=lease_seconds
        ):
            raise ValueError("lease_expires_at is outside the requested lease window")
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            if (
                current.state is DurableTaskState.RUNNING
                and current.claimed_by == worker
                and current.lease_expires_at is not None
                and current.lease_expires_at > now
            ):
                if requested_lease is not None and current.lease_ref != requested_lease:
                    raise TeamAgentPersistenceConflict(
                        "active task lease identity conflicts with requested lease_ref"
                    )
                return _copy_task(current)
            _assert_monotonic_update(current, now)
            _assert_claimable(current, now)
            claimed = replace(
                current,
                state=DurableTaskState.RUNNING,
                claimed_by=worker,
                lease_ref=requested_lease or f"tal_{uuid4().hex}",
                lease_expires_at=claimed_expiry,
                attempt_count=current.attempt_count + 1,
                retry_wait_until=None,
                retry_after_seconds=None,
                reviewer_id=None,
                result=None,
                evidence_refs=(),
                failure_code=None,
                failure_kind=None,
                blocked_reason=None,
                completed_at=None,
                expired_at=None,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = claimed
            self._append_event(
                claimed,
                "claimed",
                worker_id=worker,
                lease_ref=claimed.lease_ref,
            )
            return _copy_task(claimed)

    def heartbeat_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        extend_seconds: int,
        lease_expires_at: datetime | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        worker = _required_text(worker_id, "worker_id", 240)
        lease = _required_text(lease_ref, "lease_ref", 80)
        if extend_seconds < 1 or extend_seconds > 3600:
            raise ValueError("extend_seconds must be between 1 and 3600")
        requested_expiry = (
            _utc(lease_expires_at)
            if lease_expires_at is not None
            else now + timedelta(seconds=extend_seconds)
        )
        if requested_expiry <= now or requested_expiry > now + timedelta(
            seconds=extend_seconds
        ):
            raise ValueError("lease_expires_at is outside the requested lease window")
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            _assert_monotonic_update(current, now)
            self._assert_active_lease(current, worker, lease, now)
            heartbeat = replace(
                current,
                lease_expires_at=requested_expiry,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = heartbeat
            self._append_event(heartbeat, "heartbeat", worker_id=worker, lease_ref=lease)
            return _copy_task(heartbeat)

    def release_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        worker = _required_text(worker_id, "worker_id", 240)
        lease = _required_text(lease_ref, "lease_ref", 80)
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            _assert_monotonic_update(current, now)
            self._assert_active_lease(current, worker, lease, now)
            released = replace(
                current,
                state=DurableTaskState.QUEUED,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                retry_wait_until=None,
                retry_after_seconds=None,
                blocked_reason=None,
                expired_at=None,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = released
            self._append_event(released, "released", worker_id=worker, lease_ref=lease)
            return _copy_task(released)

    def complete_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        result: Mapping[str, Any],
        evidence_refs: Sequence[str] = (),
        reviewer_id: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        worker = _required_text(worker_id, "worker_id", 240)
        lease = _required_text(lease_ref, "lease_ref", 80)
        normalized_result = _result(result)
        normalized_evidence = _evidence_refs(evidence_refs)
        reviewer = (
            _required_text(reviewer_id, "reviewer_id", 240)
            if reviewer_id is not None
            else None
        )
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            if current.state is DurableTaskState.COMPLETED:
                expected_payload = _event_payload(
                    current,
                    {
                        "reviewer_id": reviewer,
                        "result_sha256": _sha256(normalized_result),
                        "evidence_ref_count": len(normalized_evidence),
                        "evidence_refs_sha256": _sha256(
                            {"evidence_refs": normalized_evidence}
                        ),
                    },
                )
                replay = next(
                    (
                        event
                        for event in reversed(self._events)
                        if event["task_ref"] == task_ref
                        and event["tenant_ref"] == scope.tenant_ref
                        and event["entity_ref"] == scope.entity_ref
                        and event["store_ref"] == scope.store_ref
                        and event["session_ref"] == session_ref
                        and event["task_revision"] == current.revision
                    ),
                    None,
                )
                if (
                    replay is not None
                    and replay["event_type"] == "completed"
                    and replay["worker_id"] == worker
                    and replay["lease_ref"] == lease
                    and replay["payload"] == expected_payload
                ):
                    return _copy_task(current)
                raise TeamAgentReplayConflict("completion replay conflict")
            _assert_monotonic_update(current, now)
            self._assert_active_lease(current, worker, lease, now)
            _assert_completion_policy(
                current,
                worker_id=worker,
                evidence_refs=normalized_evidence,
                reviewer_id=reviewer,
            )
            completed = replace(
                current,
                state=DurableTaskState.COMPLETED,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                retry_wait_until=None,
                retry_after_seconds=None,
                reviewer_id=reviewer,
                result=normalized_result,
                evidence_refs=normalized_evidence,
                failure_code=None,
                failure_kind=None,
                blocked_reason=None,
                completed_at=now,
                expired_at=None,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = completed
            self._append_event(
                completed,
                "completed",
                worker_id=worker,
                lease_ref=lease,
                payload={
                    "reviewer_id": reviewer,
                    "result_sha256": _sha256(normalized_result),
                    "evidence_ref_count": len(normalized_evidence),
                    "evidence_refs_sha256": _sha256({"evidence_refs": normalized_evidence}),
                },
            )
            return _copy_task(completed)

    def fail_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        failure_code: str,
        failure_kind: str,
        next_state: DurableTaskState | str = DurableTaskState.FAILED,
        retry_wait_until: datetime | None = None,
        retry_after_seconds: float | None = None,
        blocked_reason: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        worker = _required_text(worker_id, "worker_id", 240)
        lease = _required_text(lease_ref, "lease_ref", 80)
        code = _required_text(failure_code, "failure_code", 120)
        kind = _required_text(failure_kind, "failure_kind", 120)
        state = _failed_state(next_state)
        if state in {
            DurableTaskState.FAILED,
            DurableTaskState.RETRY_WAIT,
            DurableTaskState.BLOCKED,
        }:
            with self._lock:
                current = self.task(
                    scope=scope, session_ref=session_ref, task_ref=task_ref
                )
                replay = next(
                    (
                        event
                        for event in reversed(self._events)
                        if event["task_ref"] == task_ref
                        and event["tenant_ref"] == scope.tenant_ref
                        and event["entity_ref"] == scope.entity_ref
                        and event["store_ref"] == scope.store_ref
                        and event["session_ref"] == session_ref
                        and event["task_revision"] == current.revision
                    ),
                    None,
                )
                if (
                    current.state is state
                    and replay is not None
                    and replay["event_type"] == state.value
                    and replay["worker_id"] == worker
                    and replay["lease_ref"] == lease
                    and replay["payload"].get("failure_code") == code
                    and replay["payload"].get("failure_kind") == kind
                    and (
                        retry_after_seconds is None
                        or replay["payload"].get("retry_after_seconds")
                        == float(retry_after_seconds)
                    )
                    and (
                        retry_wait_until is None
                        or replay["payload"].get("retry_wait_until")
                        == _utc(retry_wait_until).isoformat()
                    )
                    and (
                        retry_after_seconds is None
                        or current.retry_after_seconds == float(retry_after_seconds)
                    )
                    and replay["payload"].get("blocked_reason")
                    == current.blocked_reason
                ):
                    return _copy_task(current)
        retry_at, retry_after = _retry_schedule(
            state=state,
            retry_wait_until=retry_wait_until,
            retry_after_seconds=retry_after_seconds,
            now=now,
        )
        reason = (
            _required_text(blocked_reason, "blocked_reason", 500)
            if blocked_reason is not None
            else ("retry_budget_exhausted" if state is DurableTaskState.BLOCKED else None)
        )
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            _assert_monotonic_update(current, now)
            self._assert_active_lease(current, worker, lease, now)
            if (
                state is DurableTaskState.RETRY_WAIT
                and current.attempt_count >= current.max_attempts
            ):
                raise TeamAgentPersistenceConflict("task retry budget is exhausted")
            failed = replace(
                current,
                state=state,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                retry_wait_until=retry_at,
                retry_after_seconds=retry_after,
                failure_code=code,
                failure_kind=kind,
                blocked_reason=reason,
                result=None,
                reviewer_id=None,
                evidence_refs=(),
                completed_at=None,
                expired_at=None,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = failed
            self._append_event(
                failed,
                state.value,
                worker_id=worker,
                lease_ref=lease,
                payload={
                    "failure_code": code,
                    "failure_kind": kind,
                    "retry_after_seconds": retry_after,
                    "retry_wait_until": retry_at.isoformat() if retry_at else None,
                    "blocked_reason": reason,
                },
            )
            return _copy_task(failed)

    def pause_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        worker_id: str | None = None,
        lease_ref: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        paused_reason = _required_text(reason, "reason", 500)
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            _assert_monotonic_update(current, now)
            if current.state is DurableTaskState.RUNNING:
                if worker_id is None or lease_ref is None:
                    raise TeamAgentPersistenceConflict("running task pause requires active lease")
                self._assert_active_lease(
                    current,
                    _required_text(worker_id, "worker_id", 240),
                    _required_text(lease_ref, "lease_ref", 80),
                    now,
                )
                event_worker = worker_id
                event_lease = lease_ref
            elif current.state not in {
                DurableTaskState.QUEUED,
                DurableTaskState.RETRY_WAIT,
                DurableTaskState.BLOCKED,
                DurableTaskState.EXPIRED,
            }:
                raise TeamAgentPersistenceConflict("task is not pausable")
            else:
                event_worker = None
                event_lease = None
            preserve_retry = current.state is DurableTaskState.RETRY_WAIT
            paused = replace(
                current,
                state=DurableTaskState.PAUSED,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                retry_wait_until=(current.retry_wait_until if preserve_retry else None),
                retry_after_seconds=(
                    current.retry_after_seconds if preserve_retry else None
                ),
                blocked_reason=paused_reason,
                completed_at=None,
                expired_at=None,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = paused
            self._append_event(
                paused,
                "paused",
                worker_id=event_worker,
                lease_ref=event_lease,
                payload={"blocked_reason": paused_reason},
            )
            return _copy_task(paused)

    def resume_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            _assert_monotonic_update(current, now)
            if current.state is not DurableTaskState.PAUSED:
                raise TeamAgentPersistenceConflict("task is not paused")
            retry_waiting = (
                current.retry_wait_until is not None
                and current.retry_wait_until > now
            )
            resumed = replace(
                current,
                state=(
                    DurableTaskState.RETRY_WAIT
                    if retry_waiting
                    else DurableTaskState.QUEUED
                ),
                retry_wait_until=(current.retry_wait_until if retry_waiting else None),
                retry_after_seconds=(
                    current.retry_after_seconds if retry_waiting else None
                ),
                blocked_reason=None,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = resumed
            self._append_event(
                resumed,
                "resumed",
                worker_id=None,
                lease_ref=None,
                payload={"resumed_state": resumed.state.value},
            )
            return _copy_task(resumed)

    def revoke_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        revoked_reason = _required_text(reason, "reason", 500)
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            _assert_monotonic_update(current, now)
            if current.state is not DurableTaskState.RUNNING:
                raise TeamAgentPersistenceConflict("only a running task can be revoked")
            revoked = replace(
                current,
                state=DurableTaskState.EXPIRED,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                retry_wait_until=None,
                retry_after_seconds=None,
                blocked_reason=revoked_reason,
                completed_at=None,
                expired_at=now,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = revoked
            self._append_event(
                revoked,
                "expired",
                worker_id=current.claimed_by,
                lease_ref=current.lease_ref,
                payload={"blocked_reason": revoked_reason, "revoked": True},
            )
            return _copy_task(revoked)

    def block_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(
                scope=scope,
                session_ref=session_ref,
                task_ref=task_ref,
            )
            _assert_monotonic_update(current, now)
            if current.state not in {
                DurableTaskState.QUEUED,
                DurableTaskState.RETRY_WAIT,
                DurableTaskState.EXPIRED,
            }:
                raise TeamAgentPersistenceConflict("task is not unleased and blockable")
            terminal_reason = _unleased_block_reason(current, reason)
            blocked = replace(
                current,
                state=DurableTaskState.BLOCKED,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                retry_wait_until=None,
                retry_after_seconds=None,
                blocked_reason=terminal_reason,
                completed_at=None,
                expired_at=None,
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = blocked
            self._append_event(
                blocked,
                "blocked",
                worker_id=None,
                lease_ref=None,
                payload={"blocked_reason": terminal_reason},
            )
            return _copy_task(blocked)

    def expire_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        next_state: DurableTaskState | str | None = None,
        blocked_reason: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        key = _task_key(scope, session_ref, task_ref)
        with self._lock:
            current = self.task(scope=scope, session_ref=session_ref, task_ref=task_ref)
            _assert_monotonic_update(current, now)
            if (
                current.state is not DurableTaskState.RUNNING
                or current.lease_expires_at is None
                or current.lease_expires_at > now
            ):
                raise TeamAgentPersistenceConflict("task lease is not expired")
            expired_state, terminal_reason = _expiry_outcome(
                current,
                next_state=next_state,
                blocked_reason=blocked_reason,
            )
            expired = replace(
                current,
                state=expired_state,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                retry_wait_until=None,
                retry_after_seconds=None,
                blocked_reason=terminal_reason,
                completed_at=None,
                expired_at=(
                    now if expired_state is DurableTaskState.EXPIRED else None
                ),
                revision=current.revision + 1,
                updated_at=now,
            )
            self._rows[key] = expired
            self._append_event(
                expired,
                expired_state.value,
                worker_id=current.claimed_by,
                lease_ref=current.lease_ref,
                payload={
                    "blocked_reason": expired.blocked_reason,
                    "previous_lease_expires_at": current.lease_expires_at.isoformat(),
                },
            )
            return _copy_task(expired)

    def checkpoint(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
    ) -> dict[str, Any]:
        session = _required_text(session_ref, "session_ref", 160)
        scope_key = tuple(_scope_values(scope).values())
        with self._lock:
            tasks = sorted(
                (
                    task
                    for key, task in self._rows.items()
                    if key[:3] == scope_key and key[3] == session
                ),
                key=lambda item: item.task_ref,
            )
            events = [
                dict(event)
                for event in self._events
                if (
                    event["tenant_ref"],
                    event["entity_ref"],
                    event["store_ref"],
                    event["session_ref"],
                )
                == (*scope_key, session)
            ]
            return _checkpoint(
                scope=scope,
                session_ref=session,
                tasks=tasks,
                events=events,
            )

    def _append_event(
        self,
        task: PersistedTeamAgentTask,
        event_type: str,
        *,
        worker_id: str | None,
        lease_ref: str | None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self._events.append(
            {
                "event_id": len(self._events) + 1,
                "tenant_ref": task.scope.tenant_ref,
                "entity_ref": task.scope.entity_ref,
                "store_ref": task.scope.store_ref,
                "session_ref": task.session_ref,
                "task_ref": task.task_ref,
                "task_revision": task.revision,
                "event_type": event_type,
                "worker_id": worker_id,
                "lease_ref": lease_ref,
                "payload": _event_payload(task, payload),
                "occurred_at": task.updated_at.isoformat(),
            }
        )

    @staticmethod
    def _assert_active_lease(
        task: PersistedTeamAgentTask,
        worker_id: str,
        lease_ref: str,
        now: datetime,
    ) -> None:
        if (
            task.state is not DurableTaskState.RUNNING
            or task.claimed_by != worker_id
            or task.lease_ref != lease_ref
            or task.lease_expires_at is None
            or task.lease_expires_at <= now
        ):
            raise TeamAgentPersistenceConflict("active task lease does not match")


def _assert_monotonic_update(
    task: PersistedTeamAgentTask,
    now: datetime,
) -> None:
    """Reject caller clocks that would make the task/event chain go backward."""

    if now < task.updated_at:
        raise TeamAgentPersistenceConflict(
            "task mutation timestamp regresses updated_at"
        )


class PostgresTeamAgentPersistence:
    """PostgreSQL adapter with revision-and-lease guarded task transitions."""

    def __init__(
        self,
        engine: Engine,
        *,
        connection: Connection | None = None,
    ) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgresTeamAgentPersistence requires PostgreSQL")
        if connection is not None and connection.engine is not engine:
            raise ValueError("TeamAgent persistence connection belongs to another engine")
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

    def register_task(
        self,
        *,
        scope: ExactScope,
        task: TeamAgentTaskRegistration,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        values = _registration_values(scope, task, now)
        with self._begin() as connection:
            inserted = connection.execute(
                postgresql_insert(team_agent_tasks)
                .values(**values)
                .on_conflict_do_nothing()
                .returning(*team_agent_tasks.c)
            ).mappings().one_or_none()
            if inserted is not None:
                persisted = _task_from_mapping(inserted)
                self._append_event(
                    connection,
                    persisted,
                    "registered",
                    worker_id=None,
                    lease_ref=None,
                )
                return _copy_task(persisted)
            existing = connection.execute(
                select(team_agent_tasks).where(
                    *self._scope_predicates(scope),
                    team_agent_tasks.c.session_ref == values["session_ref"],
                    team_agent_tasks.c.idempotency_key == values["idempotency_key"],
                )
            ).mappings().one_or_none()
            if existing is None:
                existing = connection.execute(
                    select(team_agent_tasks).where(
                        *self._task_predicates(
                            scope,
                            values["session_ref"],
                            values["task_ref"],
                        )
                    )
                ).mappings().one_or_none()
            if existing is None:
                raise TeamAgentPersistenceConflict("task registration lost its conflict winner")
            persisted = _task_from_mapping(existing)
            if persisted.request_sha256 != values["request_sha256"]:
                raise TeamAgentPersistenceConflict("idempotency or task payload conflict")
            return _copy_task(persisted)

    def task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
    ) -> PersistedTeamAgentTask:
        with self._connect() as connection:
            row = connection.execute(
                select(team_agent_tasks).where(
                    *self._task_predicates(scope, session_ref, task_ref)
                )
            ).mappings().one_or_none()
        if row is None:
            raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope")
        return _copy_task(_task_from_mapping(row))

    def claim_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_seconds: int,
        lease_ref: str | None = None,
        lease_expires_at: datetime | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        worker = _required_text(worker_id, "worker_id", 240)
        requested_lease = (
            _required_text(lease_ref, "lease_ref", 80)
            if lease_ref is not None
            else None
        )
        if lease_seconds < 1 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        claimed_expiry = (
            _utc(lease_expires_at)
            if lease_expires_at is not None
            else now + timedelta(seconds=lease_seconds)
        )
        if claimed_expiry <= now or claimed_expiry > now + timedelta(
            seconds=lease_seconds
        ):
            raise ValueError("lease_expires_at is outside the requested lease window")
        with self._begin() as connection:
            current_row = connection.execute(
                select(team_agent_tasks).where(
                    *self._task_predicates(scope, session_ref, task_ref)
                )
            ).mappings().one_or_none()
            if current_row is None:
                raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope")
            current = _task_from_mapping(current_row)
            if (
                current.state is DurableTaskState.RUNNING
                and current.claimed_by == worker
                and current.lease_expires_at is not None
                and current.lease_expires_at > now
            ):
                if requested_lease is not None and current.lease_ref != requested_lease:
                    raise TeamAgentPersistenceConflict(
                        "active task lease identity conflicts with requested lease_ref"
                    )
                return _copy_task(current)
            _assert_claimable(current, now)
            claimed_lease_ref = requested_lease or f"tal_{uuid4().hex}"
            claimable = or_(
                team_agent_tasks.c.state.in_(
                    [DurableTaskState.QUEUED.value, DurableTaskState.EXPIRED.value]
                ),
                and_(
                    team_agent_tasks.c.state == DurableTaskState.RETRY_WAIT.value,
                    team_agent_tasks.c.retry_wait_until <= now,
                ),
                and_(
                    team_agent_tasks.c.state == DurableTaskState.RUNNING.value,
                    team_agent_tasks.c.lease_expires_at <= now,
                ),
            )
            claimed_row = connection.execute(
                update(team_agent_tasks)
                .where(
                    *self._task_predicates(scope, session_ref, task_ref),
                    team_agent_tasks.c.revision == current.revision,
                    team_agent_tasks.c.updated_at <= now,
                    team_agent_tasks.c.attempt_count < team_agent_tasks.c.max_attempts,
                    claimable,
                )
                .values(
                    state=DurableTaskState.RUNNING.value,
                    claimed_by=worker,
                    lease_ref=claimed_lease_ref,
                    lease_expires_at=claimed_expiry,
                    attempt_count=team_agent_tasks.c.attempt_count + 1,
                    retry_wait_until=None,
                    retry_after_seconds=None,
                    paused_retry_wait_until=None,
                    paused_retry_after_seconds=None,
                    reviewer_id=None,
                    result_json=None,
                    evidence_refs_json=[],
                    failure_code=None,
                    failure_kind=None,
                    blocked_reason=None,
                    completed_at=None,
                    expired_at=None,
                    revision=team_agent_tasks.c.revision + 1,
                    updated_at=now,
                )
                .returning(*team_agent_tasks.c)
            ).mappings().one_or_none()
            if claimed_row is None:
                winner_row = connection.execute(
                    select(team_agent_tasks).where(
                        *self._task_predicates(
                            scope,
                            session_ref,
                            task_ref,
                        )
                    )
                ).mappings().one_or_none()
                if winner_row is not None:
                    winner = _task_from_mapping(winner_row)
                    if (
                        winner.state is DurableTaskState.RUNNING
                        and winner.claimed_by == worker
                        and winner.lease_expires_at is not None
                        and winner.lease_expires_at > now
                    ):
                        if (
                            requested_lease is not None
                            and winner.lease_ref != requested_lease
                        ):
                            raise TeamAgentPersistenceConflict(
                                "active task lease identity conflicts with requested lease_ref"
                            )
                        return _copy_task(winner)
                raise TeamAgentPersistenceConflict("task claim compare-and-swap lost")
            claimed = _task_from_mapping(claimed_row)
            self._append_event(
                connection,
                claimed,
                "claimed",
                worker_id=worker,
                lease_ref=claimed_lease_ref,
            )
            return _copy_task(claimed)

    def heartbeat_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        extend_seconds: int,
        lease_expires_at: datetime | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        worker = _required_text(worker_id, "worker_id", 240)
        lease = _required_text(lease_ref, "lease_ref", 80)
        if extend_seconds < 1 or extend_seconds > 3600:
            raise ValueError("extend_seconds must be between 1 and 3600")
        requested_expiry = (
            _utc(lease_expires_at)
            if lease_expires_at is not None
            else now + timedelta(seconds=extend_seconds)
        )
        if requested_expiry <= now or requested_expiry > now + timedelta(
            seconds=extend_seconds
        ):
            raise ValueError("lease_expires_at is outside the requested lease window")
        return self._lease_transition(
            scope=scope,
            session_ref=session_ref,
            task_ref=task_ref,
            worker_id=worker,
            lease_ref=lease,
            now=now,
            event_type="heartbeat",
            values={"lease_expires_at": requested_expiry},
        )

    def release_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        return self._lease_transition(
            scope=scope,
            session_ref=session_ref,
            task_ref=task_ref,
            worker_id=_required_text(worker_id, "worker_id", 240),
            lease_ref=_required_text(lease_ref, "lease_ref", 80),
            now=_utc(as_of),
            event_type="released",
            values={
                "state": DurableTaskState.QUEUED.value,
                "claimed_by": None,
                "lease_ref": None,
                "lease_expires_at": None,
                "retry_wait_until": None,
                "retry_after_seconds": None,
                "blocked_reason": None,
                "expired_at": None,
            },
        )

    def complete_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        result: Mapping[str, Any],
        evidence_refs: Sequence[str] = (),
        reviewer_id: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        normalized_result = _result(result)
        normalized_evidence = _evidence_refs(evidence_refs)
        reviewer = (
            _required_text(reviewer_id, "reviewer_id", 240)
            if reviewer_id is not None
            else None
        )
        return self._lease_transition(
            scope=scope,
            session_ref=session_ref,
            task_ref=task_ref,
            worker_id=_required_text(worker_id, "worker_id", 240),
            lease_ref=_required_text(lease_ref, "lease_ref", 80),
            now=now,
            event_type="completed",
            values={
                "state": DurableTaskState.COMPLETED.value,
                "claimed_by": None,
                "lease_ref": None,
                "lease_expires_at": None,
                "retry_wait_until": None,
                "retry_after_seconds": None,
                "reviewer_id": reviewer,
                "result_json": normalized_result,
                "evidence_refs_json": list(normalized_evidence),
                "failure_code": None,
                "failure_kind": None,
                "blocked_reason": None,
                "completed_at": now,
                "expired_at": None,
            },
            completion_evidence_refs=normalized_evidence,
            completion_reviewer_id=reviewer,
            payload={
                "reviewer_id": reviewer,
                "result_sha256": _sha256(normalized_result),
                "evidence_ref_count": len(normalized_evidence),
                "evidence_refs_sha256": _sha256({"evidence_refs": normalized_evidence}),
            },
        )

    def fail_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        failure_code: str,
        failure_kind: str,
        next_state: DurableTaskState | str = DurableTaskState.FAILED,
        retry_wait_until: datetime | None = None,
        retry_after_seconds: float | None = None,
        blocked_reason: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        code = _required_text(failure_code, "failure_code", 120)
        kind = _required_text(failure_kind, "failure_kind", 120)
        state = _failed_state(next_state)
        worker = _required_text(worker_id, "worker_id", 240)
        lease = _required_text(lease_ref, "lease_ref", 80)
        if state in {
            DurableTaskState.FAILED,
            DurableTaskState.RETRY_WAIT,
            DurableTaskState.BLOCKED,
        }:
            with self._begin() as connection:
                current_row = connection.execute(
                    select(team_agent_tasks).where(
                        *self._task_predicates(scope, session_ref, task_ref)
                    )
                ).mappings().one_or_none()
                if current_row is not None:
                    current = _task_from_mapping(current_row)
                    replay_row = connection.execute(
                        select(team_agent_events).where(
                            *self._event_scope_predicates(scope),
                            team_agent_events.c.session_ref == session_ref,
                            team_agent_events.c.task_ref == task_ref,
                            team_agent_events.c.task_revision == current.revision,
                        )
                    ).mappings().one_or_none()
                    replay_payload = (
                        _payload(replay_row["payload_json"])
                        if replay_row is not None
                        else {}
                    )
                    if (
                        current.state is state
                        and replay_row is not None
                        and replay_row["event_type"] == state.value
                        and replay_row["worker_id"] == worker
                        and replay_row["lease_ref"] == lease
                        and replay_payload.get("failure_code") == code
                        and replay_payload.get("failure_kind") == kind
                        and (
                            retry_after_seconds is None
                            or replay_payload.get("retry_after_seconds")
                            == float(retry_after_seconds)
                        )
                        and (
                            retry_wait_until is None
                            or replay_payload.get("retry_wait_until")
                            == _utc(retry_wait_until).isoformat()
                        )
                        and (
                            retry_after_seconds is None
                            or current.retry_after_seconds == float(retry_after_seconds)
                        )
                        and replay_payload.get("blocked_reason")
                        == current.blocked_reason
                    ):
                        return _copy_task(current)
        retry_at, retry_after = _retry_schedule(
            state=state,
            retry_wait_until=retry_wait_until,
            retry_after_seconds=retry_after_seconds,
            now=now,
        )
        reason = (
            _required_text(blocked_reason, "blocked_reason", 500)
            if blocked_reason is not None
            else ("retry_budget_exhausted" if state is DurableTaskState.BLOCKED else None)
        )
        return self._lease_transition(
            scope=scope,
            session_ref=session_ref,
            task_ref=task_ref,
            worker_id=worker,
            lease_ref=lease,
            now=now,
            event_type=state.value,
            require_retry_budget=state is DurableTaskState.RETRY_WAIT,
            values={
                "state": state.value,
                "claimed_by": None,
                "lease_ref": None,
                "lease_expires_at": None,
                "retry_wait_until": retry_at,
                "retry_after_seconds": retry_after,
                "paused_retry_wait_until": None,
                "paused_retry_after_seconds": None,
                "failure_code": code,
                "failure_kind": kind,
                "blocked_reason": reason,
                "result_json": None,
                "reviewer_id": None,
                "evidence_refs_json": [],
                "completed_at": None,
                "expired_at": None,
            },
            payload={
                "failure_code": code,
                "failure_kind": kind,
                "retry_after_seconds": retry_after,
                "retry_wait_until": retry_at.isoformat() if retry_at else None,
                "blocked_reason": reason,
            },
        )

    def pause_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        worker_id: str | None = None,
        lease_ref: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        paused_reason = _required_text(reason, "reason", 500)
        with self._begin() as connection:
            current_row = connection.execute(
                select(team_agent_tasks).where(
                    *self._task_predicates(scope, session_ref, task_ref)
                )
            ).mappings().one_or_none()
            if current_row is None:
                raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope")
            current = _task_from_mapping(current_row)
            if current.state is DurableTaskState.RUNNING:
                if worker_id is None or lease_ref is None:
                    raise TeamAgentPersistenceConflict("running task pause requires active lease")
                updated_task = self._lease_transition_in_transaction(
                    connection,
                    current=current,
                    scope=scope,
                    session_ref=session_ref,
                    task_ref=task_ref,
                    worker_id=_required_text(worker_id, "worker_id", 240),
                    lease_ref=_required_text(lease_ref, "lease_ref", 80),
                    now=now,
                    event_type="paused",
                    values={
                        "state": DurableTaskState.PAUSED.value,
                        "claimed_by": None,
                        "lease_ref": None,
                        "lease_expires_at": None,
                        "retry_wait_until": None,
                        "retry_after_seconds": None,
                        "paused_retry_wait_until": None,
                        "paused_retry_after_seconds": None,
                        "blocked_reason": paused_reason,
                        "completed_at": None,
                        "expired_at": None,
                    },
                    payload={"blocked_reason": paused_reason},
                )
                return _copy_task(updated_task)
            if current.state not in {
                DurableTaskState.QUEUED,
                DurableTaskState.RETRY_WAIT,
                DurableTaskState.BLOCKED,
                DurableTaskState.EXPIRED,
            }:
                raise TeamAgentPersistenceConflict("task is not pausable")
            preserve_retry = current.state is DurableTaskState.RETRY_WAIT
            updated_row = connection.execute(
                update(team_agent_tasks)
                .where(
                    *self._task_predicates(scope, session_ref, task_ref),
                    team_agent_tasks.c.revision == current.revision,
                    team_agent_tasks.c.updated_at <= now,
                    team_agent_tasks.c.state == current.state.value,
                )
                .values(
                    state=DurableTaskState.PAUSED.value,
                    retry_wait_until=None,
                    retry_after_seconds=None,
                    paused_retry_wait_until=(
                        current.retry_wait_until if preserve_retry else None
                    ),
                    paused_retry_after_seconds=(
                        current.retry_after_seconds if preserve_retry else None
                    ),
                    blocked_reason=paused_reason,
                    completed_at=None,
                    expired_at=None,
                    revision=team_agent_tasks.c.revision + 1,
                    updated_at=now,
                )
                .returning(*team_agent_tasks.c)
            ).mappings().one_or_none()
            if updated_row is None:
                raise TeamAgentPersistenceConflict("task pause compare-and-swap lost")
            paused = _task_from_mapping(updated_row)
            self._append_event(
                connection,
                paused,
                "paused",
                worker_id=None,
                lease_ref=None,
                payload={"blocked_reason": paused_reason},
            )
            return _copy_task(paused)

    def resume_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        with self._begin() as connection:
            current_row = connection.execute(
                select(team_agent_tasks).where(
                    *self._task_predicates(scope, session_ref, task_ref)
                )
            ).mappings().one_or_none()
            if current_row is None:
                raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope")
            current = _task_from_mapping(current_row)
            if current.state is not DurableTaskState.PAUSED:
                raise TeamAgentPersistenceConflict("task is not paused")
            retry_waiting = (
                current.paused_retry_wait_until is not None
                and current.paused_retry_wait_until > now
            )
            resumed_state = (
                DurableTaskState.RETRY_WAIT
                if retry_waiting
                else DurableTaskState.QUEUED
            )
            updated_row = connection.execute(
                update(team_agent_tasks)
                .where(
                    *self._task_predicates(scope, session_ref, task_ref),
                    team_agent_tasks.c.revision == current.revision,
                    team_agent_tasks.c.updated_at <= now,
                    team_agent_tasks.c.state == DurableTaskState.PAUSED.value,
                )
                .values(
                    state=resumed_state.value,
                    retry_wait_until=(
                        current.paused_retry_wait_until if retry_waiting else None
                    ),
                    retry_after_seconds=(
                        current.paused_retry_after_seconds if retry_waiting else None
                    ),
                    paused_retry_wait_until=None,
                    paused_retry_after_seconds=None,
                    blocked_reason=None,
                    revision=team_agent_tasks.c.revision + 1,
                    updated_at=now,
                )
                .returning(*team_agent_tasks.c)
            ).mappings().one_or_none()
            if updated_row is None:
                raise TeamAgentPersistenceConflict("task resume compare-and-swap lost")
            resumed = _task_from_mapping(updated_row)
            self._append_event(
                connection,
                resumed,
                "resumed",
                worker_id=None,
                lease_ref=None,
                payload={"resumed_state": resumed.state.value},
            )
            return _copy_task(resumed)

    def revoke_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        revoked_reason = _required_text(reason, "reason", 500)
        with self._begin() as connection:
            current_row = connection.execute(
                select(team_agent_tasks).where(
                    *self._task_predicates(scope, session_ref, task_ref)
                )
            ).mappings().one_or_none()
            if current_row is None:
                raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope")
            current = _task_from_mapping(current_row)
            if current.state is not DurableTaskState.RUNNING:
                raise TeamAgentPersistenceConflict("only a running task can be revoked")
            updated_row = connection.execute(
                update(team_agent_tasks)
                .where(
                    *self._task_predicates(scope, session_ref, task_ref),
                    team_agent_tasks.c.revision == current.revision,
                    team_agent_tasks.c.updated_at <= now,
                    team_agent_tasks.c.state == DurableTaskState.RUNNING.value,
                    team_agent_tasks.c.claimed_by == current.claimed_by,
                    team_agent_tasks.c.lease_ref == current.lease_ref,
                )
                .values(
                    state=DurableTaskState.EXPIRED.value,
                    claimed_by=None,
                    lease_ref=None,
                    lease_expires_at=None,
                    retry_wait_until=None,
                    retry_after_seconds=None,
                    blocked_reason=revoked_reason,
                    completed_at=None,
                    expired_at=now,
                    revision=team_agent_tasks.c.revision + 1,
                    updated_at=now,
                )
                .returning(*team_agent_tasks.c)
            ).mappings().one_or_none()
            if updated_row is None:
                raise TeamAgentPersistenceConflict("task revoke compare-and-swap lost")
            revoked = _task_from_mapping(updated_row)
            self._append_event(
                connection,
                revoked,
                "expired",
                worker_id=current.claimed_by,
                lease_ref=current.lease_ref,
                payload={"blocked_reason": revoked_reason, "revoked": True},
            )
            return _copy_task(revoked)

    def block_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        reason: str,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        with self._begin() as connection:
            current_row = connection.execute(
                select(team_agent_tasks).where(
                    *self._task_predicates(scope, session_ref, task_ref)
                )
            ).mappings().one_or_none()
            if current_row is None:
                raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope")
            current = _task_from_mapping(current_row)
            if current.state not in {
                DurableTaskState.QUEUED,
                DurableTaskState.RETRY_WAIT,
                DurableTaskState.EXPIRED,
            }:
                raise TeamAgentPersistenceConflict("task is not unleased and blockable")
            terminal_reason = _unleased_block_reason(current, reason)
            updated_row = connection.execute(
                update(team_agent_tasks)
                .where(
                    *self._task_predicates(scope, session_ref, task_ref),
                    team_agent_tasks.c.revision == current.revision,
                    team_agent_tasks.c.updated_at <= now,
                    team_agent_tasks.c.state == current.state.value,
                )
                .values(
                    state=DurableTaskState.BLOCKED.value,
                    claimed_by=None,
                    lease_ref=None,
                    lease_expires_at=None,
                    retry_wait_until=None,
                    retry_after_seconds=None,
                    blocked_reason=terminal_reason,
                    completed_at=None,
                    expired_at=None,
                    revision=team_agent_tasks.c.revision + 1,
                    updated_at=now,
                )
                .returning(*team_agent_tasks.c)
            ).mappings().one_or_none()
            if updated_row is None:
                raise TeamAgentPersistenceConflict("task block compare-and-swap lost")
            blocked = _task_from_mapping(updated_row)
            self._append_event(
                connection,
                blocked,
                "blocked",
                worker_id=None,
                lease_ref=None,
                payload={"blocked_reason": terminal_reason},
            )
            return _copy_task(blocked)

    def expire_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        next_state: DurableTaskState | str | None = None,
        blocked_reason: str | None = None,
        as_of: datetime | None = None,
    ) -> PersistedTeamAgentTask:
        now = _utc(as_of)
        with self._begin() as connection:
            current_row = connection.execute(
                select(team_agent_tasks).where(
                    *self._task_predicates(scope, session_ref, task_ref)
                )
            ).mappings().one_or_none()
            if current_row is None:
                raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope")
            current = _task_from_mapping(current_row)
            if (
                current.state is not DurableTaskState.RUNNING
                or current.lease_expires_at is None
                or current.lease_expires_at > now
            ):
                raise TeamAgentPersistenceConflict("task lease is not expired")
            expired_state, terminal_reason = _expiry_outcome(
                current,
                next_state=next_state,
                blocked_reason=blocked_reason,
            )
            updated_row = connection.execute(
                update(team_agent_tasks)
                .where(
                    *self._task_predicates(scope, session_ref, task_ref),
                    team_agent_tasks.c.revision == current.revision,
                    team_agent_tasks.c.updated_at <= now,
                    team_agent_tasks.c.state == DurableTaskState.RUNNING.value,
                    team_agent_tasks.c.lease_expires_at <= now,
                )
                .values(
                    state=expired_state.value,
                    claimed_by=None,
                    lease_ref=None,
                    lease_expires_at=None,
                    retry_wait_until=None,
                    retry_after_seconds=None,
                    blocked_reason=terminal_reason,
                    completed_at=None,
                    expired_at=(
                        now if expired_state is DurableTaskState.EXPIRED else None
                    ),
                    revision=team_agent_tasks.c.revision + 1,
                    updated_at=now,
                )
                .returning(*team_agent_tasks.c)
            ).mappings().one_or_none()
            if updated_row is None:
                raise TeamAgentPersistenceConflict("task expiry compare-and-swap lost")
            expired = _task_from_mapping(updated_row)
            self._append_event(
                connection,
                expired,
                expired_state.value,
                worker_id=current.claimed_by,
                lease_ref=current.lease_ref,
                payload={
                    "blocked_reason": expired.blocked_reason,
                    "previous_lease_expires_at": current.lease_expires_at.isoformat(),
                },
            )
            return _copy_task(expired)

    def checkpoint(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
    ) -> dict[str, Any]:
        session = _required_text(session_ref, "session_ref", 160)
        if self._connection is not None:
            return self._checkpoint_on_connection(
                self._connection,
                scope=scope,
                session_ref=session,
            )
        with self.engine.connect().execution_options(
            isolation_level="REPEATABLE READ"
        ) as connection, connection.begin():
            return self._checkpoint_on_connection(
                connection,
                scope=scope,
                session_ref=session,
            )

    def _checkpoint_on_connection(
        self,
        connection: Connection,
        *,
        scope: ExactScope,
        session_ref: str,
    ) -> dict[str, Any]:
        # A caller-owned connection may have been created with PostgreSQL's
        # default READ COMMITTED isolation.  The checkpoint is assembled from
        # two relation reads (tasks and events); without one transaction
        # snapshot a concurrent mutation can make the task/event sets tear.
        # Upgrade an as-yet-unused transaction before the first SELECT.  A
        # SQLAlchemy ``begin()`` wrapper is already considered a transaction,
        # so use PostgreSQL's transaction-local SET in that case.  PostgreSQL
        # rejects it after the first statement, which we convert into a
        # fail-closed persistence conflict.  Runtime composition already
        # opens its caller-owned transaction at REPEATABLE READ, so this is a
        # no-op there.  SERIALIZABLE is stronger and must not be downgraded.
        try:
            isolation = str(connection.get_isolation_level()).upper()
        except (AttributeError, InvalidRequestError):
            isolation = ""
        if isolation not in CONSISTENT_SNAPSHOT_ISOLATIONS:
            if connection.in_transaction():
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
                    raise TeamAgentPersistenceConflict(
                        "checkpoint requires a repeatable-read caller transaction"
                    ) from exc
                if effective_isolation not in CONSISTENT_SNAPSHOT_ISOLATIONS:
                    raise TeamAgentPersistenceConflict(
                        "checkpoint requires a repeatable-read caller transaction"
                    )
            else:
                try:
                    connection.execution_options(
                        isolation_level="REPEATABLE READ"
                    )
                except InvalidRequestError as exc:
                    raise TeamAgentPersistenceConflict(
                        "checkpoint requires a repeatable-read caller transaction"
                    ) from exc
        task_rows = connection.execute(
            select(team_agent_tasks)
            .where(
                *self._scope_predicates(scope),
                team_agent_tasks.c.session_ref == session_ref,
            )
            .order_by(team_agent_tasks.c.task_ref)
        ).mappings().all()
        event_rows = connection.execute(
            select(team_agent_events)
            .where(
                *self._event_scope_predicates(scope),
                team_agent_events.c.session_ref == session_ref,
            )
            .order_by(team_agent_events.c.event_id)
        ).mappings().all()
        tasks = [_task_from_mapping(row) for row in task_rows]
        events = [self._serialized_event(row) for row in event_rows]
        return _checkpoint(
            scope=scope,
            session_ref=session_ref,
            tasks=tasks,
            events=events,
        )

    def _lease_transition(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        now: datetime,
        event_type: str,
        values: Mapping[str, Any],
        payload: Mapping[str, Any] | None = None,
        require_retry_budget: bool = False,
        completion_evidence_refs: Sequence[str] | None = None,
        completion_reviewer_id: str | None = None,
    ) -> PersistedTeamAgentTask:
        with self._begin() as connection:
            current_row = connection.execute(
                select(team_agent_tasks).where(
                    *self._task_predicates(scope, session_ref, task_ref)
                )
            ).mappings().one_or_none()
            if current_row is None:
                raise TeamAgentTaskNotFound("TeamAgent task not found in exact scope")
            current = _task_from_mapping(current_row)
            if current.state.value == event_type:
                replay_row = connection.execute(
                    select(team_agent_events).where(
                        *self._event_scope_predicates(scope),
                        team_agent_events.c.session_ref == session_ref,
                        team_agent_events.c.task_ref == task_ref,
                        team_agent_events.c.task_revision == current.revision,
                    )
                ).mappings().one_or_none()
                expected_payload = _event_payload(current, payload)
                if (
                    replay_row is not None
                    and replay_row["event_type"] == event_type
                    and replay_row["worker_id"] == worker_id
                    and replay_row["lease_ref"] == lease_ref
                    and _payload(replay_row["payload_json"]) == expected_payload
                ):
                    return _copy_task(current)
                replay_name = "completion" if event_type == "completed" else event_type
                raise TeamAgentReplayConflict(f"{replay_name} replay conflict")
            if (
                require_retry_budget
                and current.attempt_count >= current.max_attempts
            ):
                raise TeamAgentPersistenceConflict("task retry budget is exhausted")
            return self._lease_transition_in_transaction(
                connection,
                current=current,
                scope=scope,
                session_ref=session_ref,
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                now=now,
                event_type=event_type,
                values=values,
                payload=payload,
                require_retry_budget=require_retry_budget,
                completion_evidence_refs=completion_evidence_refs,
                completion_reviewer_id=completion_reviewer_id,
            )

    def _lease_transition_in_transaction(
        self,
        connection: Any,
        *,
        current: PersistedTeamAgentTask,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        now: datetime,
        event_type: str,
        values: Mapping[str, Any],
        payload: Mapping[str, Any] | None = None,
        require_retry_budget: bool = False,
        completion_evidence_refs: Sequence[str] | None = None,
        completion_reviewer_id: str | None = None,
    ) -> PersistedTeamAgentTask:
        if completion_evidence_refs is not None:
            _assert_completion_policy(
                current,
                worker_id=worker_id,
                evidence_refs=completion_evidence_refs,
                reviewer_id=completion_reviewer_id,
            )
        retry_budget_predicates = (
            (team_agent_tasks.c.attempt_count < team_agent_tasks.c.max_attempts,)
            if require_retry_budget
            else ()
        )
        updated_row = connection.execute(
            update(team_agent_tasks)
            .where(
                *self._task_predicates(scope, session_ref, task_ref),
                team_agent_tasks.c.revision == current.revision,
                team_agent_tasks.c.updated_at <= now,
                team_agent_tasks.c.state == DurableTaskState.RUNNING.value,
                team_agent_tasks.c.claimed_by == worker_id,
                team_agent_tasks.c.lease_ref == lease_ref,
                team_agent_tasks.c.lease_expires_at > now,
                *retry_budget_predicates,
            )
            .values(
                **dict(values),
                revision=team_agent_tasks.c.revision + 1,
                updated_at=now,
            )
            .returning(*team_agent_tasks.c)
        ).mappings().one_or_none()
        if updated_row is None:
            raise TeamAgentPersistenceConflict("active task lease compare-and-swap lost")
        updated_task = _task_from_mapping(updated_row)
        self._append_event(
            connection,
            updated_task,
            event_type,
            worker_id=worker_id,
            lease_ref=lease_ref,
            payload=payload,
        )
        return _copy_task(updated_task)

    @staticmethod
    def _scope_predicates(scope: ExactScope) -> tuple[Any, ...]:
        values = _scope_values(scope)
        return (
            team_agent_tasks.c.tenant_ref == values["tenant_ref"],
            team_agent_tasks.c.entity_ref == values["entity_ref"],
            team_agent_tasks.c.store_ref == values["store_ref"],
        )

    @classmethod
    def _task_predicates(
        cls,
        scope: ExactScope,
        session_ref: str,
        task_ref: str,
    ) -> tuple[Any, ...]:
        return (
            *cls._scope_predicates(scope),
            team_agent_tasks.c.session_ref
            == _required_text(session_ref, "session_ref", 160),
            team_agent_tasks.c.task_ref == _required_text(task_ref, "task_ref", 160),
        )

    @staticmethod
    def _event_scope_predicates(scope: ExactScope) -> tuple[Any, ...]:
        values = _scope_values(scope)
        return (
            team_agent_events.c.tenant_ref == values["tenant_ref"],
            team_agent_events.c.entity_ref == values["entity_ref"],
            team_agent_events.c.store_ref == values["store_ref"],
        )

    @staticmethod
    def _append_event(
        connection: Any,
        task: PersistedTeamAgentTask,
        event_type: str,
        *,
        worker_id: str | None,
        lease_ref: str | None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        connection.execute(
            insert(team_agent_events).values(
                tenant_ref=task.scope.tenant_ref,
                entity_ref=task.scope.entity_ref,
                store_ref=task.scope.store_ref,
                session_ref=task.session_ref,
                task_ref=task.task_ref,
                task_revision=task.revision,
                event_type=event_type,
                worker_id=worker_id,
                lease_ref=lease_ref,
                payload_json=_event_payload(task, payload),
                occurred_at=task.updated_at,
            )
        )

    @staticmethod
    def _serialized_event(row: RowMapping) -> dict[str, Any]:
        return {
            "event_id": int(row["event_id"]),
            "tenant_ref": row["tenant_ref"],
            "entity_ref": row["entity_ref"],
            "store_ref": row["store_ref"],
            "session_ref": row["session_ref"],
            "task_ref": row["task_ref"],
            "task_revision": int(row["task_revision"]),
            "event_type": row["event_type"],
            "worker_id": row["worker_id"],
            "lease_ref": row["lease_ref"],
            "payload": _payload(row["payload_json"]),
            "occurred_at": _utc(row["occurred_at"]).isoformat(),
        }


__all__ = [
    "CONTRACT_ID",
    "DurableTaskState",
    "InMemoryTeamAgentPersistence",
    "PersistedTeamAgentTask",
    "PostgresTeamAgentPersistence",
    "TeamAgentPersistence",
    "TeamAgentPersistenceConflict",
    "TeamAgentReplayConflict",
    "TeamAgentTransactionConflict",
    "TeamAgentPersistenceError",
    "TeamAgentTaskNotFound",
    "TeamAgentTaskRegistration",
    "team_agent_events",
    "team_agent_tasks",
]
