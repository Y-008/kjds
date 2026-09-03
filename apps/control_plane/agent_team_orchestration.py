"""Provider-neutral TeamAgent/Subagent orchestration kernel.

This module is intentionally in-process and side-effect free. It keeps the
existing public surface area used by the current tests, while adding the
lease, retry, event-chain, checkpoint, and snapshot contracts requested in the
implementation plan.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from enum import StrEnum
from typing import Any, Protocol

from .enterprise_control import EnterpriseControlError, ExactScope
from .team_agent_result_contract import (
    TeamAgentResultContractError,
    normalize_team_agent_result,
)

CONTRACT_ID = "kjds-agent-team-orchestration-v1"
CONTRACT_VERSION = "1"
_JITTER_POLICY_REGISTRY: dict[str, Callable[..., float]] = {}
TEAM_AGENT_HARNESS_SOURCE = "team-agent-orchestration"
TEAM_AGENT_HARNESS_VERIFIER_ID = "team-agent-terminal-observation"
TEAM_AGENT_HARNESS_VERIFIER_VERSION = "1"
TEAM_AGENT_HARNESS_VERIFIER_SOURCE_TYPE = "team_agent_terminal_observation"
TEAM_AGENT_HARNESS_VERIFIER_AUTHORITY = "observation"
MAX_RETRY_AFTER_SECONDS = 30
DEFAULT_LEASE_SECONDS = 120
MAX_TASK_ATTEMPTS = 3
CHECKPOINT_POLICY_ID = "kjds-agent-team-orchestration-checkpoint-policy-v1"
CHECKPOINT_POLICY_VERSION = "1"
CANONICAL_PROJECTION_VERSION = "1"


class OrchestrationError(EnterpriseControlError):
    pass


class OrchestrationReplayConflict(OrchestrationError):
    """A terminal replay does not match the committed operation."""

    http_status_code = 409

    @property
    def http_detail(self) -> dict[str, str]:
        return {"code": "idempotency_conflict", "message": str(self)}


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY_WAIT = "retry_wait"
    BLOCKED = "blocked"
    PAUSED = "paused"
    EXPIRED = "expired"


class SessionState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class ThreadState(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


def _text(value: Any, name: str, maximum: int = 240) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise OrchestrationError(f"{name} must be 1 to {maximum} characters")
    return normalized


def _matching_aliases(
    primary: str | None,
    alias: str | None,
    *,
    primary_name: str,
    alias_name: str,
    maximum: int = 240,
) -> str | None:
    """Normalize two public aliases without letting one silently override the other."""

    normalized_primary = (
        _text(primary, primary_name, maximum) if primary is not None else None
    )
    normalized_alias = _text(alias, alias_name, maximum) if alias is not None else None
    if (
        normalized_primary is not None
        and normalized_alias is not None
        and normalized_primary != normalized_alias
    ):
        raise OrchestrationError(f"{primary_name} and {alias_name} conflict")
    return normalized_primary or normalized_alias


def _utc(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _normalize_result(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return normalize_team_agent_result(value)
    except TeamAgentResultContractError as exc:
        raise OrchestrationError(str(exc)) from exc


def _normalize_refs(values: Sequence[str], field_name: str, *, maximum: int = 50) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise OrchestrationError(f"{field_name} must be a sequence")
    normalized = tuple(_text(item, field_name) for item in values)
    if len(normalized) > maximum:
        raise OrchestrationError(f"{field_name} exceeds the bounded limit")
    if len(normalized) != len(set(normalized)):
        raise OrchestrationError(f"{field_name} values must be unique")
    return normalized


def _is_lower_hex_sha256(value: str | None) -> bool:
    if value is None or len(value) != 64:
        return False
    return all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class TeamAgentThread:
    thread_ref: str
    session_ref: str
    title: str
    parent_thread_ref: str | None
    state: ThreadState = ThreadState.OPEN
    parent_task_ref: str | None = None
    handoff_ref: str | None = None
    target_role: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class TeamAgentTask:
    task_ref: str
    session_ref: str
    thread_ref: str
    agent_id: str
    role: str
    objective: str
    dependencies: tuple[str, ...]
    idempotency_key: str
    state: TaskState = TaskState.QUEUED
    claimed_by: str | None = None
    reviewer_id: str | None = None
    lease_ref: str | None = None
    lease_expires_at: datetime | None = None
    attempt_count: int = 0
    max_attempts: int = MAX_TASK_ATTEMPTS
    retry_wait_until: datetime | None = None
    retry_after_seconds: float | None = None
    result: dict[str, Any] | None = None
    evidence_refs: tuple[str, ...] = ()
    failure_code: str | None = None
    failure_kind: str | None = None
    blocked_reason: str | None = None
    trace_id: str | None = None
    provider_id: str | None = None
    parent_task_ref: str | None = None
    handoff_ref: str | None = None
    requires_evidence: bool = False
    acceptance_contract: dict[str, Any] | None = None
    reviewer_role: str | None = None
    cost_budget_units: int | None = None
    cost_used_units: int = 0
    time_budget_seconds: int | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    expired_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def attempt(self) -> int:
        return self.attempt_count

    @property
    def next_attempt_at(self) -> datetime | None:
        return self.retry_wait_until

    @property
    def provider_ref(self) -> str | None:
        return self.provider_id

    @property
    def evidence_required(self) -> bool:
        return self.requires_evidence


@dataclass(frozen=True, slots=True)
class TeamAgentObservation:
    observation_ref: str
    session_ref: str
    task_ref: str
    kind: str
    payload_sha256: str
    evidence_refs: tuple[str, ...]
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class TaskLease:
    lease_ref: str
    task_ref: str
    session_ref: str
    thread_ref: str
    worker_id: str
    claimed_at: datetime
    heartbeat_at: datetime
    expires_at: datetime
    attempt_count: int
    provider_id: str | None = None
    trace_id: str | None = None
    released_at: datetime | None = None
    released_reason: str | None = None
    state: str = "active"

    @property
    def lease_id(self) -> str:
        return self.lease_ref

    @property
    def acquired_at(self) -> datetime:
        return self.claimed_at

    @property
    def attempt(self) -> int:
        return self.attempt_count


@dataclass(frozen=True, slots=True)
class ControlEvent:
    event_ref: str
    session_ref: str
    sequence: int
    cursor: str
    previous_cursor: str | None
    previous_hash: str
    event_type: str
    payload: dict[str, Any]
    payload_sha256: str
    contract_id: str
    contract_version: str
    created_at: datetime
    scope: dict[str, str] = field(default_factory=dict)

    @property
    def event_hash(self) -> str:
        return _hash(
            {
                "event_ref": self.event_ref,
                "session_ref": self.session_ref,
                "sequence": self.sequence,
                "cursor": self.cursor,
                "previous_cursor": self.previous_cursor,
                "previous_hash": self.previous_hash,
                "event_type": self.event_type,
                "payload_sha256": self.payload_sha256,
                "scope": self.scope,
                "contract_id": self.contract_id,
                "contract_version": self.contract_version,
                "created_at": _utc(self.created_at).isoformat(),
            }
        )

    @property
    def payload_hash(self) -> str:
        return self.payload_sha256


@dataclass(frozen=True, slots=True)
class TaskHandoff:
    handoff_ref: str
    session_ref: str
    source_thread_ref: str
    target_thread_ref: str
    source_task_ref: str
    target_role: str
    input_evidence_refs: tuple[str, ...]
    acceptance_contract: dict[str, Any]
    trace_id: str
    scope: dict[str, str]
    created_at: datetime


TeamAgentHandoff = TaskHandoff


@dataclass(frozen=True, slots=True)
class TeamAgentSession:
    session_ref: str
    scope: ExactScope
    objective: str
    owner_id: str
    max_parallel: int
    max_active_per_agent: int = 1
    cost_budget_units: int | None = None
    time_budget_seconds: int | None = None
    cost_used_units: int = 0
    provider_buckets: dict[str, int] = field(default_factory=dict)
    state: SessionState = SessionState.ACTIVE
    kill_switch_engaged: bool = False
    last_checkpoint_cursor: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    authority_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class EventMergeResult:
    status: str
    events: tuple[dict[str, Any], ...] = ()
    conflicts: tuple[str, ...] = ()
    cursor: str | None = None

    @property
    def merged(self) -> tuple[dict[str, Any], ...]:
        return self.events

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self):
        return iter(self.events)

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self.events[key]
        return {
            "status": self.status,
            "events": self.events,
            "merged": self.events,
            "conflicts": self.conflicts,
            "cursor": self.cursor,
        }[key]


class TeamAgentCoordinator:
    """Thread-safe coordinator for parallel TeamAgent work."""

    def __init__(
        self,
        *,
        max_sessions: int = 64,
        lease_ttl_seconds: int = DEFAULT_LEASE_SECONDS,
        max_attempts: int = MAX_TASK_ATTEMPTS,
        retry_base_seconds: int = 1,
        retry_max_seconds: int = MAX_RETRY_AFTER_SECONDS,
        jitter_fn: Callable[..., float] | None = None,
        jitter_policy_ref: str | None = None,
        breaker_failure_threshold: int = 3,
        breaker_cooldown_seconds: int = 60,
        max_active_per_agent: int | None = None,
        provider_buckets: Mapping[str, int] | None = None,
        cost_budget_units: int | None = None,
        time_budget_seconds: int | None = None,
        **legacy_options: Any,
    ) -> None:
        if "lease_seconds" in legacy_options:
            lease_ttl_seconds = int(legacy_options.pop("lease_seconds"))
        if "retry_limit" in legacy_options:
            max_attempts = int(legacy_options.pop("retry_limit"))
        if "agent_active_limit" in legacy_options:
            max_active_per_agent = int(legacy_options.pop("agent_active_limit"))
        if "provider_limits" in legacy_options and provider_buckets is None:
            provider_buckets = legacy_options.pop("provider_limits")
        if legacy_options:
            raise OrchestrationError(
                f"unknown coordinator option: {next(iter(legacy_options))}"
            )
        if max_sessions < 1 or max_sessions > 1000:
            raise OrchestrationError("max_sessions must be between 1 and 1000")
        if max_active_per_agent is None:
            max_active_per_agent = 1
        if lease_ttl_seconds < 1 or lease_ttl_seconds > 3600:
            raise OrchestrationError("lease_ttl_seconds must be between 1 and 3600")
        if max_attempts < 1 or max_attempts > MAX_TASK_ATTEMPTS:
            raise OrchestrationError("max_attempts must be between 1 and 3")
        if retry_base_seconds < 0 or retry_max_seconds < 0:
            raise OrchestrationError("retry delay cannot be negative")
        if jitter_fn is None and jitter_policy_ref is not None:
            raise OrchestrationError(
                "jitter_policy_ref requires an injected jitter function"
            )
        if breaker_failure_threshold < 1 or breaker_cooldown_seconds < 1:
            raise OrchestrationError("circuit breaker settings must be positive")
        if max_active_per_agent < 1:
            raise OrchestrationError("max_active_per_agent must be positive")
        if cost_budget_units is not None and cost_budget_units < 0:
            raise OrchestrationError("cost_budget_units cannot be negative")
        if time_budget_seconds is not None and time_budget_seconds <= 0:
            raise OrchestrationError("time_budget_seconds must be positive")
        default_buckets = {
            _text(key, "provider_bucket"): int(value)
            for key, value in (provider_buckets or {}).items()
        }
        if any(value < 1 for value in default_buckets.values()):
            raise OrchestrationError("provider bucket limits must be positive")
        self._max_sessions = max_sessions
        self._lease_ttl_seconds = lease_ttl_seconds
        self._default_max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = min(MAX_RETRY_AFTER_SECONDS, retry_max_seconds)
        self._jitter_fn = jitter_fn
        self._jitter_policy_ref = (
            _text(jitter_policy_ref, "jitter_policy_ref", 300)
            if jitter_policy_ref is not None
            else self._callable_policy_ref(jitter_fn)
        )
        if jitter_fn is not None and self._jitter_policy_ref is not None:
            _JITTER_POLICY_REGISTRY[self._jitter_policy_ref] = jitter_fn
        self._breaker_failure_threshold = breaker_failure_threshold
        self._breaker_cooldown_seconds = breaker_cooldown_seconds
        self._default_max_active_per_agent = max_active_per_agent
        self._default_provider_buckets = default_buckets
        self._default_cost_budget_units = cost_budget_units
        self._default_time_budget_seconds = time_budget_seconds
        self._sessions: dict[str, TeamAgentSession] = {}
        self._threads: dict[str, TeamAgentThread] = {}
        self._tasks: dict[str, TeamAgentTask] = {}
        self._observations: list[TeamAgentObservation] = []
        self._leases: dict[str, TaskLease] = {}
        self._events: list[ControlEvent] = []
        self._event_index: dict[str, ControlEvent] = {}
        self._event_positions: dict[str, int] = {}
        self._handoffs: dict[str, TaskHandoff] = {}
        self._circuit_breakers: dict[tuple[str, str], dict[str, Any]] = {}
        self._idempotency: dict[str, str] = {}
        self._durable_task_revisions: dict[str, int] = {}
        self._durable_task_requests: dict[str, str] = {}
        self._conflicts: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def create_session(
        self,
        *,
        session_ref: str,
        scope: ExactScope,
        objective: str,
        owner_id: str,
        max_parallel: int = 3,
        max_active_per_agent: int | None = None,
        cost_budget_units: int | None = None,
        time_budget_seconds: int | None = None,
        provider_buckets: Mapping[str, int] | None = None,
        authority_sha256: str | None = None,
        created_at: datetime | str | None = None,
    ) -> TeamAgentSession:
        with self._lock:
            session_ref = _text(session_ref, "session_ref")
            if not isinstance(scope, ExactScope):
                raise OrchestrationError("scope must be an ExactScope")
            if session_ref in self._sessions:
                raise OrchestrationError("session_ref already exists")
            if len(self._sessions) >= self._max_sessions:
                raise OrchestrationError("session capacity exhausted")
            if max_parallel < 1 or max_parallel > 32:
                raise OrchestrationError("max_parallel must be between 1 and 32")
            agent_limit = (
                max_active_per_agent
                if max_active_per_agent is not None
                else self._default_max_active_per_agent
            )
            if agent_limit < 1 or agent_limit > max_parallel:
                raise OrchestrationError(
                    "max_active_per_agent must be between 1 and max_parallel"
                )
            if cost_budget_units is None:
                cost_budget_units = self._default_cost_budget_units
            if time_budget_seconds is None:
                time_budget_seconds = self._default_time_budget_seconds
            if cost_budget_units is not None and cost_budget_units < 0:
                raise OrchestrationError("cost_budget_units cannot be negative")
            if time_budget_seconds is not None and time_budget_seconds <= 0:
                raise OrchestrationError("time_budget_seconds must be positive")
            normalized_buckets = {
                _text(key, "provider_bucket"): int(value)
                for key, value in (
                    provider_buckets
                    if provider_buckets is not None
                    else self._default_provider_buckets
                ).items()
            }
            if any(limit < 1 for limit in normalized_buckets.values()):
                raise OrchestrationError("provider bucket limits must be positive")
            if authority_sha256 is not None and not _is_lower_hex_sha256(authority_sha256):
                raise OrchestrationError("authority_sha256 must be lowercase SHA-256")
            created = _utc(created_at)
            session = TeamAgentSession(
                session_ref=session_ref,
                scope=scope,
                objective=_text(objective, "objective", 2000),
                owner_id=_text(owner_id, "owner_id"),
                max_parallel=max_parallel,
                max_active_per_agent=agent_limit,
                cost_budget_units=cost_budget_units,
                time_budget_seconds=time_budget_seconds,
                provider_buckets=normalized_buckets,
                created_at=created,
                updated_at=created,
                authority_sha256=authority_sha256,
            )
            self._sessions[session_ref] = session
            self._threads[f"{session_ref}:root"] = TeamAgentThread(
                thread_ref=f"{session_ref}:root",
                session_ref=session_ref,
                title="root",
                parent_thread_ref=None,
                created_at=created,
            )
            self._record_event(
                session_ref=session_ref,
                event_type="session.created",
                payload={
                    "objective": session.objective,
                    "owner_id": session.owner_id,
                    "max_parallel": max_parallel,
                    "max_active_per_agent": agent_limit,
                    "cost_budget_units": cost_budget_units,
                    "time_budget_seconds": time_budget_seconds,
                    "provider_buckets": normalized_buckets,
                    "authority_sha256": authority_sha256,
                },
                created_at=created,
            )
            return self._export_session(session)

    def fork_thread(
        self,
        *,
        session_ref: str,
        thread_ref: str,
        title: str,
        parent_thread_ref: str | None = None,
        parent_task_ref: str | None = None,
        handoff_ref: str | None = None,
        target_role: str | None = None,
        created_at: datetime | str | None = None,
    ) -> TeamAgentThread:
        with self._lock:
            session = self._session(session_ref)
            if session.state is not SessionState.ACTIVE or session.kill_switch_engaged:
                raise OrchestrationError("threads can only be created in an active session")
            thread_ref = _text(thread_ref, "thread_ref")
            if thread_ref in self._threads:
                raise OrchestrationError("thread_ref already exists")
            parent = parent_thread_ref or f"{session_ref}:root"
            parent_thread = self._threads.get(parent)
            if parent_thread is None or parent_thread.session_ref != session_ref:
                raise OrchestrationError("parent thread is outside the session")
            if parent_task_ref is not None:
                parent_task = self._task(parent_task_ref)
                if parent_task.session_ref != session_ref:
                    raise OrchestrationError("parent task crosses session scope")
            if handoff_ref is not None:
                handoff = self._handoffs.get(_text(handoff_ref, "handoff_ref"))
                if handoff is None or handoff.session_ref != session_ref:
                    raise OrchestrationError("handoff is outside the session")
            created = TeamAgentThread(
                thread_ref=thread_ref,
                session_ref=session_ref,
                title=_text(title, "title"),
                parent_thread_ref=parent,
                parent_task_ref=_text(parent_task_ref, "parent_task_ref") if parent_task_ref else None,
                handoff_ref=_text(handoff_ref, "handoff_ref") if handoff_ref else None,
                target_role=_text(target_role, "target_role") if target_role else None,
                created_at=_utc(created_at),
            )
            stored = self._store_thread(created)
            self._record_event(
                session_ref=session_ref,
                event_type="thread.forked",
                payload={
                    "thread_ref": stored.thread_ref,
                    "title": stored.title,
                    "parent_thread_ref": stored.parent_thread_ref,
                    "parent_task_ref": stored.parent_task_ref,
                    "handoff_ref": stored.handoff_ref,
                    "target_role": stored.target_role,
                },
                created_at=stored.created_at,
            )
            return self._export_thread(stored)

    def submit_task(
        self,
        *,
        session_ref: str,
        task_ref: str,
        thread_ref: str,
        agent_id: str,
        role: str,
        objective: str,
        idempotency_key: str,
        dependencies: tuple[str, ...] = (),
        evidence_required: bool = False,
        requires_evidence: bool | None = None,
        evidence_refs: Sequence[str] = (),
        acceptance_contract: Mapping[str, Any] | None = None,
        max_attempts: int | None = None,
        provider_id: str | None = None,
        provider_ref: str | None = None,
        trace_id: str | None = None,
        parent_task_ref: str | None = None,
        handoff_ref: str | None = None,
        reviewer_role: str | None = None,
        reviewer_agent_id: str | None = None,
        cost_budget_units: int | None = None,
        time_budget_seconds: int | None = None,
        created_at: datetime | str | None = None,
    ) -> TeamAgentTask:
        with self._lock:
            session = self._session(session_ref)
            if session.state is not SessionState.ACTIVE or session.kill_switch_engaged:
                raise OrchestrationError("tasks can only be submitted to an active session")
            task_ref = _text(task_ref, "task_ref")
            thread_ref = _text(thread_ref, "thread_ref")
            thread = self._threads.get(thread_ref)
            if thread is None or thread.session_ref != session_ref or thread.state is ThreadState.CLOSED:
                raise OrchestrationError("task thread is outside the session or closed")
            agent_id = _text(agent_id, "agent_id")
            role = _text(role, "role")
            objective = _text(objective, "objective", 2000)
            idempotency_key = _text(idempotency_key, "idempotency_key", 300)
            if max_attempts is None:
                max_attempts = self._default_max_attempts
            if max_attempts < 1 or max_attempts > MAX_TASK_ATTEMPTS:
                raise OrchestrationError("max_attempts must be between 1 and 3")
            if requires_evidence is not None:
                evidence_required = requires_evidence
            provider_id = _matching_aliases(
                provider_id,
                provider_ref,
                primary_name="provider_id",
                alias_name="provider_ref",
            )
            trace_id = _text(trace_id, "trace_id") if trace_id is not None else None
            parent_task_ref = _text(parent_task_ref, "parent_task_ref") if parent_task_ref else None
            handoff_ref = _text(handoff_ref, "handoff_ref") if handoff_ref else None
            reviewer_role = _text(reviewer_role, "reviewer_role") if reviewer_role else None
            reviewer_agent_id = (
                _text(reviewer_agent_id, "reviewer_agent_id")
                if reviewer_agent_id
                else None
            )
            normalized_dependencies = _normalize_refs(dependencies, "dependency_ref")
            normalized_evidence = _normalize_refs(evidence_refs, "evidence_ref", maximum=50)
            normalized_contract = (
                _normalize_result(acceptance_contract)
                if acceptance_contract is not None
                else None
            )
            if cost_budget_units is not None and cost_budget_units < 0:
                raise OrchestrationError("cost_budget_units cannot be negative")
            if time_budget_seconds is not None and time_budget_seconds <= 0:
                raise OrchestrationError("time_budget_seconds must be positive")
            if task_ref in normalized_dependencies:
                raise OrchestrationError("task dependency cycle detected")
            if parent_task_ref is not None:
                parent_task = self._tasks.get(parent_task_ref)
                if parent_task is None:
                    raise OrchestrationError("parent task does not exist")
                if parent_task.session_ref != session_ref:
                    raise OrchestrationError("parent task crosses session scope")
            if handoff_ref is not None:
                handoff = self._handoffs.get(handoff_ref)
                if handoff is None or handoff.session_ref != session_ref:
                    raise OrchestrationError("handoff is outside the session")
                if thread_ref != handoff.target_thread_ref:
                    raise OrchestrationError("handoff target thread conflict")
                if role != handoff.target_role:
                    raise OrchestrationError("handoff target role conflict")
                if parent_task_ref != handoff.source_task_ref:
                    raise OrchestrationError("handoff parent task conflict")
                if normalized_contract != handoff.acceptance_contract:
                    raise OrchestrationError("handoff acceptance contract conflict")
                if not set(handoff.input_evidence_refs) <= set(
                    normalized_evidence
                ):
                    raise OrchestrationError("handoff input Evidence conflict")
                if trace_id != handoff.trace_id:
                    raise OrchestrationError("handoff trace conflict")
            for dependency in normalized_dependencies:
                dependency_task = self._tasks.get(dependency)
                if dependency_task is None:
                    raise OrchestrationError("task dependency does not exist")
                if dependency_task.session_ref != session_ref:
                    raise OrchestrationError("dependency barrier crosses session scope")
            self._assert_acyclic(task_ref, normalized_dependencies)
            if reviewer_role is not None and reviewer_role == role:
                raise OrchestrationError("independent review role must differ from author")
            if reviewer_agent_id is not None and reviewer_agent_id == agent_id:
                raise OrchestrationError("independent reviewer must differ from author")
            request_hash = _hash(
                {
                    "session_ref": session_ref,
                    "task_ref": task_ref,
                    "thread_ref": thread_ref,
                    "agent_id": agent_id,
                    "role": role,
                    "objective": objective,
                    "dependencies": normalized_dependencies,
                    "evidence_required": bool(evidence_required),
                    "evidence_refs": normalized_evidence,
                    "acceptance_contract": normalized_contract,
                    "max_attempts": max_attempts,
                    "provider_id": provider_id,
                    "trace_id": trace_id,
                    "parent_task_ref": parent_task_ref,
                    "handoff_ref": handoff_ref,
                    "reviewer_role": reviewer_role,
                    "reviewer_agent_id": reviewer_agent_id,
                    "cost_budget_units": cost_budget_units,
                    "time_budget_seconds": time_budget_seconds,
                }
            )
            idempotency_slot = self._idempotency_slot(session_ref, idempotency_key)
            previous = self._idempotency.get(idempotency_slot)
            if previous is not None:
                if previous != request_hash:
                    raise OrchestrationError("idempotency_conflict")
                return self._export_task(
                    next(
                        task
                        for task in self._tasks.values()
                        if task.session_ref == session_ref
                        and task.idempotency_key == idempotency_key
                    )
                )
            if task_ref in self._tasks:
                raise OrchestrationError("task_ref already exists")
            created = _utc(created_at)
            self._assert_event_time(session_ref, created)
            task = TeamAgentTask(
                task_ref=task_ref,
                session_ref=session_ref,
                thread_ref=thread_ref,
                agent_id=agent_id,
                role=role,
                objective=objective,
                dependencies=normalized_dependencies,
                idempotency_key=idempotency_key,
                max_attempts=max_attempts,
                provider_id=provider_id,
                trace_id=trace_id,
                parent_task_ref=parent_task_ref,
                handoff_ref=handoff_ref,
                requires_evidence=bool(evidence_required),
                evidence_refs=normalized_evidence,
                acceptance_contract=normalized_contract,
                reviewer_role=reviewer_role,
                reviewer_id=reviewer_agent_id,
                cost_budget_units=cost_budget_units,
                time_budget_seconds=time_budget_seconds,
                created_at=created,
                updated_at=created,
            )
            self._tasks[task_ref] = task
            self._idempotency[idempotency_slot] = request_hash
            self._record_event(
                session_ref=session_ref,
                event_type="task.submitted",
                payload={
                    "task_ref": task_ref,
                    "thread_ref": thread_ref,
                    "agent_id": task.agent_id,
                    "role": task.role,
                    "objective": task.objective,
                    "idempotency_key": idempotency_key,
                    "dependencies": list(normalized_dependencies),
                    "evidence_required": bool(evidence_required),
                    "evidence_refs": list(normalized_evidence),
                    "acceptance_contract": normalized_contract,
                    "max_attempts": max_attempts,
                    "provider_id": provider_id,
                    "trace_id": trace_id,
                    "parent_task_ref": parent_task_ref,
                    "handoff_ref": handoff_ref,
                    "reviewer_role": reviewer_role,
                    "reviewer_agent_id": reviewer_agent_id,
                    "cost_budget_units": cost_budget_units,
                    "time_budget_seconds": time_budget_seconds,
                },
                created_at=created,
            )
            return self._export_task(task)

    def claim_task(
        self,
        *,
        task_ref: str,
        worker_id: str,
        lease_seconds: int | None = None,
        lease_ttl_seconds: int | None = None,
        lease_id: str | None = None,
        provider_id: str | None = None,
        provider_ref: str | None = None,
        trace_id: str | None = None,
        as_of: datetime | str | None = None,
    ) -> TeamAgentTask:
        with self._lock:
            now = _utc(as_of)
            task = self._task(task_ref)
            self._assert_event_time(task.session_ref, now)
            session = self._session(task.session_ref)
            if session.state is not SessionState.ACTIVE or session.kill_switch_engaged:
                raise OrchestrationError("session is not active")
            worker_id = _text(worker_id, "worker_id")
            requested_provider_id = _matching_aliases(
                provider_id,
                provider_ref,
                primary_name="provider_id",
                alias_name="provider_ref",
            )
            requested_trace_id = (
                _text(trace_id, "trace_id") if trace_id is not None else None
            )
            if task.state is TaskState.RUNNING and task.lease_ref is not None:
                lease = self._leases.get(task.lease_ref)
                if (
                    lease is not None
                    and lease.worker_id == worker_id
                    and lease.state == "active"
                    and now < lease.expires_at
                ):
                    if lease_id is not None and _text(lease_id, "lease_id") != lease.lease_ref:
                        raise OrchestrationError("lease_id does not match active claim")
                    if (
                        requested_provider_id is not None
                        and requested_provider_id != task.provider_id
                    ):
                        raise OrchestrationError(
                            "claim provider association conflict"
                        )
                    if (
                        requested_trace_id is not None
                        and requested_trace_id != task.trace_id
                    ):
                        raise OrchestrationError(
                            "claim trace association conflict"
                        )
                    return self._export_task(task)
                if lease is not None and now >= lease.expires_at:
                    self.tick(as_of=now)
                    task = self._task(task_ref)
            lease_seconds = (
                lease_ttl_seconds
                if lease_ttl_seconds is not None
                else lease_seconds
                if lease_seconds is not None
                else self._lease_ttl_seconds
            )
            if lease_seconds < 1 or lease_seconds > 3600:
                raise OrchestrationError("lease_seconds must be between 1 and 3600")
            if task.state not in {
                TaskState.QUEUED,
                TaskState.RETRY_WAIT,
                TaskState.EXPIRED,
            }:
                raise OrchestrationError("task is not claimable")
            if task.state is TaskState.RETRY_WAIT and task.retry_wait_until is not None and now < task.retry_wait_until:
                raise OrchestrationError("task is waiting for retry")
            if any(
                self._tasks[dependency].state is not TaskState.COMPLETED
                for dependency in task.dependencies
            ):
                raise OrchestrationError("task dependencies are not complete")
            if task.attempt_count >= task.max_attempts:
                blocked = self._replace_task(
                    task,
                    state=TaskState.BLOCKED,
                    blocked_reason="retry_budget_exhausted",
                    updated_at=now,
                )
                self._tasks[task.task_ref] = blocked
                self._record_event(
                    session_ref=task.session_ref,
                    event_type="task.retry_budget_exhausted",
                    payload={
                        "task_ref": task.task_ref,
                        "attempt_count": task.attempt_count,
                        "max_attempts": task.max_attempts,
                        "blocked_reason": "retry_budget_exhausted",
                    },
                    created_at=now,
                )
                self._observations.append(
                    self._observation(
                        blocked,
                        "task.blocked",
                        {"blocked_reason": "retry_budget_exhausted"},
                        blocked.evidence_refs,
                        now,
                    )
                )
                raise OrchestrationError("retry budget exhausted; task is blocked")
            if (
                session.time_budget_seconds is not None
                and (now - session.created_at).total_seconds() >= session.time_budget_seconds
            ):
                self._block_unleased_task(
                    task,
                    reason="time_budget_exhausted",
                    as_of=now,
                )
                raise OrchestrationError("session time budget exhausted")
            if (
                task.time_budget_seconds is not None
                and task.started_at is not None
                and (now - task.started_at).total_seconds() >= task.time_budget_seconds
            ):
                self._block_unleased_task(
                    task,
                    reason="time_budget_exhausted",
                    as_of=now,
                )
                raise OrchestrationError("task time budget exhausted")
            if session.cost_budget_units is not None and session.cost_used_units >= session.cost_budget_units:
                raise OrchestrationError("session cost budget exhausted")
            if task.cost_budget_units is not None and task.cost_used_units >= task.cost_budget_units:
                raise OrchestrationError("task cost budget exhausted")
            if self._session_running_count(session.session_ref) >= session.max_parallel:
                raise OrchestrationError("session parallelism budget exhausted")
            if self._agent_running_count(session.session_ref, task.agent_id) >= session.max_active_per_agent:
                raise OrchestrationError("single agent active budget exhausted")
            if (
                requested_provider_id is not None
                and task.provider_id is not None
                and requested_provider_id != task.provider_id
            ):
                raise OrchestrationError("claim provider association conflict")
            provider_id = requested_provider_id or task.provider_id
            if (
                requested_trace_id is not None
                and task.trace_id is not None
                and requested_trace_id != task.trace_id
            ):
                raise OrchestrationError("claim trace association conflict")
            trace_id = requested_trace_id or task.trace_id
            lease_ref = (
                _text(lease_id, "lease_id")
                if lease_id is not None
                else f"lease-{task.task_ref}-{task.attempt_count + 1}"
            )
            if lease_ref in self._leases:
                raise OrchestrationError("lease_id already exists")
            probe_breaker: dict[str, Any] | None = None
            if provider_id is not None:
                self._assert_provider_bucket(session, provider_id)
                breaker = self._circuit_breaker(session.session_ref, provider_id)
                if breaker["state"] == "open" and breaker["open_until"] > now:
                    raise OrchestrationError("provider circuit breaker is open")
                if breaker["state"] == "half_open" and breaker["probe_in_flight"]:
                    raise OrchestrationError("provider circuit breaker probe is already active")
                if (
                    breaker["state"] == "open"
                    and breaker["open_until"] <= now
                    or breaker["state"] == "half_open"
                ):
                    probe_breaker = breaker
            lease_expires_at = now + timedelta(seconds=lease_seconds)
            if session.time_budget_seconds is not None:
                lease_expires_at = min(
                    lease_expires_at,
                    session.created_at
                    + timedelta(seconds=session.time_budget_seconds),
                )
            if task.time_budget_seconds is not None:
                lease_expires_at = min(
                    lease_expires_at,
                    (task.started_at or now)
                    + timedelta(seconds=task.time_budget_seconds),
                )
            lease = TaskLease(
                lease_ref=lease_ref,
                task_ref=task.task_ref,
                session_ref=task.session_ref,
                thread_ref=task.thread_ref,
                worker_id=worker_id,
                claimed_at=now,
                heartbeat_at=now,
                expires_at=lease_expires_at,
                attempt_count=task.attempt_count + 1,
                provider_id=provider_id,
                trace_id=trace_id,
            )
            claimed = self._replace_task(
                task,
                state=TaskState.RUNNING,
                claimed_by=worker_id,
                lease_ref=lease_ref,
                lease_expires_at=lease.expires_at,
                provider_id=provider_id,
                trace_id=trace_id,
                attempt_count=lease.attempt_count,
                started_at=task.started_at or now,
                retry_wait_until=None,
                retry_after_seconds=None,
                expired_at=None,
                updated_at=now,
            )
            if probe_breaker is not None:
                probe_breaker["state"] = CircuitState.HALF_OPEN.value
                probe_breaker["probe_in_flight"] = True
            self._tasks[task.task_ref] = claimed
            self._leases[lease_ref] = lease
            self._record_event(
                session_ref=task.session_ref,
                event_type="task.claimed",
                payload={
                    "task_ref": task.task_ref,
                    "worker_id": worker_id,
                    "lease_ref": lease_ref,
                    "expires_at": lease.expires_at.isoformat(),
                    "attempt_count": lease.attempt_count,
                    "provider_id": provider_id,
                    "trace_id": trace_id,
                },
                created_at=now,
            )
            return self._export_task(claimed)

    def heartbeat_task(
        self,
        *,
        task_ref: str,
        worker_id: str,
        lease_seconds: int | None = None,
        extend_seconds: int | None = None,
        lease_id: str | None = None,
        lease_ref: str | None = None,
        as_of: datetime | str | None = None,
    ) -> TeamAgentTask:
        with self._lock:
            now = _utc(as_of)
            task = self._task(task_ref)
            self._assert_event_time(task.session_ref, now)
            if task.state is not TaskState.RUNNING or task.claimed_by != worker_id:
                raise OrchestrationError("only the lease holder may heartbeat a running task")
            budget_deadline = self._task_time_budget_deadline(task)
            if budget_deadline is not None and now >= budget_deadline:
                self.tick(as_of=now)
                raise OrchestrationError("task time budget exhausted")
            lease = self._assert_fenced_active_lease(
                task,
                worker_id=worker_id,
                as_of=now,
                lease_id=lease_id,
                lease_ref=lease_ref,
            )
            lease_seconds = (
                extend_seconds
                if extend_seconds is not None
                else lease_seconds
                if lease_seconds is not None
                else self._lease_ttl_seconds
            )
            if lease_seconds < 1 or lease_seconds > 3600:
                raise OrchestrationError("lease_seconds must be between 1 and 3600")
            session = self._session(task.session_ref)
            budget_deadlines: list[datetime] = []
            if session.time_budget_seconds is not None:
                budget_deadlines.append(
                    session.created_at
                    + timedelta(seconds=session.time_budget_seconds)
                )
            if task.time_budget_seconds is not None and task.started_at is not None:
                budget_deadlines.append(
                    task.started_at
                    + timedelta(seconds=task.time_budget_seconds)
                )
            budget_deadline = min(budget_deadlines) if budget_deadlines else None
            if budget_deadline is not None and now >= budget_deadline:
                self.release_task(
                    task_ref=task.task_ref,
                    worker_id=worker_id,
                    next_state=TaskState.BLOCKED,
                    reason="time_budget_exhausted",
                    lease_ref=lease.lease_ref,
                    as_of=now,
                )
                raise OrchestrationError("task time budget exhausted")
            expires_at = now + timedelta(seconds=lease_seconds)
            if budget_deadline is not None:
                expires_at = min(expires_at, budget_deadline)
            updated_lease = TaskLease(
                lease_ref=lease.lease_ref,
                task_ref=lease.task_ref,
                session_ref=lease.session_ref,
                thread_ref=lease.thread_ref,
                worker_id=lease.worker_id,
                claimed_at=lease.claimed_at,
                heartbeat_at=now,
                expires_at=expires_at,
                attempt_count=lease.attempt_count,
                provider_id=lease.provider_id,
                trace_id=lease.trace_id,
                released_at=lease.released_at,
                released_reason=lease.released_reason,
                state=lease.state,
            )
            self._leases[lease.lease_ref] = updated_lease
            updated_task = self._replace_task(
                task,
                lease_expires_at=updated_lease.expires_at,
                updated_at=now,
            )
            self._tasks[task.task_ref] = updated_task
            self._record_event(
                session_ref=task.session_ref,
                event_type="task.heartbeat",
                payload={
                    "task_ref": task.task_ref,
                    "worker_id": worker_id,
                    "lease_ref": lease.lease_ref,
                    "expires_at": updated_lease.expires_at.isoformat(),
                },
                created_at=now,
            )
            return self._export_task(updated_task)

    def release_task(
        self,
        *,
        task_ref: str,
        worker_id: str,
        next_state: TaskState | str = TaskState.QUEUED,
        reason: str | None = None,
        lease_id: str | None = None,
        lease_ref: str | None = None,
        as_of: datetime | str | None = None,
    ) -> TeamAgentTask:
        with self._lock:
            now = _utc(as_of)
            task = self._task(task_ref)
            self._assert_event_time(task.session_ref, now)
            worker_id = _text(worker_id, "worker_id")
            if isinstance(next_state, str):
                try:
                    next_state = TaskState(next_state)
                except ValueError as exc:
                    raise OrchestrationError("next_state is invalid") from exc
            if next_state not in {
                TaskState.QUEUED,
                TaskState.BLOCKED,
                TaskState.PAUSED,
                TaskState.EXPIRED,
            }:
                raise OrchestrationError("next_state is not releasable")
            normalized_reason = (
                _text(reason, "reason", 500) if reason is not None else None
            )
            if next_state is not TaskState.QUEUED and normalized_reason is None:
                raise OrchestrationError(
                    "non-queued release requires an explicit reason"
                )
            if task.state is not TaskState.RUNNING:
                raise OrchestrationError("only a running task may be released")
            if task.claimed_by != worker_id:
                raise OrchestrationError("only the lease holder may release a running task")
            budget_deadline = self._task_time_budget_deadline(task)
            if budget_deadline is not None and now >= budget_deadline:
                self.tick(as_of=now)
                raise OrchestrationError("task time budget exhausted")
            lease = self._assert_fenced_active_lease(
                task,
                worker_id=worker_id,
                as_of=now,
                lease_id=lease_id,
                lease_ref=lease_ref,
            )
            released_lease = TaskLease(
                lease_ref=lease.lease_ref,
                task_ref=lease.task_ref,
                session_ref=lease.session_ref,
                thread_ref=lease.thread_ref,
                worker_id=lease.worker_id,
                claimed_at=lease.claimed_at,
                heartbeat_at=lease.heartbeat_at,
                expires_at=lease.expires_at,
                attempt_count=lease.attempt_count,
                provider_id=lease.provider_id,
                trace_id=lease.trace_id,
                released_at=now,
                released_reason=normalized_reason,
                state="released",
            )
            released = self._replace_task(
                task,
                state=next_state,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                blocked_reason=(
                    normalized_reason
                    if normalized_reason is not None
                    else task.blocked_reason
                ),
                updated_at=now,
            )
            self._leases[lease.lease_ref] = released_lease
            self._release_breaker_probe(task.session_ref, lease.provider_id)
            self._tasks[task.task_ref] = released
            self._record_event(
                session_ref=task.session_ref,
                event_type="task.released",
                payload={
                    "task_ref": task.task_ref,
                    "worker_id": worker_id,
                    "lease_ref": lease.lease_ref,
                    "next_state": next_state.value,
                    "reason": normalized_reason,
                },
                created_at=now,
            )
            if next_state is TaskState.BLOCKED:
                self._observations.append(
                    self._observation(
                        released,
                        "task.blocked",
                        {"blocked_reason": released.blocked_reason},
                        released.evidence_refs,
                        now,
                    )
                )
            return self._export_task(released)

    def complete_task(
        self,
        *,
        task_ref: str,
        worker_id: str,
        result: Mapping[str, Any],
        evidence_refs: tuple[str, ...] = (),
        reviewer_id: str | None = None,
        reviewer_agent_id: str | None = None,
        lease_id: str | None = None,
        lease_ref: str | None = None,
        cost_units: int = 0,
        trace_id: str | None = None,
        as_of: datetime | str | None = None,
    ) -> TeamAgentTask:
        with self._lock:
            task = self._task(task_ref)
            if task.state is TaskState.COMPLETED:
                normalized = _normalize_result(result)
                supplied_evidence = _normalize_refs(
                    evidence_refs, "evidence_ref", maximum=50
                )
                supplied_reviewer = reviewer_id or reviewer_agent_id or task.reviewer_id
                if supplied_reviewer is not None:
                    supplied_reviewer = _text(supplied_reviewer, "reviewer_id")
                supplied_lease = _matching_aliases(
                    lease_ref,
                    lease_id,
                    primary_name="lease_ref",
                    alias_name="lease_id",
                    maximum=80,
                )
                terminal_event = next(
                    (
                        event
                        for event in reversed(self._events)
                        if event.session_ref == task.session_ref
                        and event.event_type == "task.completed"
                        and event.payload.get("task_ref") == task.task_ref
                    ),
                    None,
                )
                payload = terminal_event.payload if terminal_event is not None else {}
                recorded_completion_evidence = payload.get("completion_evidence_refs")
                if recorded_completion_evidence is None:
                    recorded_completion_evidence = payload.get("evidence_refs") or ()
                if (
                    payload.get("worker_id") == worker_id
                    and payload.get("lease_ref") == supplied_lease
                    and payload.get("result_sha256") == _hash(normalized)
                    and tuple(recorded_completion_evidence) == supplied_evidence
                    and payload.get("reviewer_id") == supplied_reviewer
                    and payload.get("cost_units") == cost_units
                    and (
                        trace_id is None
                        or payload.get("trace_id") == _text(trace_id, "trace_id")
                    )
                ):
                    return self._export_task(task)
                raise OrchestrationReplayConflict("completion replay conflict")
            if task.state is not TaskState.RUNNING or task.claimed_by != worker_id:
                raise OrchestrationError("only the claiming worker may complete a running task")
            now = _utc(as_of)
            self._assert_event_time(task.session_ref, now)
            budget_deadline = self._task_time_budget_deadline(task)
            if budget_deadline is not None and now >= budget_deadline:
                self.tick(as_of=now)
                raise OrchestrationError("task time budget exhausted")
            active_lease = self._assert_fenced_active_lease(
                task,
                worker_id=worker_id,
                as_of=now,
                lease_id=lease_id,
                lease_ref=lease_ref,
            )
            supplied_trace_id = (
                _text(trace_id, "trace_id") if trace_id is not None else None
            )
            if task.trace_id != active_lease.trace_id:
                raise OrchestrationError("task lease trace association conflict")
            if (
                supplied_trace_id is not None
                and supplied_trace_id != active_lease.trace_id
            ):
                raise OrchestrationError("completion trace association conflict")
            session = self._session(task.session_ref)
            budget_error: str | None = None
            if (
                session.time_budget_seconds is not None
                and (now - session.created_at).total_seconds()
                >= session.time_budget_seconds
            ):
                budget_error = "session time budget exhausted"
            elif (
                task.time_budget_seconds is not None
                and task.started_at is not None
                and (now - task.started_at).total_seconds()
                >= task.time_budget_seconds
            ):
                budget_error = "task time budget exhausted"
            if budget_error is not None:
                self.release_task(
                    task_ref=task.task_ref,
                    worker_id=worker_id,
                    next_state=TaskState.BLOCKED,
                    reason="time_budget_exhausted",
                    lease_ref=task.lease_ref,
                    as_of=now,
                )
                raise OrchestrationError(budget_error)
            new_evidence = _normalize_refs(evidence_refs, "evidence_ref", maximum=50)
            evidence = tuple(sorted(set(task.evidence_refs) | set(new_evidence)))
            if task.requires_evidence and not evidence:
                raise OrchestrationError("task requires Evidence before completion")
            reviewer_id = reviewer_id or reviewer_agent_id or task.reviewer_id
            if task.reviewer_role is not None and reviewer_id is None:
                raise OrchestrationError("independent reviewer is required")
            if reviewer_id is not None:
                reviewer_id = _text(reviewer_id, "reviewer_id")
                if reviewer_id in {worker_id, task.agent_id}:
                    raise OrchestrationError("independent reviewer must differ from the author")
            if cost_units < 0:
                raise OrchestrationError("cost_units cannot be negative")
            if task.cost_budget_units is not None and task.cost_used_units + cost_units > task.cost_budget_units:
                raise OrchestrationError("task cost budget exhausted")
            if session.cost_budget_units is not None and session.cost_used_units + cost_units > session.cost_budget_units:
                raise OrchestrationError("session cost budget exhausted")
            normalized = _normalize_result(result)
            active_lease_ref = task.lease_ref
            completed = self._replace_task(
                task,
                state=TaskState.COMPLETED,
                result=normalized,
                evidence_refs=evidence,
                reviewer_id=reviewer_id,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                cost_used_units=task.cost_used_units + cost_units,
                trace_id=active_lease.trace_id,
                completed_at=now,
                updated_at=now,
            )
            self._tasks[task.task_ref] = completed
            self._sessions[session.session_ref] = self._replace_session(
                session,
                cost_used_units=session.cost_used_units + cost_units,
            )
            if active_lease_ref is not None:
                self._leases.pop(active_lease_ref, None)
            self._touch_circuit_breaker(
                task.session_ref,
                task.provider_id,
                failed=False,
                at=now,
            )
            self._record_event(
                session_ref=task.session_ref,
                event_type="task.completed",
                payload={
                    "task_ref": task.task_ref,
                    "thread_ref": task.thread_ref,
                    "worker_id": worker_id,
                    "lease_ref": active_lease.lease_ref,
                    "result": normalized,
                    "result_sha256": _hash(normalized),
                    "evidence_refs": list(evidence),
                    "completion_evidence_refs": list(new_evidence),
                    "reviewer_id": reviewer_id,
                    "cost_units": cost_units,
                    "trace_id": active_lease.trace_id,
                },
                created_at=now,
            )
            self._observations.append(
                self._observation(
                    completed,
                    "task.completed",
                    normalized,
                    completed.evidence_refs,
                    completed.completed_at or completed.updated_at,
                )
            )
            return self._export_task(completed)

    def fail_task(
        self,
        *,
        task_ref: str,
        worker_id: str,
        failure_code: str,
        retry_after_seconds: float | None = None,
        retryable: bool | None = None,
        provider_id: str | None = None,
        provider_ref: str | None = None,
        status_code: int | None = None,
        error_kind: str | None = None,
        timeout: bool = False,
        trace_id: str | None = None,
        session_id: str | None = None,
        thread_id: str | None = None,
        retry_after: str | int | float | None = None,
        jitter_seed: str | None = None,
        lease_id: str | None = None,
        lease_ref: str | None = None,
        as_of: datetime | str | None = None,
    ) -> TeamAgentTask:
        with self._lock:
            task = self._task(task_ref)
            if task.state in {
                TaskState.FAILED,
                TaskState.RETRY_WAIT,
                TaskState.BLOCKED,
            }:
                now = _utc(as_of)
                code = _text(failure_code, "failure_code", 120)
                supplied_provider = _matching_aliases(
                    provider_id,
                    provider_ref,
                    primary_name="provider_id",
                    alias_name="provider_ref",
                )
                supplied_trace = _text(trace_id, "trace_id") if trace_id is not None else None
                classified_kind = self._classify_failure(code, status_code, timeout)
                supplied_kind = _text(error_kind, "error_kind", 120) if error_kind is not None else None
                failure_kind = supplied_kind or classified_kind
                transient = (
                    bool(retryable)
                    if retryable is not None
                    else failure_kind in {"rate_limited", "server_error", "timeout"}
                )
                parsed_retry_after = self._parse_retry_after(
                    retry_after_seconds,
                    retry_after,
                    now=now,
                )
                supplied_lease = _matching_aliases(
                    lease_ref,
                    lease_id,
                    primary_name="lease_ref",
                    alias_name="lease_id",
                    maximum=80,
                )
                event_type = f"task.{task.state.value}"
                terminal_event = next(
                    (
                        event
                        for event in reversed(self._events)
                        if event.session_ref == task.session_ref
                        and event.event_type == event_type
                        and event.payload.get("task_ref") == task.task_ref
                    ),
                    None,
                )
                payload = terminal_event.payload if terminal_event is not None else {}
                if (
                    payload.get("worker_id") == worker_id
                    and payload.get("lease_ref") == supplied_lease
                    and payload.get("failure_code") == code
                    and payload.get("status_code") == status_code
                    and payload.get("failure_kind") == failure_kind
                    and payload.get("retryable") == bool(transient)
                    and payload.get("retry_after_seconds") == parsed_retry_after
                    and payload.get("provider_id") == (supplied_provider or task.provider_id)
                    and payload.get("trace_id") == (supplied_trace or task.trace_id)
                    and payload.get("jitter_seed") == jitter_seed
                    and payload.get("timeout", timeout) == timeout
                    and (
                        session_id is None
                        or _text(session_id, "session_id") == task.session_ref
                    )
                    and (
                        thread_id is None
                        or _text(thread_id, "thread_id") == task.thread_ref
                    )
                ):
                    return self._export_task(task)
                raise OrchestrationReplayConflict("failure replay conflict")
            if task.state is not TaskState.RUNNING or task.claimed_by != worker_id:
                raise OrchestrationError("only the claiming worker may fail a running task")
            now = _utc(as_of)
            self._assert_event_time(task.session_ref, now)
            budget_deadline = self._task_time_budget_deadline(task)
            if budget_deadline is not None and now >= budget_deadline:
                self.tick(as_of=now)
                raise OrchestrationError("task time budget exhausted")
            active_lease = self._assert_fenced_active_lease(
                task,
                worker_id=worker_id,
                as_of=now,
                lease_id=lease_id,
                lease_ref=lease_ref,
            )
            code = _text(failure_code, "failure_code", 120)
            normalized_provider_id = (
                _text(provider_id, "provider_id")
                if provider_id is not None
                else None
            )
            normalized_provider_ref = (
                _text(provider_ref, "provider_ref")
                if provider_ref is not None
                else None
            )
            if (
                normalized_provider_id is not None
                and normalized_provider_ref is not None
                and normalized_provider_id != normalized_provider_ref
            ):
                raise OrchestrationError("failure provider aliases conflict")
            supplied_provider = normalized_provider_id or normalized_provider_ref
            if task.provider_id != active_lease.provider_id:
                raise OrchestrationError("task lease provider association conflict")
            if supplied_provider is not None and supplied_provider != active_lease.provider_id:
                raise OrchestrationError("failure provider association conflict")
            provider_id = active_lease.provider_id
            supplied_trace_id = (
                _text(trace_id, "trace_id") if trace_id is not None else None
            )
            if task.trace_id != active_lease.trace_id:
                raise OrchestrationError("task lease trace association conflict")
            if supplied_trace_id is not None and supplied_trace_id != active_lease.trace_id:
                raise OrchestrationError("failure trace association conflict")
            trace_id = active_lease.trace_id
            if (
                session_id is not None
                and _text(session_id, "session_id") != task.session_ref
            ):
                raise OrchestrationError("failure session association conflict")
            if (
                thread_id is not None
                and _text(thread_id, "thread_id") != task.thread_ref
            ):
                raise OrchestrationError("failure thread association conflict")
            classified_kind = self._classify_failure(code, status_code, timeout)
            supplied_error_kind = (
                _text(error_kind, "error_kind", 120)
                if error_kind is not None
                else None
            )
            provider_failure_kinds = {"rate_limited", "server_error", "timeout"}
            if (
                classified_kind in provider_failure_kinds
                and supplied_error_kind is not None
                and supplied_error_kind != classified_kind
            ):
                raise OrchestrationError("failure provider classification conflict")
            failure_kind = supplied_error_kind or classified_kind
            if classified_kind in provider_failure_kinds and retryable is False:
                raise OrchestrationError(
                    "transient provider failures cannot be marked non-retryable"
                )
            transient = (
                bool(retryable)
                if retryable is not None
                else failure_kind in provider_failure_kinds
            )
            parsed_retry_after = self._parse_retry_after(
                retry_after_seconds,
                retry_after,
                now=now,
            )
            should_retry = bool(transient) and task.attempt_count < task.max_attempts
            next_retry_at = None
            state = TaskState.FAILED
            if should_retry:
                delay = parsed_retry_after
                if delay is None:
                    delay = self._backoff_delay(task.attempt_count, jitter_seed=jitter_seed)
                delay = min(delay, self._retry_max_seconds)
                next_retry_at = now + timedelta(seconds=delay)
                state = TaskState.RETRY_WAIT
            elif transient and task.attempt_count >= task.max_attempts:
                state = TaskState.BLOCKED
            if transient:
                self._touch_circuit_breaker(task.session_ref, provider_id, failed=True, at=now)
            else:
                self._release_breaker_probe(task.session_ref, provider_id)
            active_lease_ref = task.lease_ref
            failed = self._replace_task(
                task,
                state=state,
                failure_code=code,
                failure_kind=failure_kind,
                blocked_reason=(
                    "retry_budget_exhausted"
                    if state is TaskState.BLOCKED
                    else task.blocked_reason
                ),
                retry_wait_until=next_retry_at,
                retry_after_seconds=parsed_retry_after,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                provider_id=provider_id,
                trace_id=trace_id,
                expired_at=None,
                updated_at=now,
            )
            self._tasks[task.task_ref] = failed
            if active_lease_ref is not None:
                self._leases.pop(active_lease_ref, None)
            event_type = f"task.{state.value}"
            self._record_event(
                session_ref=task.session_ref,
                event_type=event_type,
                payload={
                    "task_ref": task.task_ref,
                    "worker_id": worker_id,
                    "lease_ref": active_lease.lease_ref,
                    "failure_code": code,
                    "status_code": status_code,
                    "failure_kind": failure_kind,
                    "rate_limited": failure_kind == "rate_limited",
                    "retryable": bool(transient),
                    "attempt": task.attempt_count,
                    "max_attempts": task.max_attempts,
                    "retry_after_seconds": parsed_retry_after,
                    "next_retry_at": next_retry_at.isoformat() if next_retry_at else None,
                    "provider_id": provider_id,
                    "trace_id": trace_id,
                    "session_ref": task.session_ref,
                    "thread_ref": task.thread_ref,
                    "session_id": task.session_ref,
                    "thread_id": task.thread_ref,
                    "jitter_seed": jitter_seed,
                    "timeout": timeout,
                },
                created_at=now,
            )
            self._observations.append(
                self._observation(
                    failed,
                    event_type,
                    {
                        "failure_code": failed.failure_code,
                        "failure_kind": failure_kind,
                        "status_code": status_code,
                        "rate_limited": failure_kind == "rate_limited",
                    },
                    failed.evidence_refs,
                    failed.updated_at,
                )
            )
            return self._export_task(failed)

    def pause(
        self,
        *,
        session_ref: str,
        reason: str,
        actor_id: str,
        as_of: datetime | str | None = None,
    ) -> TeamAgentSession:
        with self._lock:
            session = self._session(session_ref)
            if (
                session.state is not SessionState.ACTIVE
                or session.kill_switch_engaged
            ):
                raise OrchestrationError("only active sessions can be paused")
            now = _utc(as_of)
            self._assert_event_time(session_ref, now)
            updated_session = TeamAgentSession(
                session_ref=session.session_ref,
                scope=session.scope,
                objective=session.objective,
                owner_id=session.owner_id,
                max_parallel=session.max_parallel,
                max_active_per_agent=session.max_active_per_agent,
                cost_budget_units=session.cost_budget_units,
                time_budget_seconds=session.time_budget_seconds,
                cost_used_units=session.cost_used_units,
                provider_buckets=dict(session.provider_buckets),
                state=SessionState.PAUSED,
                kill_switch_engaged=session.kill_switch_engaged,
                last_checkpoint_cursor=session.last_checkpoint_cursor,
                created_at=session.created_at,
                updated_at=now,
                authority_sha256=session.authority_sha256,
            )
            self._sessions[session_ref] = updated_session
            for task in list(self._tasks.values()):
                if task.session_ref != session_ref:
                    continue
                if task.state in {TaskState.QUEUED, TaskState.RETRY_WAIT}:
                    task_updated = self._replace_task(
                        task,
                        state=TaskState.PAUSED,
                        blocked_reason=_text(reason, "reason", 500),
                        updated_at=now,
                    )
                elif task.state is TaskState.RUNNING:
                    if task.lease_ref is not None:
                        self._leases.pop(task.lease_ref, None)
                    self._release_breaker_probe(task.session_ref, task.provider_id)
                    task_updated = self._replace_task(
                        task,
                        state=TaskState.PAUSED,
                        claimed_by=None,
                        lease_ref=None,
                        lease_expires_at=None,
                        blocked_reason=_text(reason, "reason", 500),
                        updated_at=now,
                    )
                else:
                    continue
                self._tasks[task.task_ref] = task_updated
            self._record_event(
                session_ref=session_ref,
                event_type="session.paused",
                payload={"reason": reason, "actor_id": actor_id},
                created_at=now,
            )
            self._observations.append(
                TeamAgentObservation(
                    self._next_control_observation_ref(session_ref),
                    session_ref,
                    f"{session_ref}:control",
                    "session.paused",
                    _hash({"reason": reason, "actor_id": actor_id}),
                    (),
                    now,
                )
            )
            return self._export_session(updated_session)

    def resume(
        self,
        *,
        session_ref: str,
        actor_id: str,
        reason: str = "manual resume",
        as_of: datetime | str | None = None,
    ) -> TeamAgentSession:
        with self._lock:
            session = self._session(session_ref)
            if session.kill_switch_engaged:
                raise OrchestrationError(
                    "kill switch must be released through release_kill_switch"
                )
            if session.state is not SessionState.PAUSED:
                raise OrchestrationError("only paused sessions can resume")
            now = _utc(as_of)
            self._assert_event_time(session_ref, now)
            updated_session = TeamAgentSession(
                session_ref=session.session_ref,
                scope=session.scope,
                objective=session.objective,
                owner_id=session.owner_id,
                max_parallel=session.max_parallel,
                max_active_per_agent=session.max_active_per_agent,
                cost_budget_units=session.cost_budget_units,
                time_budget_seconds=session.time_budget_seconds,
                cost_used_units=session.cost_used_units,
                provider_buckets=dict(session.provider_buckets),
                state=SessionState.ACTIVE,
                kill_switch_engaged=False,
                last_checkpoint_cursor=session.last_checkpoint_cursor,
                created_at=session.created_at,
                updated_at=now,
                authority_sha256=session.authority_sha256,
            )
            self._sessions[session_ref] = updated_session
            for task in list(self._tasks.values()):
                if task.session_ref == session_ref and task.state is TaskState.PAUSED:
                    retry_waiting = (
                        task.retry_wait_until is not None
                        and now < task.retry_wait_until
                    )
                    task_updated = self._replace_task(
                        task,
                        state=(
                            TaskState.RETRY_WAIT
                            if retry_waiting
                            else TaskState.QUEUED
                        ),
                        retry_wait_until=(
                            task.retry_wait_until if retry_waiting else None
                        ),
                        blocked_reason=None,
                        updated_at=now,
                    )
                    self._tasks[task.task_ref] = task_updated
            self._record_event(
                session_ref=session_ref,
                event_type="session.resumed",
                payload={"actor_id": actor_id, "reason": _text(reason, "reason", 500)},
                created_at=now,
            )
            self._observations.append(
                TeamAgentObservation(
                    self._next_control_observation_ref(session_ref),
                    session_ref,
                    f"{session_ref}:control",
                    "session.resumed",
                    _hash({"actor_id": actor_id, "reason": _text(reason, "reason", 500)}),
                    (),
                    now,
                )
            )
            return self._export_session(updated_session)

    def engage_kill_switch(
        self,
        *,
        session_ref: str,
        reason: str,
        actor_id: str,
        as_of: datetime | str | None = None,
    ) -> TeamAgentSession:
        with self._lock:
            session = self._session(session_ref)
            now = _utc(as_of)
            self._assert_event_time(session_ref, now)
            normalized_reason = _text(reason, "reason", 500)
            normalized_actor_id = _text(actor_id, "actor_id")
            updated = TeamAgentSession(
                session_ref=session.session_ref,
                scope=session.scope,
                objective=session.objective,
                owner_id=session.owner_id,
                max_parallel=session.max_parallel,
                max_active_per_agent=session.max_active_per_agent,
                cost_budget_units=session.cost_budget_units,
                time_budget_seconds=session.time_budget_seconds,
                cost_used_units=session.cost_used_units,
                provider_buckets=dict(session.provider_buckets),
                state=SessionState.CLOSED,
                kill_switch_engaged=True,
                last_checkpoint_cursor=session.last_checkpoint_cursor,
                created_at=session.created_at,
                updated_at=now,
                authority_sha256=session.authority_sha256,
            )
            self._sessions[session_ref] = updated
            for task in list(self._tasks.values()):
                if task.session_ref != session_ref:
                    continue
                if task.state in {TaskState.QUEUED, TaskState.RETRY_WAIT}:
                    self._tasks[task.task_ref] = self._replace_task(
                        task,
                        state=TaskState.PAUSED,
                        blocked_reason=normalized_reason,
                        updated_at=now,
                    )
                elif task.state is TaskState.RUNNING:
                    if task.lease_ref is not None:
                        self._leases.pop(task.lease_ref, None)
                    self._release_breaker_probe(task.session_ref, task.provider_id)
                    self._tasks[task.task_ref] = self._replace_task(
                        task,
                        state=TaskState.EXPIRED,
                        blocked_reason=normalized_reason,
                        claimed_by=None,
                        lease_ref=None,
                        lease_expires_at=None,
                        expired_at=now,
                        updated_at=now,
                    )
            self._record_event(
                session_ref=session_ref,
                event_type="session.kill_switch_engaged",
                payload={
                    "reason": normalized_reason,
                    "actor_id": normalized_actor_id,
                },
                created_at=now,
            )
            return self._export_session(updated)

    def release_kill_switch(
        self,
        *,
        session_ref: str,
        reason: str,
        actor_id: str,
        as_of: datetime | str | None = None,
    ) -> TeamAgentSession:
        with self._lock:
            session = self._session(session_ref)
            if not session.kill_switch_engaged:
                raise OrchestrationError("kill switch is not engaged")
            now = _utc(as_of)
            self._assert_event_time(session_ref, now)
            updated = TeamAgentSession(
                session_ref=session.session_ref,
                scope=session.scope,
                objective=session.objective,
                owner_id=session.owner_id,
                max_parallel=session.max_parallel,
                max_active_per_agent=session.max_active_per_agent,
                cost_budget_units=session.cost_budget_units,
                time_budget_seconds=session.time_budget_seconds,
                cost_used_units=session.cost_used_units,
                provider_buckets=dict(session.provider_buckets),
                state=SessionState.ACTIVE,
                kill_switch_engaged=False,
                last_checkpoint_cursor=session.last_checkpoint_cursor,
                created_at=session.created_at,
                updated_at=now,
                authority_sha256=session.authority_sha256,
            )
            self._sessions[session_ref] = updated
            for task in list(self._tasks.values()):
                if task.session_ref == session_ref and task.state is TaskState.PAUSED:
                    retry_waiting = (
                        task.retry_wait_until is not None
                        and now < task.retry_wait_until
                    )
                    self._tasks[task.task_ref] = self._replace_task(
                        task,
                        state=(
                            TaskState.RETRY_WAIT
                            if retry_waiting
                            else TaskState.QUEUED
                        ),
                        retry_wait_until=(
                            task.retry_wait_until if retry_waiting else None
                        ),
                        blocked_reason=None,
                        updated_at=now,
                    )
            self._record_event(
                session_ref=session_ref,
                event_type="session.kill_switch_released",
                payload={"reason": reason, "actor_id": actor_id},
                created_at=now,
            )
            return self._export_session(updated)

    kill_switch = engage_kill_switch
    clear_kill_switch = release_kill_switch
    stop = engage_kill_switch

    def handoff_task(
        self,
        *,
        session_ref: str,
        source_task_ref: str,
        source_thread_ref: str,
        target_thread_ref: str,
        target_role: str,
        input_evidence_refs: Sequence[str],
        acceptance_contract: Mapping[str, Any],
        trace_id: str,
        scope: Mapping[str, str] | ExactScope | None = None,
        created_at: datetime | str | None = None,
    ) -> TaskHandoff:
        with self._lock:
            session_ref = _text(session_ref, "session_ref")
            source_task_ref = _text(source_task_ref, "source_task_ref")
            source_thread_ref = _text(source_thread_ref, "source_thread_ref")
            target_thread_ref = _text(target_thread_ref, "target_thread_ref")
            target_role = _text(target_role, "target_role")
            trace_id = _text(trace_id, "trace_id")
            session = self._session(session_ref)
            if session.state is not SessionState.ACTIVE or session.kill_switch_engaged:
                raise OrchestrationError("handoffs require an active session")
            source_task = self._task(source_task_ref)
            source_thread = self._threads.get(source_thread_ref)
            if source_task.session_ref != session_ref:
                raise OrchestrationError("source task is outside the session")
            if source_thread is None or source_thread.session_ref != session_ref:
                raise OrchestrationError("source thread is outside the session")
            if source_task.thread_ref != source_thread_ref:
                raise OrchestrationError("source task/thread lineage conflict")
            if source_task.state is not TaskState.COMPLETED:
                raise OrchestrationError("handoff source task must be completed")
            target_thread = self._threads.get(target_thread_ref)
            if target_thread is None or target_thread.session_ref != session_ref:
                raise OrchestrationError("target thread is outside the session")
            if target_thread.parent_thread_ref != source_thread_ref:
                raise OrchestrationError(
                    "target thread does not descend from source thread"
                )
            handoff_ref = f"handoff-{source_task_ref}-{target_thread_ref}"
            if target_thread.handoff_ref not in {None, handoff_ref}:
                raise OrchestrationError(
                    "target thread is already bound to another handoff"
                )
            evidence = _normalize_refs(input_evidence_refs, "evidence_ref", maximum=20)
            if not evidence:
                raise OrchestrationError("handoff requires input Evidence")
            if not set(evidence) <= set(source_task.evidence_refs):
                raise OrchestrationError(
                    "handoff input Evidence must come from the source task"
                )
            normalized_contract = _normalize_result(acceptance_contract)
            if not normalized_contract:
                raise OrchestrationError("handoff requires an acceptance contract")
            if isinstance(scope, ExactScope):
                scope_payload = {
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "session_ref": session_ref,
                }
            else:
                scope_payload = _clone(
                    dict(
                        scope
                        or {
                            "tenant_ref": session.scope.tenant_ref,
                            "entity_ref": session.scope.entity_ref,
                            "store_ref": session.scope.store_ref,
                            "session_ref": session_ref,
                        }
                    )
                )
            required_scope = {
                "tenant_ref",
                "entity_ref",
                "store_ref",
                "session_ref",
            }
            if set(scope_payload) != required_scope:
                raise OrchestrationError("handoff scope is not exact")
            scope_payload = {
                str(key): _text(value, f"scope.{key}")
                for key, value in scope_payload.items()
            }
            expected_scope = {
                "tenant_ref": session.scope.tenant_ref,
                "entity_ref": session.scope.entity_ref,
                "store_ref": session.scope.store_ref,
                "session_ref": session_ref,
            }
            if scope_payload != expected_scope:
                raise OrchestrationError("handoff scope conflict")
            request_payload = {
                "session_ref": session_ref,
                "source_thread_ref": source_thread_ref,
                "target_thread_ref": target_thread_ref,
                "source_task_ref": source_task_ref,
                "target_role": target_role,
                "input_evidence_refs": list(evidence),
                "acceptance_contract": normalized_contract,
                "trace_id": trace_id,
                "scope": scope_payload,
            }
            existing = self._handoffs.get(handoff_ref)
            if existing is not None:
                existing_payload = {
                    "session_ref": existing.session_ref,
                    "source_thread_ref": existing.source_thread_ref,
                    "target_thread_ref": existing.target_thread_ref,
                    "source_task_ref": existing.source_task_ref,
                    "target_role": existing.target_role,
                    "input_evidence_refs": list(existing.input_evidence_refs),
                    "acceptance_contract": existing.acceptance_contract,
                    "trace_id": existing.trace_id,
                    "scope": existing.scope,
                }
                if _hash(request_payload) != _hash(existing_payload):
                    raise OrchestrationError("idempotency_conflict")
                return self._export_handoff(existing)
            if source_task.trace_id != trace_id:
                raise OrchestrationError("handoff trace must match source task")
            handoff_created_at = _utc(created_at)
            self._assert_event_time(session_ref, handoff_created_at)
            if (
                source_task.completed_at is None
                or handoff_created_at < source_task.completed_at
            ):
                raise OrchestrationError(
                    "handoff cannot precede source task completion"
                )
            handoff = TaskHandoff(
                handoff_ref=handoff_ref,
                session_ref=session_ref,
                source_thread_ref=source_thread_ref,
                target_thread_ref=target_thread_ref,
                source_task_ref=source_task_ref,
                target_role=target_role,
                input_evidence_refs=evidence,
                acceptance_contract=normalized_contract,
                trace_id=trace_id,
                scope=scope_payload,
                created_at=handoff_created_at,
            )
            self._handoffs[handoff_ref] = handoff
            self._tasks[source_task_ref] = self._replace_task(
                source_task,
                handoff_ref=handoff_ref,
                updated_at=handoff.created_at,
            )
            self._threads[target_thread_ref] = self._replace_thread(
                target_thread,
                handoff_ref=handoff_ref,
                target_role=target_role,
            )
            self._record_event(
                session_ref=session_ref,
                event_type="task.handoff",
                payload={
                    "handoff_ref": handoff_ref,
                    "task_ref": source_task_ref,
                    "source_task_ref": source_task_ref,
                    "source_thread_ref": source_thread_ref,
                    "target_thread_ref": target_thread_ref,
                    "target_role": target_role,
                    "input_evidence_refs": list(evidence),
                    "acceptance_contract": normalized_contract,
                    "trace_id": trace_id,
                    "scope": scope_payload,
                },
                created_at=handoff.created_at,
            )
            return self._export_handoff(handoff)

    create_handoff = handoff_task
    submit_handoff = handoff_task

    def expire_task(
        self,
        *,
        task_ref: str,
        as_of: datetime | str | None = None,
    ) -> TeamAgentTask:
        """Apply one due running-task expiry without advancing unrelated work.

        Durable restart recovery uses this narrow transition after it has locked
        the session sidecar.  ``tick`` remains the bulk scheduler projection,
        while this method prevents a restart from also making unrelated retry or
        circuit-breaker transitions as a side effect of recovering one lease.
        """

        with self._lock:
            task = self._task(task_ref)
            if task.state is not TaskState.RUNNING:
                raise OrchestrationError("only a running task can expire")
            now = _utc(as_of)
            self._assert_event_time(task.session_ref, now)
            session = self._session(task.session_ref)
            budget_deadlines: list[datetime] = []
            if session.time_budget_seconds is not None:
                budget_deadlines.append(
                    session.created_at
                    + timedelta(seconds=session.time_budget_seconds)
                )
            if task.time_budget_seconds is not None and task.started_at is not None:
                budget_deadlines.append(
                    task.started_at + timedelta(seconds=task.time_budget_seconds)
                )
            budget_deadline = min(budget_deadlines) if budget_deadlines else None
            budget_exhausted = (
                budget_deadline is not None and now >= budget_deadline
            )
            lease_expired = (
                task.lease_expires_at is not None and now >= task.lease_expires_at
            )
            if not lease_expired and not budget_exhausted:
                raise OrchestrationError("task lease and time budget are still active")
            return self._export_task(
                self._expire_running_task(
                    task,
                    now=now,
                    budget_exhausted=budget_exhausted,
                )
            )

    def tick(self, *, as_of: datetime | str | None = None) -> dict[str, Any]:
        with self._lock:
            now = _utc(as_of)
            for session_ref in self._sessions:
                self._assert_event_time(session_ref, now)
            expired_tasks: list[str] = []
            retry_ready_tasks: list[str] = []
            paused_tasks: list[str] = []
            next_check_at: datetime | None = None
            for task in list(self._tasks.values()):
                task_session = self._session(task.session_ref)
                budget_deadlines: list[datetime] = []
                if task_session.time_budget_seconds is not None:
                    budget_deadlines.append(
                        task_session.created_at
                        + timedelta(seconds=task_session.time_budget_seconds)
                    )
                if (
                    task.time_budget_seconds is not None
                    and task.started_at is not None
                ):
                    budget_deadlines.append(
                        task.started_at
                        + timedelta(seconds=task.time_budget_seconds)
                    )
                budget_deadline = (
                    min(budget_deadlines) if budget_deadlines else None
                )
                budget_exhausted = (
                    task.state is TaskState.RUNNING
                    and budget_deadline is not None
                    and now >= budget_deadline
                )
                lease_expired = (
                    task.state is TaskState.RUNNING
                    and task.lease_expires_at is not None
                    and now >= task.lease_expires_at
                )
                if lease_expired or budget_exhausted:
                    expired_tasks.append(task.task_ref)
                    self._expire_running_task(
                        task,
                        now=now,
                        budget_exhausted=budget_exhausted,
                    )
                    continue
                elif task.state is TaskState.RETRY_WAIT and task.retry_wait_until is not None:
                    if (
                        now >= task.retry_wait_until
                        and task_session.state is SessionState.ACTIVE
                        and not task_session.kill_switch_engaged
                    ):
                        retry_ready_tasks.append(task.task_ref)
                        self._tasks[task.task_ref] = self._replace_task(
                            task,
                            state=TaskState.QUEUED,
                            retry_wait_until=None,
                            updated_at=now,
                        )
                        self._record_event(
                            session_ref=task.session_ref,
                            event_type="task.retry_ready",
                            payload={"task_ref": task.task_ref},
                            created_at=now,
                        )
                    else:
                        next_check_at = self._min_dt(next_check_at, task.retry_wait_until)
                elif task.state is TaskState.PAUSED:
                    paused_tasks.append(task.task_ref)
                if task.state is TaskState.RUNNING and task.lease_expires_at is not None:
                    next_check_at = self._min_dt(next_check_at, task.lease_expires_at)
                    next_check_at = self._min_dt(next_check_at, budget_deadline)
            for (breaker_session_ref, provider_id), breaker in list(
                self._circuit_breakers.items()
            ):
                open_until = breaker.get("open_until")
                if isinstance(open_until, str):
                    open_until = _utc(open_until)
                    breaker["open_until"] = open_until
                if breaker["state"] == "open" and open_until is not None and open_until <= now:
                    breaker["state"] = "half_open"
                    breaker["probe_in_flight"] = False
                    self._record_event(
                        session_ref=breaker_session_ref,
                        event_type="circuit.half_open",
                        payload={
                            "provider_id": provider_id,
                            "failure_count": int(breaker["failure_count"]),
                            "open_until": open_until.isoformat(),
                        },
                        created_at=now,
                    )
                if breaker["state"] == "open" and open_until is not None:
                    next_check_at = self._min_dt(next_check_at, open_until)
            breaker_snapshot = {
                f"{session_ref}|{provider_id}": self._serialize_breaker(value)
                for (session_ref, provider_id), value in sorted(
                    self._circuit_breakers.items()
                )
            }
            safe_retry_tasks = [
                task_ref
                for task_ref in retry_ready_tasks
                if (
                    self._tasks[task_ref].provider_id is None
                    or self._read_circuit_breaker(
                        self._tasks[task_ref].session_ref,
                        self._tasks[task_ref].provider_id or "",
                    )["state"]
                    != CircuitState.OPEN.value
                )
            ]
            payload = {
                "contract_id": CONTRACT_ID,
                "checked_at": now.isoformat(),
                "expired_tasks": sorted(expired_tasks),
                "retry_ready_tasks": sorted(retry_ready_tasks),
                "paused_tasks": sorted(paused_tasks),
                "next_check_at": next_check_at.isoformat() if next_check_at else None,
                "safe_actions": [
                    {
                        "task_ref": task_ref,
                        "action": "inspect_and_reclaim",
                    }
                    for task_ref in sorted(expired_tasks)
                ]
                + [
                    {"task_ref": task_ref, "action": "claim_task"}
                    for task_ref in sorted(safe_retry_tasks)
                ],
                "circuit_breakers": breaker_snapshot,
            }
            payload["snapshot_sha256"] = _hash(payload)
            return payload

    def _expire_running_task(
        self,
        task: TeamAgentTask,
        *,
        now: datetime,
        budget_exhausted: bool,
    ) -> TeamAgentTask:
        """Transition a validated running task to its bounded expiry state."""

        lease_ref = task.lease_ref
        lease = self._leases.pop(lease_ref, None) if lease_ref is not None else None
        self._release_breaker_probe(
            task.session_ref,
            lease.provider_id if lease is not None else task.provider_id,
        )
        next_state = (
            TaskState.BLOCKED
            if budget_exhausted or task.attempt_count >= task.max_attempts
            else TaskState.EXPIRED
        )
        blocked_reason = (
            "time_budget_exhausted"
            if budget_exhausted
            else "retry_budget_exhausted"
            if next_state is TaskState.BLOCKED
            else "lease_expired"
        )
        updated = self._replace_task(
            task,
            state=next_state,
            claimed_by=None,
            lease_ref=None,
            lease_expires_at=None,
            # ``expired_at`` describes the EXPIRED state, not the wall-clock
            # instant that a RUNNING task was converted to another terminal
            # state.  Retry/time-budget exhaustion becomes BLOCKED and must
            # keep the same projection as the durable task row.
            expired_at=now if next_state is TaskState.EXPIRED else None,
            blocked_reason=blocked_reason,
            updated_at=now,
        )
        self._tasks[task.task_ref] = updated
        self._record_event(
            session_ref=task.session_ref,
            event_type="task.expired",
            payload={
                "task_ref": task.task_ref,
                "lease_ref": lease_ref,
                "next_state": next_state.value,
                "blocked_reason": blocked_reason,
            },
            created_at=now,
        )
        if next_state is TaskState.BLOCKED:
            self._observations.append(
                self._observation(
                    updated,
                    "task.blocked",
                    {"blocked_reason": blocked_reason},
                    updated.evidence_refs,
                    now,
                )
            )
        return updated

    def checkpoint_policy_config(self) -> dict[str, Any]:
        """Return the complete serializable policy that governs recovery."""

        with self._lock:
            return {
                "policy_id": CHECKPOINT_POLICY_ID,
                "policy_version": CHECKPOINT_POLICY_VERSION,
                "max_sessions": self._max_sessions,
                "lease_ttl_seconds": self._lease_ttl_seconds,
                "max_attempts": self._default_max_attempts,
                "retry_base_seconds": self._retry_base_seconds,
                "retry_max_seconds": self._retry_max_seconds,
                "jitter_strategy": (
                    "injected" if self._jitter_fn is not None else "seeded_sha256_v1"
                ),
                "jitter_policy_ref": self._jitter_policy_ref,
                "breaker_failure_threshold": self._breaker_failure_threshold,
                "breaker_cooldown_seconds": self._breaker_cooldown_seconds,
                "max_active_per_agent": self._default_max_active_per_agent,
                "provider_buckets": _clone(self._default_provider_buckets),
                "cost_budget_units": self._default_cost_budget_units,
                "time_budget_seconds": self._default_time_budget_seconds,
            }

    @property
    def checkpoint_policy_sha256(self) -> str:
        return _hash(self.checkpoint_policy_config())

    def checkpoint(self, *, session_ref: str | None = None) -> dict[str, Any]:
        with self._lock:
            sessions = (
                [self._session(session_ref)]
                if session_ref is not None
                else list(self._sessions.values())
            )
            session_refs = {item.session_ref for item in sessions}
            checkpoint_policy = self.checkpoint_policy_config()
            payload = {
                "contract_id": CONTRACT_ID,
                "contract_version": CONTRACT_VERSION,
                "checkpoint_policy": checkpoint_policy,
                "checkpoint_policy_sha256": _hash(checkpoint_policy),
                "canonical_projection_version": CANONICAL_PROJECTION_VERSION,
                "scope": (
                    {
                        "tenant_ref": sessions[0].scope.tenant_ref,
                        "entity_ref": sessions[0].scope.entity_ref,
                        "store_ref": sessions[0].scope.store_ref,
                    }
                    if len(sessions) == 1
                    else None
                ),
                "sessions": [self._serialize_session(item) for item in sorted(sessions, key=lambda item: item.session_ref)],
                "threads": [
                    self._serialize_thread(item)
                    for item in sorted(self._threads.values(), key=lambda item: item.thread_ref)
                    if item.session_ref in session_refs
                ],
                "tasks": [
                    self._serialize_task(item)
                    for item in sorted(self._tasks.values(), key=lambda item: item.task_ref)
                    if item.session_ref in session_refs
                ],
                "leases": [
                    self._serialize_lease(item)
                    for item in sorted(self._leases.values(), key=lambda item: item.lease_ref)
                    if item.session_ref in session_refs
                ],
                "observations": [
                    self._serialize_observation(item)
                    for item in self._observations
                    if item.session_ref in session_refs
                ],
                "events": [
                    self._serialize_event(item)
                    for item in self._events
                    if item.session_ref in session_refs
                ],
                "handoffs": [
                    self._serialize_handoff(item)
                    for item in sorted(self._handoffs.values(), key=lambda item: item.handoff_ref)
                    if item.session_ref in session_refs
                ],
                "idempotency": {
                    key: self._idempotency[key]
                    for key in sorted(
                        {
                            self._idempotency_slot(
                                task.session_ref,
                                task.idempotency_key,
                            )
                            for task in self._tasks.values()
                            if task.session_ref in session_refs
                        }
                    )
                    if key in self._idempotency
                },
                "durable_task_revisions": {
                    task.task_ref: self._durable_task_revisions[task.task_ref]
                    for task in sorted(
                        self._tasks.values(), key=lambda item: item.task_ref
                    )
                    if task.session_ref in session_refs
                    and task.task_ref in self._durable_task_revisions
                },
                "durable_task_requests": {
                    task.task_ref: self._durable_task_requests[task.task_ref]
                    for task in sorted(
                        self._tasks.values(), key=lambda item: item.task_ref
                    )
                    if task.session_ref in session_refs
                    and task.task_ref in self._durable_task_requests
                },
                "circuit_breakers": {
                    f"{session_ref_key}|{provider_id}": self._serialize_breaker(value)
                    for (session_ref_key, provider_id), value in sorted(self._circuit_breakers.items())
                    if session_ref_key in session_refs
                },
                "conflicts": _clone(
                    [
                        item
                        for item in self._conflicts
                        if session_ref is None
                        or session_ref in item.get("session_refs", ())
                    ]
                ),
            }
            payload["canonical_projection_sha256"] = _hash(
                self._canonical_projection(session_refs)
            )
            payload["checkpoint_sha256"] = _hash(payload)
            return payload

    @classmethod
    def restore(
        cls,
        checkpoint: Mapping[str, Any],
        *,
        scope: ExactScope | None = None,
        trusted_digest_anchor: str | None = None,
        expected_policy_sha256: str | None = None,
        jitter_fn: Callable[..., float] | None = None,
        jitter_policy_ref: str | None = None,
    ) -> TeamAgentCoordinator:
        payload = cls._verified_checkpoint_payload(
            checkpoint,
            trusted_digest_anchor=trusted_digest_anchor,
        )
        policy = cls._validated_checkpoint_policy(payload)
        policy_sha256 = str(payload["checkpoint_policy_sha256"])
        cls._assert_expected_policy(
            policy_sha256,
            expected_policy_sha256=expected_policy_sha256,
        )
        coordinator = cls._from_checkpoint_policy(
            policy,
            jitter_fn=jitter_fn,
            jitter_policy_ref=jitter_policy_ref,
        )
        coordinator.load_checkpoint(
            checkpoint,
            scope=scope,
            trusted_digest_anchor=trusted_digest_anchor,
            expected_policy_sha256=policy_sha256,
        )
        return coordinator

    def load_checkpoint(
        self,
        checkpoint: Mapping[str, Any],
        *,
        scope: ExactScope | None = None,
        trusted_digest_anchor: str | None = None,
        expected_policy_sha256: str | None = None,
    ) -> TeamAgentCoordinator:
        with self._lock:
            payload = self._verified_checkpoint_payload(
                checkpoint,
                trusted_digest_anchor=trusted_digest_anchor,
            )
            if payload.get("contract_id") != CONTRACT_ID:
                raise OrchestrationError("checkpoint contract drift")
            if payload.get("contract_version") != CONTRACT_VERSION:
                raise OrchestrationError("checkpoint contract version drift")
            policy = self._validated_checkpoint_policy(payload)
            policy_sha256 = str(payload["checkpoint_policy_sha256"])
            self._assert_expected_policy(
                policy_sha256,
                expected_policy_sha256=expected_policy_sha256,
            )
            if policy != self.checkpoint_policy_config():
                raise OrchestrationError("checkpoint policy conflict")
            if payload.get("canonical_projection_version") != CANONICAL_PROJECTION_VERSION:
                raise OrchestrationError("checkpoint canonical projection drift")
            projection_sha256 = payload.get("canonical_projection_sha256")
            if not _is_lower_hex_sha256(
                str(projection_sha256) if projection_sha256 is not None else None
            ):
                raise OrchestrationError("checkpoint canonical projection hash is invalid")
            checkpoint_scope = payload.get("scope")
            if scope is not None and checkpoint_scope is not None:
                restored_scope = ExactScope(
                    checkpoint_scope["tenant_ref"],
                    checkpoint_scope["entity_ref"],
                    checkpoint_scope["store_ref"],
                )
                if restored_scope != scope:
                    raise OrchestrationError("checkpoint scope conflict")
            sessions: dict[str, TeamAgentSession] = {}
            threads: dict[str, TeamAgentThread] = {}
            tasks: dict[str, TeamAgentTask] = {}
            observations: list[TeamAgentObservation] = []
            leases: dict[str, TaskLease] = {}
            events: list[ControlEvent] = []
            event_index: dict[str, ControlEvent] = {}
            event_positions: dict[str, int] = {}
            handoffs: dict[str, TaskHandoff] = {}
            circuit_breakers: dict[tuple[str, str], dict[str, Any]] = {}
            idempotency: dict[str, str] = {}
            durable_task_revisions: dict[str, int] = {}
            durable_task_requests: dict[str, str] = {}
            restored_idempotency = dict(payload.get("idempotency", {}))
            restored_durable_revisions = dict(
                payload.get("durable_task_revisions", {})
            )
            restored_durable_requests = dict(
                payload.get("durable_task_requests", {})
            )
            for item in payload.get("sessions", []):
                session = self._deserialize_session(item)
                if scope is not None and session.scope != scope:
                    raise OrchestrationError("checkpoint scope conflict")
                if session.session_ref in sessions:
                    raise OrchestrationError("checkpoint session identity conflict")
                sessions[session.session_ref] = session
            for item in payload.get("threads", []):
                thread = self._deserialize_thread(item)
                if thread.thread_ref in threads:
                    raise OrchestrationError("checkpoint thread identity conflict")
                threads[thread.thread_ref] = thread
            for item in payload.get("tasks", []):
                task = self._deserialize_task(item)
                if task.task_ref in tasks:
                    raise OrchestrationError("checkpoint task identity conflict")
                tasks[task.task_ref] = task
                slot = self._idempotency_slot(task.session_ref, task.idempotency_key)
                request_hash = restored_idempotency.get(slot)
                if request_hash is None:
                    # Compatibility with checkpoints emitted before idempotency
                    # keys were scoped by session.
                    request_hash = restored_idempotency.get(task.idempotency_key)
                if request_hash is not None:
                    idempotency[slot] = str(request_hash)
                durable_revision = restored_durable_revisions.get(task.task_ref)
                if durable_revision is not None:
                    if type(durable_revision) is not int or durable_revision < 0:
                        raise OrchestrationError(
                            "checkpoint durable task revision is invalid"
                        )
                    durable_task_revisions[task.task_ref] = durable_revision
                durable_request = restored_durable_requests.get(task.task_ref)
                if durable_request is not None:
                    if not _is_lower_hex_sha256(str(durable_request)):
                        raise OrchestrationError(
                            "checkpoint durable task request hash is invalid"
                        )
                    durable_task_requests[task.task_ref] = str(durable_request)
            if set(restored_durable_revisions) - set(tasks):
                raise OrchestrationError(
                    "checkpoint durable task revision references an unknown task"
                )
            if set(restored_durable_requests) - set(tasks):
                raise OrchestrationError(
                    "checkpoint durable task request references an unknown task"
                )
            for item in payload.get("leases", []):
                lease = self._deserialize_lease(item)
                if lease.lease_ref in leases:
                    raise OrchestrationError("checkpoint lease identity conflict")
                leases[lease.lease_ref] = lease
            for item in payload.get("observations", []):
                observation = self._deserialize_observation(item)
                observations.append(observation)
            for item in payload.get("events", []):
                event = self._deserialize_event(item)
                if event.cursor in event_index:
                    raise OrchestrationError("checkpoint event cursor conflict")
                events.append(event)
                event_index[event.cursor] = event
                event_positions[event.cursor] = len(events) - 1
            for item in payload.get("handoffs", []):
                handoff = self._deserialize_handoff(item)
                if handoff.handoff_ref in handoffs:
                    raise OrchestrationError("checkpoint handoff identity conflict")
                handoffs[handoff.handoff_ref] = handoff
            for key, value in payload.get("circuit_breakers", {}).items():
                session_key, provider_id = key.split("|", 1)
                circuit_breakers[(session_key, provider_id)] = self._deserialize_breaker(
                    value
                )
            staged = TeamAgentCoordinator(
                max_sessions=self._max_sessions,
                lease_ttl_seconds=self._lease_ttl_seconds,
                max_attempts=self._default_max_attempts,
                retry_base_seconds=self._retry_base_seconds,
                retry_max_seconds=self._retry_max_seconds,
                jitter_fn=self._jitter_fn,
                jitter_policy_ref=self._jitter_policy_ref,
                breaker_failure_threshold=self._breaker_failure_threshold,
                breaker_cooldown_seconds=self._breaker_cooldown_seconds,
                max_active_per_agent=self._default_max_active_per_agent,
                provider_buckets=self._default_provider_buckets,
                cost_budget_units=self._default_cost_budget_units,
                time_budget_seconds=self._default_time_budget_seconds,
            )
            staged._sessions = sessions
            staged._threads = threads
            staged._tasks = tasks
            staged._observations = observations
            staged._leases = leases
            staged._events = events
            staged._event_index = event_index
            staged._event_positions = event_positions
            staged._handoffs = handoffs
            staged._circuit_breakers = circuit_breakers
            staged._idempotency = idempotency
            staged._durable_task_revisions = durable_task_revisions
            staged._durable_task_requests = durable_task_requests
            staged._conflicts = [
                dict(item) for item in payload.get("conflicts", [])
            ]
            staged._validate_restored_state()
            staged._validate_event_chains()
            staged._validate_checkpoint_event_replay(
                expected_projection_sha256=str(projection_sha256)
            )
            self._sessions = staged._sessions
            self._threads = staged._threads
            self._tasks = staged._tasks
            self._observations = staged._observations
            self._leases = staged._leases
            self._events = staged._events
            self._event_index = staged._event_index
            self._event_positions = staged._event_positions
            self._handoffs = staged._handoffs
            self._circuit_breakers = staged._circuit_breakers
            self._idempotency = staged._idempotency
            self._durable_task_revisions = staged._durable_task_revisions
            self._durable_task_requests = staged._durable_task_requests
            self._conflicts = staged._conflicts
            return self

    def events(
        self,
        *,
        after_cursor: str | None = None,
        session_ref: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        with self._lock:
            if after_cursor is None:
                return tuple(
                    self._serialize_event(item)
                    for item in self._events
                    if session_ref is None or item.session_ref == session_ref
                )
            if after_cursor not in self._event_index:
                raise OrchestrationError("event cursor is unknown")
            cursor_event = self._event_index[after_cursor]
            if session_ref is not None and cursor_event.session_ref != session_ref:
                raise OrchestrationError("event cursor scope conflict")
            return tuple(
                self._serialize_event(item)
                for item in self._events
                if item.session_ref == cursor_event.session_ref
                and item.sequence > cursor_event.sequence
            )

    def merge_events(
        self,
        events: Sequence[Mapping[str, Any] | ControlEvent],
        *,
        expected_scope: ExactScope | Mapping[str, str] | None = None,
        expected_contract_id: str = CONTRACT_ID,
        expected_contract_version: str = CONTRACT_VERSION,
    ) -> EventMergeResult:
        with self._lock:
            expected_contract_id = _text(
                expected_contract_id,
                "expected_contract_id",
            )
            expected_contract_version = _text(
                expected_contract_version,
                "expected_contract_version",
            )
            expected_scope_payload: dict[str, str] | None = None
            if isinstance(expected_scope, ExactScope):
                expected_scope_payload = {
                    "tenant_ref": expected_scope.tenant_ref,
                    "entity_ref": expected_scope.entity_ref,
                    "store_ref": expected_scope.store_ref,
                }
            elif expected_scope is not None:
                required_scope = {"tenant_ref", "entity_ref", "store_ref"}
                if set(expected_scope) != required_scope:
                    raise OrchestrationError("expected event scope is not exact")
                expected_scope_payload = {
                    key: _text(expected_scope[key], f"expected_scope.{key}")
                    for key in sorted(required_scope)
                }
            pending: list[ControlEvent] = []
            pending_by_cursor: dict[str, ControlEvent] = {}
            duplicates: list[dict[str, Any]] = []
            conflict_reasons: list[str] = []
            incoming_session_refs: set[str] = set()
            last_by_session: dict[str, ControlEvent] = {}
            scope_by_session: dict[str, dict[str, str]] = {}
            for existing_event in self._events:
                last_by_session[existing_event.session_ref] = existing_event
                scope_by_session[existing_event.session_ref] = existing_event.scope
            for item in events:
                try:
                    event = self._deserialize_event(item)
                    self._validate_event(event)
                except (
                    KeyError,
                    OrchestrationError,
                    OverflowError,
                    TypeError,
                    ValueError,
                ) as exc:
                    reason = (
                        str(exc)
                        if isinstance(exc, OrchestrationError)
                        else "event payload conflict"
                    )
                    if "hash" in reason:
                        conflict_reasons.append("event hash conflict")
                    else:
                        conflict_reasons.append(reason)
                    continue
                incoming_session_refs.add(event.session_ref)
                if (
                    event.contract_id != expected_contract_id
                    or event.contract_version != expected_contract_version
                ):
                    conflict_reasons.append("event contract drift")
                    continue
                if (
                    expected_scope_payload is not None
                    and event.scope != expected_scope_payload
                ):
                    conflict_reasons.append("event scope conflict")
                    continue
                established_scope = scope_by_session.get(event.session_ref)
                if established_scope is not None and event.scope != established_scope:
                    conflict_reasons.append("event scope conflict")
                    continue
                scope_by_session[event.session_ref] = event.scope
                existing = self._event_index.get(event.cursor)
                if existing is not None:
                    if existing.event_hash != event.event_hash:
                        conflict_reasons.append("event hash conflict")
                    else:
                        duplicates.append(self._serialize_event(existing))
                    continue
                pending_duplicate = pending_by_cursor.get(event.cursor)
                if pending_duplicate is not None:
                    if pending_duplicate.event_hash != event.event_hash:
                        conflict_reasons.append("event hash conflict")
                    else:
                        duplicates.append(
                            self._serialize_event(pending_duplicate)
                        )
                    continue
                previous = last_by_session.get(event.session_ref)
                if previous is not None:
                    if event.sequence != previous.sequence + 1:
                        conflict_reasons.append("event sequence gap")
                        continue
                    if event.previous_hash != previous.event_hash:
                        conflict_reasons.append("event hash chain conflict")
                        continue
                    if event.previous_cursor != previous.cursor:
                        conflict_reasons.append("event cursor chain conflict")
                        continue
                    if event.created_at < previous.created_at:
                        conflict_reasons.append("event created_at regression")
                        continue
                elif event.sequence != 1:
                    conflict_reasons.append("event sequence gap")
                    continue
                last_by_session[event.session_ref] = event
                pending.append(event)
                pending_by_cursor[event.cursor] = event
            if len(incoming_session_refs) > 1:
                conflict_reasons.append("event batch spans multiple sessions")
            if conflict_reasons:
                reasons = tuple(sorted(set(conflict_reasons)))
                self._conflicts.append(
                    {
                        "kind": "event_merge",
                        "reasons": list(reasons),
                        "incoming_count": len(events),
                        "session_refs": sorted(incoming_session_refs),
                    }
                )
                return EventMergeResult(
                    status="conflict",
                    conflicts=reasons,
                    cursor=self._merge_cursor_for_sessions(incoming_session_refs),
                )
            merged = list(duplicates)
            staged = self._projection_clone()
            try:
                for event in pending:
                    staged._events.append(event)
                    staged._event_index[event.cursor] = event
                    staged._event_positions[event.cursor] = len(staged._events) - 1
                    staged._apply_event_projection(event)
                    merged.append(staged._serialize_event(event))
                staged._validate_event_chains()
                staged._validate_restored_state()
            except (
                KeyError,
                OrchestrationError,
                OverflowError,
                TypeError,
                ValueError,
            ) as exc:
                reason = (
                    str(exc)
                    if isinstance(exc, OrchestrationError)
                    else "event projection payload conflict"
                )
                reasons = (
                    "event hash conflict" if "hash" in reason else reason,
                )
                self._conflicts.append(
                    {
                        "kind": "event_merge",
                        "reasons": list(reasons),
                        "incoming_count": len(events),
                        "session_refs": sorted(incoming_session_refs),
                    }
                )
                return EventMergeResult(
                    status="conflict",
                    conflicts=reasons,
                    cursor=self._merge_cursor_for_sessions(incoming_session_refs),
                )
            self._sessions = staged._sessions
            self._threads = staged._threads
            self._tasks = staged._tasks
            self._observations = staged._observations
            self._leases = staged._leases
            self._events = staged._events
            self._event_index = staged._event_index
            self._event_positions = staged._event_positions
            self._handoffs = staged._handoffs
            self._circuit_breakers = staged._circuit_breakers
            self._idempotency = staged._idempotency
            self._durable_task_revisions = staged._durable_task_revisions
            self._durable_task_requests = staged._durable_task_requests
            return EventMergeResult(
                status="merged",
                events=tuple(merged),
                cursor=self._merge_cursor_for_sessions(incoming_session_refs),
            )

    def _merge_cursor_for_sessions(
        self,
        session_refs: set[str],
    ) -> str | None:
        """A single cursor is meaningful only for one incoming session."""

        if len(session_refs) != 1:
            return None
        return self._latest_cursor_for_sessions(session_refs)

    def _latest_cursor_for_sessions(
        self,
        session_refs: set[str],
    ) -> str | None:
        return next(
            (
                event.cursor
                for event in reversed(self._events)
                if event.session_ref in session_refs
            ),
            None,
        )

    def snapshot(self, *, session_ref: str) -> dict[str, Any]:
        with self._lock:
            session = self._session(session_ref)
            tasks = [task for task in self._tasks.values() if task.session_ref == session_ref]
            threads = [thread for thread in self._threads.values() if thread.session_ref == session_ref]
            leases = [
                lease
                for lease in self._leases.values()
                if lease.session_ref == session_ref and lease.state == "active"
            ]
            events = [event for event in self._events if event.session_ref == session_ref]
            session_conflicts = [
                item
                for item in self._conflicts
                if session_ref in item.get("session_refs", ())
            ]
            counts = Counter(task.state.value for task in tasks)
            retry_budget = {
                "max_attempts": MAX_TASK_ATTEMPTS,
                "attempts_in_flight": sum(
                    task.attempt_count for task in tasks if task.state is TaskState.RUNNING
                ),
                "retry_wait": sum(task.state is TaskState.RETRY_WAIT for task in tasks),
                "tasks": [
                    {
                        "task_ref": task.task_ref,
                        "attempt": task.attempt_count,
                        "max_attempts": task.max_attempts,
                        "remaining": max(0, task.max_attempts - task.attempt_count),
                        "next_attempt_at": (
                            task.retry_wait_until.isoformat()
                            if task.retry_wait_until
                            else None
                        ),
                    }
                    for task in sorted(tasks, key=lambda item: item.task_ref)
                ],
            }
            task_waves = self._task_waves(tasks)
            payload = {
                "contract_id": CONTRACT_ID,
                "session_ref": session_ref,
                "scope": {
                    "tenant_ref": session.scope.tenant_ref,
                    "entity_ref": session.scope.entity_ref,
                    "store_ref": session.scope.store_ref,
                },
                "state": session.state.value,
                "objective": session.objective,
                "max_parallel": session.max_parallel,
                "max_active_per_agent": session.max_active_per_agent,
                "cost_budget_units": session.cost_budget_units,
                "cost_used_units": session.cost_used_units,
                "time_budget_seconds": session.time_budget_seconds,
                "authority_sha256": session.authority_sha256,
                "task_counts": dict(sorted(counts.items())),
                "task_waves": task_waves,
                "waves": task_waves,
                "threads": [
                    {
                        "thread_ref": thread.thread_ref,
                        "title": thread.title,
                        "parent_thread_ref": thread.parent_thread_ref,
                        "parent_task_ref": thread.parent_task_ref,
                        "handoff_ref": thread.handoff_ref,
                        "target_role": thread.target_role,
                        "state": thread.state.value,
                    }
                    for thread in sorted(threads, key=lambda item: item.thread_ref)
                ],
                "tasks": [
                    {
                        "task_ref": task.task_ref,
                        "thread_ref": task.thread_ref,
                        "agent_id": task.agent_id,
                        "role": task.role,
                        "objective": task.objective,
                        "state": task.state.value,
                        "dependencies": task.dependencies,
                        "claimed_by": task.claimed_by,
                        "reviewer_id": task.reviewer_id,
                        "attempt_count": task.attempt_count,
                        "max_attempts": task.max_attempts,
                        "lease_ref": task.lease_ref,
                        "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
                        "retry_wait_until": task.retry_wait_until.isoformat() if task.retry_wait_until else None,
                        "retry_after_seconds": task.retry_after_seconds,
                        "failure_code": task.failure_code,
                        "failure_kind": task.failure_kind,
                        "blocked_reason": task.blocked_reason,
                        "evidence_refs": task.evidence_refs,
                        "requires_evidence": task.requires_evidence,
                        "provider_id": task.provider_id,
                        "trace_id": task.trace_id,
                        "parent_task_ref": task.parent_task_ref,
                        "handoff_ref": task.handoff_ref,
                        "cost_budget_units": task.cost_budget_units,
                        "cost_used_units": task.cost_used_units,
                        "time_budget_seconds": task.time_budget_seconds,
                    }
                    for task in sorted(tasks, key=lambda item: item.task_ref)
                ],
                "active_leases": [
                    {
                        "lease_ref": lease.lease_ref,
                        "task_ref": lease.task_ref,
                        "worker_id": lease.worker_id,
                        "expires_at": lease.expires_at.isoformat(),
                        "provider_id": lease.provider_id,
                        "trace_id": lease.trace_id,
                    }
                    for lease in sorted(leases, key=lambda item: item.lease_ref)
                ],
                "events": [self._serialize_event(event) for event in events],
                "event_cursor": events[-1].cursor if events else None,
                "retry_budget": retry_budget,
                "circuit_breakers": {
                    provider_id: self._serialize_breaker(value)
                    for (session_key, provider_id), value in sorted(self._circuit_breakers.items())
                    if session_key == session_ref
                },
                "conflict_count": len(session_conflicts),
                "conflicts": _clone(session_conflicts),
                "blocked_task_count": sum(
                    task.state in {TaskState.BLOCKED, TaskState.EXPIRED}
                    for task in tasks
                ),
                "observation_count": sum(
                    1 for observation in self._observations if observation.session_ref == session_ref
                ),
                "evidence_complete": all(
                    (not task.requires_evidence) or bool(task.evidence_refs)
                    for task in tasks
                ),
                "evidence_completeness": {
                    "required_tasks": sum(task.requires_evidence for task in tasks),
                    "complete_tasks": sum(
                        task.requires_evidence and bool(task.evidence_refs)
                        for task in tasks
                    ),
                    "missing_tasks": sorted(
                        task.task_ref
                        for task in tasks
                        if task.requires_evidence and not task.evidence_refs
                    ),
                },
                "authority": {
                    "formal_fact": False,
                    "finance_entry": False,
                    "approval": False,
                    "permit": False,
                    "external_write_allowed": False,
                },
                "control_boundary": {
                    "formal_fact": False,
                    "finance_entry": False,
                    "approval": False,
                    "permit": False,
                    "external_write_allowed": False,
                    "provider_invocation_allowed": False,
                    "database_write_allowed": False,
                },
            }
            payload["snapshot_sha256"] = _hash(payload)
            return payload

    def control_snapshot(self, *, session_ref: str) -> dict[str, Any]:
        return self.snapshot(session_ref=session_ref)

    def observations(self, *, session_ref: str) -> tuple[TeamAgentObservation, ...]:
        with self._lock:
            self._session(session_ref)
            return tuple(
                item for item in self._observations if item.session_ref == session_ref
            )

    def session(self, session_ref: str) -> TeamAgentSession:
        with self._lock:
            return self._export_session(self._session(session_ref))

    def task(self, task_ref: str) -> TeamAgentTask:
        with self._lock:
            return self._export_task(self._task(task_ref))

    def bind_durable_task_revision(
        self,
        *,
        task_ref: str,
        revision: int,
        request_sha256: str | None = None,
    ) -> int:
        """Bind a verified 0099 task revision into the session sidecar.

        This is recovery metadata, not a business transition.  The composite
        durable runtime calls it only after the corresponding task mutation
        has succeeded and before saving the session checkpoint.
        """

        with self._lock:
            task = self._task(task_ref)
            if type(revision) is not int or revision < 0:
                raise OrchestrationError("durable task revision must be non-negative")
            current = self._durable_task_revisions.get(task.task_ref)
            if current is not None and revision not in {current, current + 1}:
                raise OrchestrationError("durable task revision is not contiguous")
            if request_sha256 is not None:
                if not _is_lower_hex_sha256(request_sha256):
                    raise OrchestrationError(
                        "durable task request_sha256 must be lowercase SHA-256"
                    )
                current_request = self._durable_task_requests.get(task.task_ref)
                if current_request is not None and current_request != request_sha256:
                    raise OrchestrationError("durable task request identity changed")
                self._durable_task_requests[task.task_ref] = request_sha256
            self._durable_task_revisions[task.task_ref] = revision
            return revision

    def durable_task_revisions(self, *, session_ref: str) -> dict[str, int]:
        with self._lock:
            self._session(session_ref)
            return {
                task.task_ref: self._durable_task_revisions[task.task_ref]
                for task in sorted(self._tasks.values(), key=lambda item: item.task_ref)
                if task.session_ref == session_ref
                and task.task_ref in self._durable_task_revisions
            }

    def durable_task_requests(self, *, session_ref: str) -> dict[str, str]:
        with self._lock:
            self._session(session_ref)
            return {
                task.task_ref: self._durable_task_requests[task.task_ref]
                for task in sorted(self._tasks.values(), key=lambda item: item.task_ref)
                if task.session_ref == session_ref
                and task.task_ref in self._durable_task_requests
            }

    def lease(self, *, task_ref: str) -> TaskLease | None:
        with self._lock:
            task = self._task(task_ref)
            return self._leases.get(task.lease_ref) if task.lease_ref else None

    def breaker_state(
        self,
        *,
        session_ref: str,
        provider_id: str | None = None,
        provider_ref: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self._session(session_ref)
            provider = _matching_aliases(
                provider_id,
                provider_ref,
                primary_name="provider_id",
                alias_name="provider_ref",
            )
            if provider is None:
                raise OrchestrationError("provider_id must be 1 to 240 characters")
            return self._serialize_breaker(
                self._read_circuit_breaker(session_ref, provider)
            )

    circuit_breaker = breaker_state

    def handoffs(self, *, session_ref: str) -> tuple[TaskHandoff, ...]:
        with self._lock:
            self._session(session_ref)
            return tuple(
                self._export_handoff(handoff)
                for handoff in self._handoffs.values()
                if handoff.session_ref == session_ref
            )

    @property
    def conflict_count(self) -> int:
        with self._lock:
            return len(self._conflicts)

    def _session(self, session_ref: str) -> TeamAgentSession:
        try:
            return self._sessions[_text(session_ref, "session_ref")]
        except KeyError as exc:
            raise KeyError("TeamAgent session not found") from exc

    def _task(self, task_ref: str) -> TeamAgentTask:
        try:
            return self._tasks[_text(task_ref, "task_ref")]
        except KeyError as exc:
            raise KeyError("TeamAgent task not found") from exc

    def _store_thread(self, thread: TeamAgentThread) -> TeamAgentThread:
        self._threads[thread.thread_ref] = thread
        return thread

    def _replace_thread(
        self, thread: TeamAgentThread, **changes: Any
    ) -> TeamAgentThread:
        values = {
            field_name: getattr(thread, field_name)
            for field_name in thread.__dataclass_fields__
        }
        values.update(changes)
        return TeamAgentThread(**values)

    def _replace_task(self, task: TeamAgentTask, **changes: Any) -> TeamAgentTask:
        values = {field_name: getattr(task, field_name) for field_name in task.__dataclass_fields__}
        values.update(changes)
        return TeamAgentTask(**values)

    def _replace_session(
        self, session: TeamAgentSession, **changes: Any
    ) -> TeamAgentSession:
        values = {
            field_name: getattr(session, field_name)
            for field_name in session.__dataclass_fields__
        }
        values.update(changes)
        return TeamAgentSession(**values)

    def _export_session(self, session: TeamAgentSession) -> TeamAgentSession:
        return self._replace_session(
            session,
            provider_buckets=dict(session.provider_buckets),
        )

    def _export_thread(self, thread: TeamAgentThread) -> TeamAgentThread:
        """Return a detached public thread value.

        Thread records are frozen dataclasses today, but keeping an explicit
        export boundary makes the public read path consistent with sessions,
        tasks, and handoffs.  It also prevents a future mutable field from
        accidentally exposing coordinator-owned state.
        """

        return self._replace_thread(thread)

    def _export_task(self, task: TeamAgentTask) -> TeamAgentTask:
        return self._replace_task(
            task,
            result=_clone(task.result) if task.result is not None else None,
            acceptance_contract=(
                _clone(task.acceptance_contract)
                if task.acceptance_contract is not None
                else None
            ),
        )

    def _export_handoff(self, handoff: TaskHandoff) -> TaskHandoff:
        """Return a detached handoff, including copies of nested mappings."""

        return TaskHandoff(
            handoff_ref=handoff.handoff_ref,
            session_ref=handoff.session_ref,
            source_thread_ref=handoff.source_thread_ref,
            target_thread_ref=handoff.target_thread_ref,
            source_task_ref=handoff.source_task_ref,
            target_role=handoff.target_role,
            input_evidence_refs=tuple(handoff.input_evidence_refs),
            acceptance_contract=_clone(handoff.acceptance_contract),
            trace_id=handoff.trace_id,
            scope=_clone(handoff.scope),
            created_at=handoff.created_at,
        )

    @staticmethod
    def _callable_policy_ref(value: Callable[..., float] | None) -> str | None:
        if value is None:
            return None
        module = str(getattr(value, "__module__", type(value).__module__))
        qualname = str(
            getattr(
                value,
                "__qualname__",
                getattr(value, "__name__", type(value).__qualname__),
            )
        )
        return _text(f"{module}:{qualname}", "jitter_policy_ref", 300)

    @staticmethod
    def _verified_checkpoint_payload(
        checkpoint: Mapping[str, Any],
        *,
        trusted_digest_anchor: str | None = None,
    ) -> dict[str, Any]:
        payload = _clone(dict(checkpoint))
        supplied = payload.pop("checkpoint_sha256", None)
        supplied_digest = str(supplied) if supplied is not None else None
        if not _is_lower_hex_sha256(supplied_digest):
            raise OrchestrationError("checkpoint hash is invalid")
        if _hash(payload) != supplied_digest:
            raise OrchestrationError("checkpoint hash mismatch")
        if trusted_digest_anchor is not None:
            anchor = str(trusted_digest_anchor)
            if not _is_lower_hex_sha256(anchor):
                raise OrchestrationError("trusted digest anchor is invalid")
            if anchor != supplied_digest:
                raise OrchestrationError("trusted digest anchor mismatch")
        return payload

    @staticmethod
    def _assert_expected_policy(
        policy_sha256: str,
        *,
        expected_policy_sha256: str | None,
    ) -> None:
        if expected_policy_sha256 is None:
            return
        expected = str(expected_policy_sha256)
        if not _is_lower_hex_sha256(expected):
            raise OrchestrationError("expected checkpoint policy hash is invalid")
        if expected != policy_sha256:
            raise OrchestrationError("checkpoint policy fingerprint conflict")

    @staticmethod
    def _validated_checkpoint_policy(payload: Mapping[str, Any]) -> dict[str, Any]:
        raw_policy = payload.get("checkpoint_policy")
        if not isinstance(raw_policy, Mapping):
            raise OrchestrationError("checkpoint policy config is missing")
        policy = _clone(dict(raw_policy))
        supplied = payload.get("checkpoint_policy_sha256")
        supplied_digest = str(supplied) if supplied is not None else None
        if not _is_lower_hex_sha256(supplied_digest):
            raise OrchestrationError("checkpoint policy fingerprint is invalid")
        if _hash(policy) != supplied_digest:
            raise OrchestrationError("checkpoint policy fingerprint mismatch")
        expected_fields = {
            "policy_id",
            "policy_version",
            "max_sessions",
            "lease_ttl_seconds",
            "max_attempts",
            "retry_base_seconds",
            "retry_max_seconds",
            "jitter_strategy",
            "jitter_policy_ref",
            "breaker_failure_threshold",
            "breaker_cooldown_seconds",
            "max_active_per_agent",
            "provider_buckets",
            "cost_budget_units",
            "time_budget_seconds",
        }
        if set(policy) != expected_fields:
            raise OrchestrationError("checkpoint policy config is not closed")
        if (
            policy["policy_id"] != CHECKPOINT_POLICY_ID
            or policy["policy_version"] != CHECKPOINT_POLICY_VERSION
        ):
            raise OrchestrationError("checkpoint policy contract drift")
        required_integer_fields = {
            "max_sessions",
            "lease_ttl_seconds",
            "max_attempts",
            "retry_base_seconds",
            "retry_max_seconds",
            "breaker_failure_threshold",
            "breaker_cooldown_seconds",
            "max_active_per_agent",
        }
        if any(type(policy[field_name]) is not int for field_name in required_integer_fields):
            raise OrchestrationError("checkpoint policy integer field is invalid")
        for field_name in ("cost_budget_units", "time_budget_seconds"):
            if policy[field_name] is not None and type(policy[field_name]) is not int:
                raise OrchestrationError("checkpoint policy budget field is invalid")
        provider_buckets = policy["provider_buckets"]
        if not isinstance(provider_buckets, Mapping) or any(
            not isinstance(key, str) or type(value) is not int
            for key, value in provider_buckets.items()
        ):
            raise OrchestrationError("checkpoint provider bucket policy is invalid")
        strategy = policy["jitter_strategy"]
        jitter_policy_ref = policy["jitter_policy_ref"]
        if strategy not in {"seeded_sha256_v1", "injected"}:
            raise OrchestrationError("checkpoint jitter strategy is invalid")
        if strategy == "seeded_sha256_v1" and jitter_policy_ref is not None:
            raise OrchestrationError("checkpoint jitter policy reference is invalid")
        if strategy == "injected":
            _text(jitter_policy_ref, "checkpoint jitter policy reference", 300)
        return policy

    @classmethod
    def _from_checkpoint_policy(
        cls,
        policy: Mapping[str, Any],
        *,
        jitter_fn: Callable[..., float] | None,
        jitter_policy_ref: str | None,
    ) -> TeamAgentCoordinator:
        strategy = str(policy["jitter_strategy"])
        restored_jitter_ref: str | None = None
        if strategy == "seeded_sha256_v1":
            if jitter_fn is not None or jitter_policy_ref is not None:
                raise OrchestrationError("checkpoint jitter policy conflict")
        else:
            if jitter_fn is None and jitter_policy_ref is None:
                jitter_policy_ref = str(policy.get("jitter_policy_ref") or "")
                jitter_fn = _JITTER_POLICY_REGISTRY.get(jitter_policy_ref)
            if jitter_fn is None:
                raise OrchestrationError(
                    "checkpoint requires the injected jitter policy"
                )
            restored_jitter_ref = (
                _text(jitter_policy_ref, "jitter_policy_ref", 300)
                if jitter_policy_ref is not None
                else cls._callable_policy_ref(jitter_fn)
            )
            if restored_jitter_ref != policy["jitter_policy_ref"]:
                raise OrchestrationError("checkpoint jitter policy conflict")
        return cls(
            max_sessions=int(policy["max_sessions"]),
            lease_ttl_seconds=int(policy["lease_ttl_seconds"]),
            max_attempts=int(policy["max_attempts"]),
            retry_base_seconds=int(policy["retry_base_seconds"]),
            retry_max_seconds=int(policy["retry_max_seconds"]),
            jitter_fn=jitter_fn,
            jitter_policy_ref=restored_jitter_ref,
            breaker_failure_threshold=int(policy["breaker_failure_threshold"]),
            breaker_cooldown_seconds=int(policy["breaker_cooldown_seconds"]),
            max_active_per_agent=int(policy["max_active_per_agent"]),
            provider_buckets=dict(policy["provider_buckets"]),
            cost_budget_units=policy["cost_budget_units"],
            time_budget_seconds=policy["time_budget_seconds"],
        )

    def _canonical_projection(
        self,
        session_refs: set[str] | None = None,
    ) -> dict[str, Any]:
        included = set(self._sessions) if session_refs is None else set(session_refs)
        task_slots = {
            self._idempotency_slot(task.session_ref, task.idempotency_key)
            for task in self._tasks.values()
            if task.session_ref in included
        }
        return {
            "canonical_projection_version": CANONICAL_PROJECTION_VERSION,
            "sessions": [
                self._serialize_session(item)
                for item in sorted(
                    self._sessions.values(), key=lambda item: item.session_ref
                )
                if item.session_ref in included
            ],
            "threads": [
                self._serialize_thread(item)
                for item in sorted(
                    self._threads.values(), key=lambda item: item.thread_ref
                )
                if item.session_ref in included
            ],
            "tasks": [
                self._serialize_task(item)
                for item in sorted(self._tasks.values(), key=lambda item: item.task_ref)
                if item.session_ref in included
            ],
            "leases": [
                self._serialize_lease(item)
                for item in sorted(
                    self._leases.values(), key=lambda item: item.lease_ref
                )
                if item.session_ref in included
            ],
            "observations": [
                self._serialize_observation(item)
                for item in sorted(
                    self._observations,
                    key=lambda item: (
                        item.session_ref,
                        item.recorded_at,
                        item.observation_ref,
                    ),
                )
                if item.session_ref in included
            ],
            "handoffs": [
                self._serialize_handoff(item)
                for item in sorted(
                    self._handoffs.values(), key=lambda item: item.handoff_ref
                )
                if item.session_ref in included
            ],
            "idempotency": {
                key: self._idempotency[key]
                for key in sorted(task_slots)
                if key in self._idempotency
            },
            "circuit_breakers": {
                f"{session_ref}|{provider_id}": self._serialize_breaker(value)
                for (session_ref, provider_id), value in sorted(
                    self._circuit_breakers.items()
                )
                if session_ref in included
            },
        }

    def _validate_checkpoint_event_replay(
        self,
        *,
        expected_projection_sha256: str,
    ) -> None:
        session_refs = set(self._sessions)
        hydrated_sha256 = _hash(self._canonical_projection(session_refs))
        if hydrated_sha256 != expected_projection_sha256:
            raise OrchestrationError("checkpoint canonical projection hash mismatch")
        replay = self._from_checkpoint_policy(
            self.checkpoint_policy_config(),
            jitter_fn=self._jitter_fn,
            jitter_policy_ref=self._jitter_policy_ref,
        )
        events_by_session: dict[str, list[dict[str, Any]]] = {}
        for event in self._events:
            events_by_session.setdefault(event.session_ref, []).append(
                self._serialize_event(event)
            )
        for session_ref in sorted(events_by_session):
            result = replay.merge_events(
                tuple(events_by_session[session_ref]),
                expected_contract_id=CONTRACT_ID,
                expected_contract_version=CONTRACT_VERSION,
            )
            if result.status != "merged":
                reason = result.conflicts[0] if result.conflicts else "unknown conflict"
                raise OrchestrationError(
                    f"checkpoint event replay conflict: {reason}"
                )
        replay_sha256 = _hash(replay._canonical_projection(session_refs))
        if replay_sha256 != expected_projection_sha256:
            raise OrchestrationError(
                "checkpoint event replay canonical projection conflict"
            )

    def _projection_clone(self) -> TeamAgentCoordinator:
        staged = TeamAgentCoordinator(
            max_sessions=self._max_sessions,
            lease_ttl_seconds=self._lease_ttl_seconds,
            max_attempts=self._default_max_attempts,
            retry_base_seconds=self._retry_base_seconds,
            retry_max_seconds=self._retry_max_seconds,
            jitter_fn=self._jitter_fn,
            jitter_policy_ref=self._jitter_policy_ref,
            breaker_failure_threshold=self._breaker_failure_threshold,
            breaker_cooldown_seconds=self._breaker_cooldown_seconds,
            max_active_per_agent=self._default_max_active_per_agent,
            provider_buckets=self._default_provider_buckets,
            cost_budget_units=self._default_cost_budget_units,
            time_budget_seconds=self._default_time_budget_seconds,
        )
        staged._sessions = dict(self._sessions)
        staged._threads = dict(self._threads)
        staged._tasks = dict(self._tasks)
        staged._observations = list(self._observations)
        staged._leases = dict(self._leases)
        staged._events = list(self._events)
        staged._event_index = dict(self._event_index)
        staged._event_positions = dict(self._event_positions)
        staged._handoffs = dict(self._handoffs)
        staged._circuit_breakers = {
            key: self._deserialize_breaker(self._serialize_breaker(value))
            for key, value in self._circuit_breakers.items()
        }
        staged._idempotency = dict(self._idempotency)
        staged._durable_task_revisions = dict(self._durable_task_revisions)
        staged._durable_task_requests = dict(self._durable_task_requests)
        staged._conflicts = [dict(item) for item in self._conflicts]
        return staged

    def _assert_active_lease(
        self,
        task: TeamAgentTask,
        *,
        worker_id: str,
        as_of: datetime,
        expected_lease_ref: str | None = None,
    ) -> TaskLease:
        if task.lease_ref is None:
            raise OrchestrationError("task lease is missing")
        if (
            expected_lease_ref is not None
            and task.lease_ref != _text(expected_lease_ref, "lease_id")
        ):
            raise OrchestrationError("lease_id does not match")
        lease = self._leases.get(task.lease_ref)
        if (
            lease is None
            or lease.state != "active"
            or lease.task_ref != task.task_ref
            or lease.session_ref != task.session_ref
            or lease.thread_ref != task.thread_ref
            or lease.worker_id != worker_id
            or lease.attempt_count != task.attempt_count
        ):
            raise OrchestrationError("task lease is no longer active")
        if as_of >= lease.expires_at:
            self.tick(as_of=as_of)
            raise OrchestrationError("task lease has expired")
        return lease

    def _assert_fenced_active_lease(
        self,
        task: TeamAgentTask,
        *,
        worker_id: str,
        as_of: datetime,
        lease_id: str | None,
        lease_ref: str | None,
    ) -> TaskLease:
        normalized_lease_id = (
            _text(lease_id, "lease_id") if lease_id is not None else None
        )
        normalized_lease_ref = (
            _text(lease_ref, "lease_ref") if lease_ref is not None else None
        )
        if (
            normalized_lease_id is not None
            and normalized_lease_ref is not None
            and normalized_lease_id != normalized_lease_ref
        ):
            raise OrchestrationError("lease_id and lease_ref conflict")
        expected_lease_ref = normalized_lease_id or normalized_lease_ref
        if task.attempt_count > 1 and expected_lease_ref is None:
            raise OrchestrationError(
                "lease reference is required after the first attempt"
            )
        return self._assert_active_lease(
            task,
            worker_id=_text(worker_id, "worker_id"),
            as_of=as_of,
            expected_lease_ref=expected_lease_ref,
        )

    def _assert_acyclic(self, task_ref: str, dependencies: tuple[str, ...]) -> None:
        graph = {key: set(value.dependencies) for key, value in self._tasks.items()}
        graph[task_ref] = set(dependencies)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise OrchestrationError("task dependency cycle detected")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph.get(node, ()):
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        visit(task_ref)

    def _record_event(
        self,
        *,
        session_ref: str,
        event_type: str,
        payload: Mapping[str, Any],
        created_at: datetime,
    ) -> ControlEvent:
        session_ref = _text(session_ref, "session_ref")
        session = self._session(session_ref)
        created_at = _utc(created_at)
        self._assert_event_time(session_ref, created_at)
        sequence = sum(1 for event in self._events if event.session_ref == session_ref) + 1
        previous = next(
            (
                event
                for event in reversed(self._events)
                if event.session_ref == session_ref
            ),
            None,
        )
        payload_dict = _clone(dict(payload))
        event = ControlEvent(
            event_ref=f"evt-{session_ref}-{sequence}",
            session_ref=session_ref,
            sequence=sequence,
            cursor=f"{session_ref}:{sequence:020d}",
            previous_cursor=previous.cursor if previous else None,
            previous_hash=previous.event_hash if previous else "0" * 64,
            event_type=_text(event_type, "event_type", 80),
            payload=payload_dict,
            payload_sha256=_hash(payload_dict),
            contract_id=CONTRACT_ID,
            contract_version=CONTRACT_VERSION,
            created_at=created_at,
            scope={
                "tenant_ref": session.scope.tenant_ref,
                "entity_ref": session.scope.entity_ref,
                "store_ref": session.scope.store_ref,
            },
        )
        self._events.append(event)
        self._event_index[event.cursor] = event
        self._event_positions[event.cursor] = len(self._events) - 1
        self._sessions[session_ref] = self._replace_session(
            self._session(session_ref),
            last_checkpoint_cursor=event.cursor,
            updated_at=max(self._session(session_ref).updated_at, created_at),
        )
        return event

    def _assert_event_time(
        self,
        session_ref: str,
        created_at: datetime,
    ) -> None:
        previous = next(
            (
                event
                for event in reversed(self._events)
                if event.session_ref == session_ref
            ),
            None,
        )
        if previous is not None and created_at < previous.created_at:
            raise OrchestrationError("event created_at regression")

    def _apply_event_projection(self, event: ControlEvent) -> None:
        if not isinstance(event.payload, Mapping):
            raise OrchestrationError("event projection payload must be an object")
        payload = event.payload

        def projected_task() -> TeamAgentTask:
            task_ref = _text(payload.get("task_ref"), "task_ref")
            task = self._tasks.get(task_ref)
            if task is None or task.session_ref != event.session_ref:
                raise OrchestrationError("event projection task scope conflict")
            return task

        def projected_active_lease() -> tuple[TeamAgentTask, TaskLease]:
            task = projected_task()
            lease_ref = _text(payload.get("lease_ref"), "lease_ref")
            lease = self._leases.get(lease_ref)
            worker_id = _text(payload.get("worker_id"), "worker_id")
            if (
                task.state is not TaskState.RUNNING
                or task.lease_ref != lease_ref
                or task.claimed_by != worker_id
                or lease is None
                or lease.state != "active"
                or lease.task_ref != task.task_ref
                or lease.session_ref != task.session_ref
                or lease.thread_ref != task.thread_ref
                or lease.worker_id != worker_id
                or lease.attempt_count != task.attempt_count
            ):
                raise OrchestrationError(
                    "event projection active lease conflict"
                )
            return task, lease

        if event.event_type == "session.created":
            if event.session_ref in self._sessions:
                raise OrchestrationError("event projection session conflict")
            if len(self._sessions) >= self._max_sessions:
                raise OrchestrationError("event projection session capacity conflict")
            root_ref = f"{event.session_ref}:root"
            if root_ref in self._threads:
                raise OrchestrationError("event projection root thread conflict")
            provider_buckets = {
                _text(key, "provider_bucket"): int(value)
                for key, value in dict(
                    payload.get("provider_buckets", {})
                ).items()
            }
            if any(value < 1 for value in provider_buckets.values()):
                raise OrchestrationError(
                    "event projection provider bucket conflict"
                )
            max_parallel = int(payload.get("max_parallel", 3))
            if max_parallel < 1 or max_parallel > 32:
                raise OrchestrationError(
                    "event projection max_parallel conflict"
                )
            max_active_per_agent = int(
                payload.get("max_active_per_agent", 1)
            )
            if (
                max_active_per_agent < 1
                or max_active_per_agent > max_parallel
            ):
                raise OrchestrationError(
                    "event projection agent limit conflict"
                )
            cost_budget_units = payload.get("cost_budget_units")
            if cost_budget_units is not None:
                cost_budget_units = int(cost_budget_units)
                if cost_budget_units < 0:
                    raise OrchestrationError(
                        "event projection cost budget conflict"
                    )
            time_budget_seconds = payload.get("time_budget_seconds")
            if time_budget_seconds is not None:
                time_budget_seconds = int(time_budget_seconds)
                if time_budget_seconds <= 0:
                    raise OrchestrationError(
                        "event projection time budget conflict"
                    )
            authority_sha256 = payload.get("authority_sha256")
            if authority_sha256 is not None and not _is_lower_hex_sha256(
                authority_sha256
            ):
                raise OrchestrationError("event projection authority hash conflict")
            session = TeamAgentSession(
                session_ref=event.session_ref,
                scope=ExactScope(
                    event.scope["tenant_ref"],
                    event.scope["entity_ref"],
                    event.scope["store_ref"],
                ),
                objective=_text(payload.get("objective"), "objective", 2000),
                owner_id=_text(payload.get("owner_id"), "owner_id"),
                max_parallel=max_parallel,
                max_active_per_agent=max_active_per_agent,
                cost_budget_units=cost_budget_units,
                time_budget_seconds=time_budget_seconds,
                provider_buckets=provider_buckets,
                last_checkpoint_cursor=event.cursor,
                created_at=event.created_at,
                updated_at=event.created_at,
                authority_sha256=authority_sha256,
            )
            self._sessions[event.session_ref] = session
            self._threads[root_ref] = TeamAgentThread(
                thread_ref=root_ref,
                session_ref=event.session_ref,
                title="root",
                parent_thread_ref=None,
                created_at=event.created_at,
            )
            return

        session = self._sessions.get(event.session_ref)
        if session is None:
            raise OrchestrationError("event projection session is missing")
        expected_scope = {
            "tenant_ref": session.scope.tenant_ref,
            "entity_ref": session.scope.entity_ref,
            "store_ref": session.scope.store_ref,
        }
        if event.scope != expected_scope:
            raise OrchestrationError("event projection scope conflict")

        if event.event_type == "thread.forked":
            if session.state is not SessionState.ACTIVE or session.kill_switch_engaged:
                raise OrchestrationError(
                    "event projection session is not active"
                )
            thread_ref = _text(payload.get("thread_ref"), "thread_ref")
            if thread_ref in self._threads:
                raise OrchestrationError("event projection thread conflict")
            parent_thread_ref = _text(
                payload.get("parent_thread_ref"),
                "parent_thread_ref",
            )
            parent_thread = self._threads.get(parent_thread_ref)
            if parent_thread is None or parent_thread.session_ref != event.session_ref:
                raise OrchestrationError("event projection parent thread conflict")
            parent_task_ref = payload.get("parent_task_ref")
            if parent_task_ref is not None:
                parent_task = self._tasks.get(str(parent_task_ref))
                if parent_task is None or parent_task.session_ref != event.session_ref:
                    raise OrchestrationError("event projection parent task conflict")
            handoff_ref = payload.get("handoff_ref")
            if handoff_ref is not None:
                handoff_ref = _text(handoff_ref, "handoff_ref")
                handoff = self._handoffs.get(handoff_ref)
                if handoff is None or handoff.session_ref != event.session_ref:
                    raise OrchestrationError(
                        "event projection handoff conflict"
                    )
            self._threads[thread_ref] = TeamAgentThread(
                thread_ref=thread_ref,
                session_ref=event.session_ref,
                title=_text(payload.get("title"), "title"),
                parent_thread_ref=parent_thread_ref,
                parent_task_ref=(
                    _text(parent_task_ref, "parent_task_ref")
                    if parent_task_ref is not None
                    else None
                ),
                handoff_ref=handoff_ref,
                target_role=(
                    _text(payload.get("target_role"), "target_role")
                    if payload.get("target_role") is not None
                    else None
                ),
                created_at=event.created_at,
            )
        elif event.event_type == "task.submitted":
            if session.state is not SessionState.ACTIVE or session.kill_switch_engaged:
                raise OrchestrationError(
                    "event projection session is not active"
                )
            task_ref = _text(payload.get("task_ref"), "task_ref")
            if task_ref in self._tasks:
                raise OrchestrationError("event projection task conflict")
            thread_ref = _text(payload.get("thread_ref"), "thread_ref")
            thread = self._threads.get(thread_ref)
            if (
                thread is None
                or thread.session_ref != event.session_ref
                or thread.state is ThreadState.CLOSED
            ):
                raise OrchestrationError("event projection task thread conflict")
            dependencies = _normalize_refs(
                tuple(payload.get("dependencies", ())),
                "dependency_ref",
            )
            if task_ref in dependencies:
                raise OrchestrationError("task dependency cycle detected")
            for dependency_ref in dependencies:
                dependency = self._tasks.get(dependency_ref)
                if dependency is None or dependency.session_ref != event.session_ref:
                    raise OrchestrationError(
                        "event projection dependency scope conflict"
                    )
            parent_task_ref = payload.get("parent_task_ref")
            if parent_task_ref is not None:
                parent_task_ref = _text(parent_task_ref, "parent_task_ref")
                parent_task = self._tasks.get(parent_task_ref)
                if parent_task is None or parent_task.session_ref != event.session_ref:
                    raise OrchestrationError("event projection parent task conflict")
            handoff_ref = payload.get("handoff_ref")
            handoff: TaskHandoff | None = None
            if handoff_ref is not None:
                handoff_ref = _text(handoff_ref, "handoff_ref")
                handoff = self._handoffs.get(handoff_ref)
                if handoff is None or handoff.session_ref != event.session_ref:
                    raise OrchestrationError("event projection handoff conflict")
            evidence_refs = _normalize_refs(
                tuple(payload.get("evidence_refs", ())),
                "evidence_ref",
            )
            acceptance_contract = (
                _normalize_result(payload["acceptance_contract"])
                if payload.get("acceptance_contract") is not None
                else None
            )
            idempotency_key = _text(
                payload.get("idempotency_key"),
                "idempotency_key",
                300,
            )
            reviewer_role = payload.get("reviewer_role")
            reviewer_agent_id = payload.get("reviewer_agent_id")
            role = _text(payload.get("role"), "role")
            agent_id = _text(payload.get("agent_id"), "agent_id")
            trace_id = payload.get("trace_id")
            if trace_id is not None:
                trace_id = _text(trace_id, "trace_id")
            if handoff is not None:
                if thread_ref != handoff.target_thread_ref:
                    raise OrchestrationError(
                        "event projection handoff target thread conflict"
                    )
                if role != handoff.target_role:
                    raise OrchestrationError(
                        "event projection handoff target role conflict"
                    )
                if parent_task_ref != handoff.source_task_ref:
                    raise OrchestrationError(
                        "event projection handoff parent task conflict"
                    )
                if acceptance_contract != handoff.acceptance_contract:
                    raise OrchestrationError(
                        "event projection handoff contract conflict"
                    )
                if not set(handoff.input_evidence_refs) <= set(evidence_refs):
                    raise OrchestrationError(
                        "event projection handoff Evidence conflict"
                    )
                if trace_id != handoff.trace_id:
                    raise OrchestrationError(
                        "event projection handoff trace conflict"
                    )
            if reviewer_role is not None:
                reviewer_role = _text(reviewer_role, "reviewer_role")
                if reviewer_role == role:
                    raise OrchestrationError(
                        "independent review role must differ from author"
                    )
            if reviewer_agent_id is not None:
                reviewer_agent_id = _text(
                    reviewer_agent_id,
                    "reviewer_agent_id",
                )
                if reviewer_agent_id == agent_id:
                    raise OrchestrationError(
                        "independent reviewer must differ from author"
                    )
            max_attempts = int(payload.get("max_attempts", MAX_TASK_ATTEMPTS))
            if max_attempts < 1 or max_attempts > MAX_TASK_ATTEMPTS:
                raise OrchestrationError(
                    "event projection max attempts conflict"
                )
            evidence_required = payload.get("evidence_required", False)
            if not isinstance(evidence_required, bool):
                raise OrchestrationError(
                    "event projection Evidence requirement conflict"
                )
            provider_id = payload.get("provider_id")
            if provider_id is not None:
                provider_id = _text(provider_id, "provider_id")
            cost_budget_units = payload.get("cost_budget_units")
            if cost_budget_units is not None:
                cost_budget_units = int(cost_budget_units)
                if cost_budget_units < 0:
                    raise OrchestrationError(
                        "event projection task cost budget conflict"
                    )
            time_budget_seconds = payload.get("time_budget_seconds")
            if time_budget_seconds is not None:
                time_budget_seconds = int(time_budget_seconds)
                if time_budget_seconds <= 0:
                    raise OrchestrationError(
                        "event projection task time budget conflict"
                    )
            task = TeamAgentTask(
                task_ref=task_ref,
                session_ref=event.session_ref,
                thread_ref=thread_ref,
                agent_id=agent_id,
                role=role,
                objective=_text(payload.get("objective"), "objective", 2000),
                dependencies=dependencies,
                idempotency_key=idempotency_key,
                reviewer_id=reviewer_agent_id,
                max_attempts=max_attempts,
                evidence_refs=evidence_refs,
                trace_id=trace_id,
                provider_id=provider_id,
                parent_task_ref=parent_task_ref,
                handoff_ref=handoff_ref,
                requires_evidence=evidence_required,
                acceptance_contract=acceptance_contract,
                reviewer_role=reviewer_role,
                cost_budget_units=cost_budget_units,
                time_budget_seconds=time_budget_seconds,
                created_at=event.created_at,
                updated_at=event.created_at,
            )
            self._assert_acyclic(task_ref, dependencies)
            request_payload = {
                "session_ref": event.session_ref,
                "task_ref": task_ref,
                "thread_ref": thread_ref,
                "agent_id": agent_id,
                "role": role,
                "objective": task.objective,
                "dependencies": dependencies,
                "evidence_required": task.requires_evidence,
                "evidence_refs": evidence_refs,
                "acceptance_contract": acceptance_contract,
                "max_attempts": max_attempts,
                "provider_id": task.provider_id,
                "trace_id": task.trace_id,
                "parent_task_ref": parent_task_ref,
                "handoff_ref": handoff_ref,
                "reviewer_role": reviewer_role,
                "reviewer_agent_id": reviewer_agent_id,
                "cost_budget_units": task.cost_budget_units,
                "time_budget_seconds": task.time_budget_seconds,
            }
            slot = self._idempotency_slot(event.session_ref, idempotency_key)
            if slot in self._idempotency:
                raise OrchestrationError("idempotency_conflict")
            self._tasks[task_ref] = task
            self._idempotency[slot] = _hash(request_payload)
        elif event.event_type == "task.retry_budget_exhausted":
            task = projected_task()
            attempt_count = int(payload.get("attempt_count", -1))
            max_attempts = int(payload.get("max_attempts", -1))
            if (
                task.state
                not in {
                    TaskState.QUEUED,
                    TaskState.RETRY_WAIT,
                    TaskState.EXPIRED,
                }
                or attempt_count != task.attempt_count
                or max_attempts != task.max_attempts
                or attempt_count < max_attempts
                or payload.get("blocked_reason")
                != "retry_budget_exhausted"
            ):
                raise OrchestrationError(
                    "event projection retry budget conflict"
                )
            self._tasks[task.task_ref] = self._replace_task(
                task,
                state=TaskState.BLOCKED,
                blocked_reason="retry_budget_exhausted",
                retry_wait_until=None,
                retry_after_seconds=None,
                expired_at=None,
                updated_at=event.created_at,
            )
            self._observations.append(
                self._observation(
                    self._tasks[task.task_ref],
                    "task.blocked",
                    {"blocked_reason": "retry_budget_exhausted"},
                    self._tasks[task.task_ref].evidence_refs,
                    event.created_at,
                )
            )
        elif event.event_type == "task.time_budget_exhausted":
            task = projected_task()
            attempt_count = int(payload.get("attempt_count", -1))
            max_attempts = int(payload.get("max_attempts", -1))
            if (
                task.state
                not in {TaskState.QUEUED, TaskState.RETRY_WAIT, TaskState.EXPIRED}
                or task.lease_ref is not None
                or attempt_count != task.attempt_count
                or max_attempts != task.max_attempts
                or payload.get("blocked_reason") != "time_budget_exhausted"
            ):
                raise OrchestrationError("event projection time budget conflict")
            deadline = self._task_time_budget_deadline(task)
            if deadline is None or event.created_at < deadline:
                raise OrchestrationError("event projection time budget deadline conflict")
            blocked = self._replace_task(
                task,
                state=TaskState.BLOCKED,
                blocked_reason="time_budget_exhausted",
                retry_wait_until=None,
                retry_after_seconds=None,
                expired_at=None,
                updated_at=event.created_at,
            )
            self._tasks[task.task_ref] = blocked
            self._observations.append(
                self._observation(
                    blocked,
                    "task.blocked",
                    {"blocked_reason": "time_budget_exhausted"},
                    blocked.evidence_refs,
                    event.created_at,
                )
            )
        elif event.event_type == "task.claimed":
            task = projected_task()
            if session.state is not SessionState.ACTIVE or session.kill_switch_engaged:
                raise OrchestrationError("event projection session is not active")
            if task.state not in {
                TaskState.QUEUED,
                TaskState.RETRY_WAIT,
                TaskState.EXPIRED,
            }:
                raise OrchestrationError(
                    "event projection task is not claimable"
                )
            if (
                task.state is TaskState.RETRY_WAIT
                and task.retry_wait_until is not None
                and event.created_at < task.retry_wait_until
            ):
                raise OrchestrationError(
                    "event projection task retry is not ready"
                )
            if any(
                self._tasks[dependency].state is not TaskState.COMPLETED
                for dependency in task.dependencies
            ):
                raise OrchestrationError(
                    "event projection task dependencies are not complete"
                )
            lease_ref = _text(payload.get("lease_ref"), "lease_ref")
            if lease_ref in self._leases:
                raise OrchestrationError("event projection lease conflict")
            worker_id = _text(payload.get("worker_id"), "worker_id")
            attempt_count = int(payload.get("attempt_count", 0))
            if (
                attempt_count != task.attempt_count + 1
                or attempt_count > task.max_attempts
            ):
                raise OrchestrationError(
                    "event projection lease attempt conflict"
                )
            expires_at = _utc(payload.get("expires_at"))
            if (
                expires_at <= event.created_at
                or expires_at
                > event.created_at + timedelta(seconds=3600)
            ):
                raise OrchestrationError(
                    "event projection lease expiry conflict"
                )
            provider_id = payload.get("provider_id")
            trace_id = payload.get("trace_id")
            if provider_id is not None:
                provider_id = _text(provider_id, "provider_id")
            if trace_id is not None:
                trace_id = _text(trace_id, "trace_id")
            if task.provider_id is not None and provider_id != task.provider_id:
                raise OrchestrationError(
                    "event projection provider association conflict"
                )
            if task.trace_id is not None and trace_id != task.trace_id:
                raise OrchestrationError(
                    "event projection trace association conflict"
                )
            if (
                session.time_budget_seconds is not None
                and (event.created_at - session.created_at).total_seconds()
                >= session.time_budget_seconds
            ):
                raise OrchestrationError(
                    "event projection session time budget conflict"
                )
            if (
                task.time_budget_seconds is not None
                and task.started_at is not None
                and (event.created_at - task.started_at).total_seconds()
                >= task.time_budget_seconds
            ):
                raise OrchestrationError(
                    "event projection task time budget conflict"
                )
            budget_deadlines: list[datetime] = []
            if session.time_budget_seconds is not None:
                budget_deadlines.append(
                    session.created_at
                    + timedelta(seconds=session.time_budget_seconds)
                )
            if task.time_budget_seconds is not None:
                budget_deadlines.append(
                    (task.started_at or event.created_at)
                    + timedelta(seconds=task.time_budget_seconds)
                )
            if budget_deadlines and expires_at > min(budget_deadlines):
                raise OrchestrationError(
                    "event projection lease budget deadline conflict"
                )
            if (
                session.cost_budget_units is not None
                and session.cost_used_units >= session.cost_budget_units
                or task.cost_budget_units is not None
                and task.cost_used_units >= task.cost_budget_units
            ):
                raise OrchestrationError(
                    "event projection cost budget conflict"
                )
            if self._session_running_count(event.session_ref) >= session.max_parallel:
                raise OrchestrationError(
                    "event projection session parallelism conflict"
                )
            if (
                self._agent_running_count(event.session_ref, task.agent_id)
                >= session.max_active_per_agent
            ):
                raise OrchestrationError(
                    "event projection agent parallelism conflict"
                )
            if provider_id is not None:
                self._assert_provider_bucket(session, provider_id)
                breaker = self._circuit_breaker(
                    event.session_ref,
                    provider_id,
                )
                if (
                    breaker["state"] == CircuitState.OPEN.value
                    and breaker["open_until"] > event.created_at
                ):
                    raise OrchestrationError(
                        "event projection provider circuit is open"
                    )
                if (
                    breaker["state"] == CircuitState.HALF_OPEN.value
                    and breaker["probe_in_flight"]
                ):
                    raise OrchestrationError(
                        "event projection provider probe conflict"
                    )
            lease = TaskLease(
                lease_ref=lease_ref,
                task_ref=task.task_ref,
                session_ref=task.session_ref,
                thread_ref=task.thread_ref,
                worker_id=worker_id,
                claimed_at=event.created_at,
                heartbeat_at=event.created_at,
                expires_at=expires_at,
                attempt_count=attempt_count,
                provider_id=provider_id,
                trace_id=trace_id,
            )
            self._leases[lease_ref] = lease
            self._tasks[task.task_ref] = self._replace_task(
                task,
                state=TaskState.RUNNING,
                claimed_by=worker_id,
                lease_ref=lease_ref,
                lease_expires_at=expires_at,
                attempt_count=attempt_count,
                provider_id=provider_id,
                trace_id=trace_id,
                started_at=task.started_at or event.created_at,
                retry_wait_until=None,
                retry_after_seconds=None,
                expired_at=None,
                updated_at=event.created_at,
            )
            if provider_id is not None:
                breaker = self._circuit_breaker(event.session_ref, provider_id)
                if breaker["state"] in {
                    CircuitState.OPEN.value,
                    CircuitState.HALF_OPEN.value,
                }:
                    breaker["state"] = CircuitState.HALF_OPEN.value
                    breaker["probe_in_flight"] = True
        elif event.event_type == "task.heartbeat":
            task, lease = projected_active_lease()
            lease_ref = lease.lease_ref
            if event.created_at >= lease.expires_at:
                raise OrchestrationError(
                    "event projection heartbeat after lease expiry"
                )
            expires_at = _utc(payload.get("expires_at"))
            budget_deadlines: list[datetime] = []
            if session.time_budget_seconds is not None:
                budget_deadlines.append(
                    session.created_at
                    + timedelta(seconds=session.time_budget_seconds)
                )
            if task.time_budget_seconds is not None and task.started_at is not None:
                budget_deadlines.append(
                    task.started_at
                    + timedelta(seconds=task.time_budget_seconds)
                )
            budget_deadline = min(budget_deadlines) if budget_deadlines else None
            if (
                expires_at <= event.created_at
                or expires_at
                > event.created_at + timedelta(seconds=3600)
                or budget_deadline is not None
                and (
                    event.created_at >= budget_deadline
                    or expires_at > budget_deadline
                )
            ):
                raise OrchestrationError(
                    "event projection heartbeat expiry conflict"
                )
            self._leases[lease_ref] = TaskLease(
                lease_ref=lease.lease_ref,
                task_ref=lease.task_ref,
                session_ref=lease.session_ref,
                thread_ref=lease.thread_ref,
                worker_id=lease.worker_id,
                claimed_at=lease.claimed_at,
                heartbeat_at=event.created_at,
                expires_at=expires_at,
                attempt_count=lease.attempt_count,
                provider_id=lease.provider_id,
                trace_id=lease.trace_id,
            )
            self._tasks[task.task_ref] = self._replace_task(
                task,
                lease_expires_at=expires_at,
                updated_at=event.created_at,
            )
        elif event.event_type == "task.released":
            task, lease = projected_active_lease()
            lease_ref = lease.lease_ref
            if event.created_at >= lease.expires_at:
                raise OrchestrationError(
                    "event projection release after lease expiry"
                )
            reason = payload.get("reason")
            next_state = TaskState(payload.get("next_state"))
            if next_state not in {
                TaskState.QUEUED,
                TaskState.BLOCKED,
                TaskState.PAUSED,
                TaskState.EXPIRED,
            }:
                raise OrchestrationError(
                    "event projection release state conflict"
                )
            if next_state is not TaskState.QUEUED and reason is None:
                raise OrchestrationError(
                    "event projection release reason conflict"
                )
            self._leases[lease_ref] = TaskLease(
                lease_ref=lease.lease_ref,
                task_ref=lease.task_ref,
                session_ref=lease.session_ref,
                thread_ref=lease.thread_ref,
                worker_id=lease.worker_id,
                claimed_at=lease.claimed_at,
                heartbeat_at=lease.heartbeat_at,
                expires_at=lease.expires_at,
                attempt_count=lease.attempt_count,
                provider_id=lease.provider_id,
                trace_id=lease.trace_id,
                released_at=event.created_at,
                released_reason=reason,
                state="released",
            )
            self._release_breaker_probe(task.session_ref, lease.provider_id)
            self._tasks[task.task_ref] = self._replace_task(
                task,
                state=next_state,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                blocked_reason=reason or task.blocked_reason,
                updated_at=event.created_at,
            )
            if next_state is TaskState.BLOCKED:
                self._observations.append(
                    self._observation(
                        self._tasks[task.task_ref],
                        "task.blocked",
                        {"blocked_reason": self._tasks[task.task_ref].blocked_reason},
                        self._tasks[task.task_ref].evidence_refs,
                        event.created_at,
                    )
                )
        elif event.event_type == "task.completed":
            task, lease = projected_active_lease()
            if event.created_at >= lease.expires_at:
                raise OrchestrationError(
                    "event projection completion after lease expiry"
                )
            result = _normalize_result(payload.get("result", {}))
            if _hash(result) != payload.get("result_sha256"):
                raise OrchestrationError("event projection result hash conflict")
            evidence_refs = _normalize_refs(
                tuple(payload.get("evidence_refs", ())),
                "evidence_ref",
            )
            reviewer_id = payload.get("reviewer_id")
            cost_units = int(payload.get("cost_units", 0))
            if task.requires_evidence and not evidence_refs:
                raise OrchestrationError(
                    "event projection completion Evidence conflict"
                )
            if task.reviewer_role is not None and reviewer_id is None:
                raise OrchestrationError(
                    "event projection completion reviewer conflict"
                )
            if reviewer_id is not None:
                reviewer_id = _text(reviewer_id, "reviewer_id")
                if reviewer_id in {lease.worker_id, task.agent_id}:
                    raise OrchestrationError(
                        "event projection completion reviewer conflict"
                    )
            if cost_units < 0:
                raise OrchestrationError(
                    "event projection completion cost conflict"
                )
            if (
                task.cost_budget_units is not None
                and task.cost_used_units + cost_units > task.cost_budget_units
                or session.cost_budget_units is not None
                and session.cost_used_units + cost_units
                > session.cost_budget_units
            ):
                raise OrchestrationError(
                    "event projection completion budget conflict"
                )
            event_trace_id = payload.get("trace_id")
            if event_trace_id != lease.trace_id:
                raise OrchestrationError(
                    "event projection completion trace conflict"
                )
            if task.lease_ref is not None:
                self._leases.pop(task.lease_ref, None)
            completed = self._replace_task(
                task,
                state=TaskState.COMPLETED,
                result=result,
                evidence_refs=evidence_refs,
                reviewer_id=reviewer_id,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                cost_used_units=task.cost_used_units + cost_units,
                trace_id=payload.get("trace_id") or task.trace_id,
                completed_at=event.created_at,
                updated_at=event.created_at,
            )
            self._tasks[task.task_ref] = completed
            self._sessions[session.session_ref] = self._replace_session(
                session,
                cost_used_units=session.cost_used_units + cost_units,
            )
            self._touch_circuit_breaker(
                task.session_ref,
                task.provider_id,
                failed=False,
                at=event.created_at,
            )
            self._observations.append(
                self._observation(
                    completed,
                    "task.completed",
                    result,
                    evidence_refs,
                    event.created_at,
                )
            )
        elif event.event_type in {
            "task.retry_wait",
            "task.failed",
            "task.blocked",
        }:
            task, lease = projected_active_lease()
            if event.created_at >= lease.expires_at:
                raise OrchestrationError(
                    "event projection failure after lease expiry"
                )
            next_state = TaskState(event.event_type.removeprefix("task."))
            provider_id = payload.get("provider_id")
            trace_id = payload.get("trace_id")
            if provider_id != lease.provider_id or task.provider_id != lease.provider_id:
                raise OrchestrationError(
                    "event projection failure provider conflict"
                )
            if trace_id != lease.trace_id or task.trace_id != lease.trace_id:
                raise OrchestrationError(
                    "event projection failure trace conflict"
                )
            attempt = int(payload.get("attempt", 0))
            max_attempts = int(payload.get("max_attempts", 0))
            if attempt != task.attempt_count or max_attempts != task.max_attempts:
                raise OrchestrationError(
                    "event projection failure attempt conflict"
                )
            failure_code = _text(
                payload.get("failure_code"),
                "failure_code",
                120,
            )
            failure_kind = _text(
                payload.get("failure_kind"),
                "failure_kind",
                120,
            )
            classified_kind = self._classify_failure(
                failure_code,
                payload.get("status_code"),
                False,
            )
            provider_failure_kinds = {
                "rate_limited",
                "server_error",
                "timeout",
            }
            if (
                classified_kind in provider_failure_kinds
                and failure_kind != classified_kind
            ):
                raise OrchestrationError(
                    "event projection failure classification conflict"
                )
            retryable = bool(payload.get("retryable"))
            expected_state = TaskState.FAILED
            if retryable and attempt < max_attempts:
                expected_state = TaskState.RETRY_WAIT
            elif retryable:
                expected_state = TaskState.BLOCKED
            if next_state is not expected_state:
                raise OrchestrationError(
                    "event projection failure state conflict"
                )
            if bool(payload.get("rate_limited")) != (
                failure_kind == "rate_limited"
            ):
                raise OrchestrationError(
                    "event projection rate limit classification conflict"
                )
            if task.lease_ref is not None:
                self._leases.pop(task.lease_ref, None)
            next_retry_at = payload.get("next_retry_at")
            parsed_next_retry_at = (
                _utc(next_retry_at) if next_retry_at is not None else None
            )
            if expected_state is TaskState.RETRY_WAIT:
                if (
                    parsed_next_retry_at is None
                    or parsed_next_retry_at < event.created_at
                    or parsed_next_retry_at
                    > event.created_at
                    + timedelta(seconds=self._retry_max_seconds)
                ):
                    raise OrchestrationError(
                        "event projection retry deadline conflict"
                    )
            elif parsed_next_retry_at is not None:
                raise OrchestrationError(
                    "event projection unexpected retry deadline"
                )
            failed = self._replace_task(
                task,
                state=next_state,
                failure_code=failure_code,
                failure_kind=failure_kind,
                blocked_reason=(
                    "retry_budget_exhausted"
                    if next_state is TaskState.BLOCKED
                    else task.blocked_reason
                ),
                retry_wait_until=parsed_next_retry_at,
                retry_after_seconds=payload.get("retry_after_seconds"),
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                provider_id=provider_id,
                trace_id=trace_id,
                expired_at=None,
                updated_at=event.created_at,
            )
            self._tasks[task.task_ref] = failed
            if retryable:
                self._touch_circuit_breaker(
                    task.session_ref,
                    provider_id,
                    failed=True,
                    at=event.created_at,
                )
            else:
                self._release_breaker_probe(task.session_ref, provider_id)
            self._observations.append(
                self._observation(
                    failed,
                    event.event_type,
                    {
                        "failure_code": failed.failure_code,
                        "failure_kind": failure_kind,
                        "status_code": payload.get("status_code"),
                        "rate_limited": bool(payload.get("rate_limited")),
                    },
                    failed.evidence_refs,
                    event.created_at,
                )
            )
        elif event.event_type == "task.expired":
            task = projected_task()
            lease_ref = _text(payload.get("lease_ref"), "lease_ref")
            lease = self._leases.get(lease_ref)
            blocked_reason = payload.get("blocked_reason", "lease_expired")
            budget_deadlines: list[datetime] = []
            if session.time_budget_seconds is not None:
                budget_deadlines.append(
                    session.created_at
                    + timedelta(seconds=session.time_budget_seconds)
                )
            if task.time_budget_seconds is not None and task.started_at is not None:
                budget_deadlines.append(
                    task.started_at
                    + timedelta(seconds=task.time_budget_seconds)
                )
            budget_deadline = min(budget_deadlines) if budget_deadlines else None
            budget_exhausted = (
                blocked_reason == "time_budget_exhausted"
                and budget_deadline is not None
                and event.created_at >= budget_deadline
            )
            if (
                task.state is not TaskState.RUNNING
                or task.lease_ref != lease_ref
                or lease is None
                or lease.state != "active"
                or lease.attempt_count != task.attempt_count
                or not budget_exhausted
                and event.created_at < lease.expires_at
            ):
                raise OrchestrationError(
                    "event projection expired lease conflict"
                )
            next_state = TaskState(
                payload.get("next_state", TaskState.EXPIRED)
            )
            expected_state = (
                TaskState.BLOCKED
                if budget_exhausted
                else TaskState.EXPIRED
                if task.attempt_count < task.max_attempts
                else TaskState.BLOCKED
            )
            if next_state is not expected_state:
                raise OrchestrationError(
                    "event projection expired state conflict"
                )
            self._leases.pop(lease_ref, None)
            self._release_breaker_probe(task.session_ref, lease.provider_id)
            self._tasks[task.task_ref] = self._replace_task(
                task,
                state=next_state,
                claimed_by=None,
                lease_ref=None,
                lease_expires_at=None,
                expired_at=(
                    event.created_at
                    if next_state is TaskState.EXPIRED
                    else None
                ),
                blocked_reason=blocked_reason,
                updated_at=event.created_at,
            )
            if next_state is TaskState.BLOCKED:
                self._observations.append(
                    self._observation(
                        self._tasks[task.task_ref],
                        "task.blocked",
                        {"blocked_reason": blocked_reason},
                        self._tasks[task.task_ref].evidence_refs,
                        event.created_at,
                    )
                )
        elif event.event_type == "task.retry_ready":
            task = projected_task()
            if (
                task.state is not TaskState.RETRY_WAIT
                or task.retry_wait_until is None
                or event.created_at < task.retry_wait_until
            ):
                raise OrchestrationError(
                    "event projection retry readiness conflict"
                )
            self._tasks[task.task_ref] = self._replace_task(
                task,
                state=TaskState.QUEUED,
                retry_wait_until=None,
                updated_at=event.created_at,
            )
        elif event.event_type == "session.paused":
            reason = _text(payload.get("reason"), "reason", 500)
            self._sessions[event.session_ref] = self._replace_session(
                session,
                state=SessionState.PAUSED,
                updated_at=event.created_at,
            )
            for task in list(self._tasks.values()):
                if task.session_ref != event.session_ref:
                    continue
                if task.state is TaskState.RUNNING and task.lease_ref is not None:
                    self._leases.pop(task.lease_ref, None)
                    self._release_breaker_probe(task.session_ref, task.provider_id)
                if task.state in {
                    TaskState.QUEUED,
                    TaskState.RETRY_WAIT,
                    TaskState.RUNNING,
                }:
                    self._tasks[task.task_ref] = self._replace_task(
                        task,
                        state=TaskState.PAUSED,
                        claimed_by=None,
                        lease_ref=None,
                        lease_expires_at=None,
                        blocked_reason=reason,
                        updated_at=event.created_at,
                    )
            actor_id = payload.get("actor_id")
            self._observations.append(
                TeamAgentObservation(
                    self._next_control_observation_ref(event.session_ref),
                    event.session_ref,
                    f"{event.session_ref}:control",
                    "session.paused",
                    _hash({"reason": reason, "actor_id": actor_id}),
                    (),
                    event.created_at,
                )
            )
        elif event.event_type in {
            "session.resumed",
            "session.kill_switch_released",
        }:
            if event.event_type == "session.resumed" and session.kill_switch_engaged:
                raise OrchestrationError("event projection kill switch conflict")
            self._sessions[event.session_ref] = self._replace_session(
                session,
                state=SessionState.ACTIVE,
                kill_switch_engaged=False,
                updated_at=event.created_at,
            )
            for task in list(self._tasks.values()):
                if task.session_ref == event.session_ref and task.state is TaskState.PAUSED:
                    retry_waiting = (
                        task.retry_wait_until is not None
                        and event.created_at < task.retry_wait_until
                    )
                    self._tasks[task.task_ref] = self._replace_task(
                        task,
                        state=(
                            TaskState.RETRY_WAIT
                            if retry_waiting
                            else TaskState.QUEUED
                        ),
                        retry_wait_until=(
                            task.retry_wait_until if retry_waiting else None
                        ),
                        blocked_reason=None,
                        updated_at=event.created_at,
                    )
            if event.event_type == "session.resumed":
                actor_id = payload.get("actor_id")
                reason = _text(payload.get("reason"), "reason", 500)
                self._observations.append(
                    TeamAgentObservation(
                        self._next_control_observation_ref(event.session_ref),
                        event.session_ref,
                        f"{event.session_ref}:control",
                        "session.resumed",
                        _hash({"actor_id": actor_id, "reason": reason}),
                        (),
                        event.created_at,
                    )
                )
        elif event.event_type == "session.kill_switch_engaged":
            reason = _text(payload.get("reason"), "reason", 500)
            self._sessions[event.session_ref] = self._replace_session(
                session,
                state=SessionState.CLOSED,
                kill_switch_engaged=True,
                updated_at=event.created_at,
            )
            for task in list(self._tasks.values()):
                if task.session_ref != event.session_ref:
                    continue
                if task.state in {TaskState.QUEUED, TaskState.RETRY_WAIT}:
                    self._tasks[task.task_ref] = self._replace_task(
                        task,
                        state=TaskState.PAUSED,
                        blocked_reason=reason,
                        updated_at=event.created_at,
                    )
                elif task.state is TaskState.RUNNING:
                    if task.lease_ref is not None:
                        self._leases.pop(task.lease_ref, None)
                    self._release_breaker_probe(task.session_ref, task.provider_id)
                    self._tasks[task.task_ref] = self._replace_task(
                        task,
                        state=TaskState.EXPIRED,
                        blocked_reason=reason,
                        claimed_by=None,
                        lease_ref=None,
                        lease_expires_at=None,
                        expired_at=event.created_at,
                        updated_at=event.created_at,
                    )
        elif event.event_type == "circuit.half_open":
            provider_id = _text(payload.get("provider_id"), "provider_id")
            breaker = self._circuit_breaker(event.session_ref, provider_id)
            open_until = breaker.get("open_until")
            if isinstance(open_until, str):
                open_until = _utc(open_until)
            expected_open_until = _utc(payload.get("open_until"))
            if (
                breaker.get("state") != CircuitState.OPEN.value
                or open_until != expected_open_until
                or open_until is None
                or open_until > event.created_at
                or int(breaker.get("failure_count", 0))
                != int(payload.get("failure_count", -1))
            ):
                raise OrchestrationError(
                    "event projection circuit half-open conflict"
                )
            breaker["state"] = CircuitState.HALF_OPEN.value
            breaker["probe_in_flight"] = False
        elif event.event_type == "task.handoff":
            task = projected_task()
            if task.state is not TaskState.COMPLETED:
                raise OrchestrationError(
                    "event projection handoff source must be completed"
                )
            handoff_ref = _text(payload.get("handoff_ref"), "handoff_ref")
            if handoff_ref in self._handoffs:
                raise OrchestrationError("event projection handoff conflict")
            scope = dict(payload.get("scope", {}))
            source_thread_ref = _text(
                payload.get("source_thread_ref"),
                "source_thread_ref",
            )
            target_thread_ref = _text(
                payload.get("target_thread_ref"),
                "target_thread_ref",
            )
            source_thread = self._threads.get(source_thread_ref)
            target_thread = self._threads.get(target_thread_ref)
            if (
                source_thread is None
                or source_thread.session_ref != event.session_ref
                or task.thread_ref != source_thread_ref
                or target_thread is None
                or target_thread.session_ref != event.session_ref
                or target_thread.parent_thread_ref != source_thread_ref
            ):
                raise OrchestrationError(
                    "event projection handoff lineage conflict"
                )
            if target_thread.handoff_ref not in {None, handoff_ref}:
                raise OrchestrationError(
                    "event projection target thread handoff conflict"
                )
            evidence_refs = _normalize_refs(
                tuple(payload.get("input_evidence_refs", ())),
                "evidence_ref",
            )
            if not evidence_refs or not set(evidence_refs) <= set(
                task.evidence_refs
            ):
                raise OrchestrationError(
                    "event projection handoff Evidence conflict"
                )
            trace_id = _text(payload.get("trace_id"), "trace_id")
            if trace_id != task.trace_id:
                raise OrchestrationError(
                    "event projection handoff trace conflict"
                )
            acceptance_contract = _normalize_result(
                payload.get("acceptance_contract", {})
            )
            if not acceptance_contract:
                raise OrchestrationError(
                    "event projection handoff contract is incomplete"
                )
            handoff = TaskHandoff(
                handoff_ref=handoff_ref,
                session_ref=event.session_ref,
                source_thread_ref=source_thread_ref,
                target_thread_ref=target_thread_ref,
                source_task_ref=task.task_ref,
                target_role=_text(payload.get("target_role"), "target_role"),
                input_evidence_refs=evidence_refs,
                acceptance_contract=acceptance_contract,
                trace_id=trace_id,
                scope={str(key): str(value) for key, value in scope.items()},
                created_at=event.created_at,
            )
            self._handoffs[handoff_ref] = handoff
            self._tasks[task.task_ref] = self._replace_task(
                task,
                handoff_ref=handoff_ref,
                updated_at=event.created_at,
            )
            self._threads[target_thread_ref] = self._replace_thread(
                target_thread,
                handoff_ref=handoff_ref,
                target_role=handoff.target_role,
            )
        else:
            raise OrchestrationError(
                f"event projection type is unsupported: {event.event_type}"
            )

        current_session = self._sessions[event.session_ref]
        self._sessions[event.session_ref] = self._replace_session(
            current_session,
            last_checkpoint_cursor=event.cursor,
            updated_at=max(current_session.updated_at, event.created_at),
        )

    @staticmethod
    def _serialize_session(session: TeamAgentSession) -> dict[str, Any]:
        return {
            "session_ref": session.session_ref,
            "scope": {
                "tenant_ref": session.scope.tenant_ref,
                "entity_ref": session.scope.entity_ref,
                "store_ref": session.scope.store_ref,
            },
            "objective": session.objective,
            "owner_id": session.owner_id,
            "max_parallel": session.max_parallel,
            "max_active_per_agent": session.max_active_per_agent,
            "cost_budget_units": session.cost_budget_units,
            "time_budget_seconds": session.time_budget_seconds,
            "cost_used_units": session.cost_used_units,
            "provider_buckets": _clone(session.provider_buckets),
            "state": session.state.value,
            "kill_switch_engaged": session.kill_switch_engaged,
            "last_checkpoint_cursor": session.last_checkpoint_cursor,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "authority_sha256": session.authority_sha256,
        }

    @staticmethod
    def _deserialize_session(value: Mapping[str, Any]) -> TeamAgentSession:
        scope = value["scope"]
        return TeamAgentSession(
            session_ref=_text(value["session_ref"], "session_ref"),
            scope=ExactScope(
                scope["tenant_ref"],
                scope["entity_ref"],
                scope["store_ref"],
            ),
            objective=_text(value["objective"], "objective", 2000),
            owner_id=_text(value["owner_id"], "owner_id"),
            max_parallel=int(value["max_parallel"]),
            max_active_per_agent=int(value.get("max_active_per_agent", 1)),
            cost_budget_units=value.get("cost_budget_units"),
            time_budget_seconds=value.get("time_budget_seconds"),
            cost_used_units=int(value.get("cost_used_units", 0)),
            provider_buckets={str(key): int(val) for key, val in dict(value.get("provider_buckets", {})).items()},
            state=SessionState(value.get("state", SessionState.ACTIVE)),
            kill_switch_engaged=bool(value.get("kill_switch_engaged", False)),
            last_checkpoint_cursor=value.get("last_checkpoint_cursor"),
            created_at=_utc(value.get("created_at")),
            updated_at=_utc(value.get("updated_at")),
            authority_sha256=value.get("authority_sha256"),
        )

    @staticmethod
    def _serialize_thread(thread: TeamAgentThread) -> dict[str, Any]:
        return {
            "thread_ref": thread.thread_ref,
            "session_ref": thread.session_ref,
            "title": thread.title,
            "parent_thread_ref": thread.parent_thread_ref,
            "state": thread.state.value,
            "parent_task_ref": thread.parent_task_ref,
            "handoff_ref": thread.handoff_ref,
            "target_role": thread.target_role,
            "created_at": thread.created_at.isoformat(),
        }

    @staticmethod
    def _deserialize_thread(value: Mapping[str, Any]) -> TeamAgentThread:
        return TeamAgentThread(
            thread_ref=_text(value["thread_ref"], "thread_ref"),
            session_ref=_text(value["session_ref"], "session_ref"),
            title=_text(value["title"], "title"),
            parent_thread_ref=value.get("parent_thread_ref"),
            state=ThreadState(value.get("state", ThreadState.OPEN)),
            parent_task_ref=value.get("parent_task_ref"),
            handoff_ref=value.get("handoff_ref"),
            target_role=value.get("target_role"),
            created_at=_utc(value.get("created_at")),
        )

    @staticmethod
    def _serialize_task(task: TeamAgentTask) -> dict[str, Any]:
        return {
            "task_ref": task.task_ref,
            "session_ref": task.session_ref,
            "thread_ref": task.thread_ref,
            "agent_id": task.agent_id,
            "role": task.role,
            "objective": task.objective,
            "dependencies": list(task.dependencies),
            "idempotency_key": task.idempotency_key,
            "state": task.state.value,
            "claimed_by": task.claimed_by,
            "reviewer_id": task.reviewer_id,
            "lease_ref": task.lease_ref,
            "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
            "attempt_count": task.attempt_count,
            "max_attempts": task.max_attempts,
            "retry_wait_until": task.retry_wait_until.isoformat() if task.retry_wait_until else None,
            "retry_after_seconds": task.retry_after_seconds,
            "result": _clone(task.result) if task.result is not None else None,
            "evidence_refs": list(task.evidence_refs),
            "failure_code": task.failure_code,
            "failure_kind": task.failure_kind,
            "blocked_reason": task.blocked_reason,
            "trace_id": task.trace_id,
            "provider_id": task.provider_id,
            "parent_task_ref": task.parent_task_ref,
            "handoff_ref": task.handoff_ref,
            "requires_evidence": task.requires_evidence,
            "acceptance_contract": (
                _clone(task.acceptance_contract)
                if task.acceptance_contract is not None
                else None
            ),
            "reviewer_role": task.reviewer_role,
            "cost_budget_units": task.cost_budget_units,
            "cost_used_units": task.cost_used_units,
            "time_budget_seconds": task.time_budget_seconds,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "expired_at": task.expired_at.isoformat() if task.expired_at else None,
            "created_at": task.created_at.isoformat(),
            "updated_at": task.updated_at.isoformat(),
        }

    @staticmethod
    def _deserialize_task(value: Mapping[str, Any]) -> TeamAgentTask:
        return TeamAgentTask(
            task_ref=_text(value["task_ref"], "task_ref"),
            session_ref=_text(value["session_ref"], "session_ref"),
            thread_ref=_text(value["thread_ref"], "thread_ref"),
            agent_id=_text(value["agent_id"], "agent_id"),
            role=_text(value["role"], "role"),
            objective=_text(value["objective"], "objective", 2000),
            dependencies=tuple(value.get("dependencies", ())),
            idempotency_key=_text(value["idempotency_key"], "idempotency_key", 300),
            state=TaskState(value.get("state", TaskState.QUEUED)),
            claimed_by=value.get("claimed_by"),
            reviewer_id=value.get("reviewer_id"),
            lease_ref=value.get("lease_ref"),
            lease_expires_at=_utc(value.get("lease_expires_at")) if value.get("lease_expires_at") else None,
            attempt_count=int(value.get("attempt_count", 0)),
            max_attempts=int(value.get("max_attempts", MAX_TASK_ATTEMPTS)),
            retry_wait_until=_utc(value.get("retry_wait_until")) if value.get("retry_wait_until") else None,
            retry_after_seconds=value.get("retry_after_seconds"),
            result=(
                _normalize_result(value["result"])
                if value.get("result") is not None
                else None
            ),
            evidence_refs=tuple(value.get("evidence_refs", ())),
            failure_code=value.get("failure_code"),
            failure_kind=value.get("failure_kind"),
            blocked_reason=value.get("blocked_reason"),
            trace_id=value.get("trace_id"),
            provider_id=value.get("provider_id"),
            parent_task_ref=value.get("parent_task_ref"),
            handoff_ref=value.get("handoff_ref"),
            requires_evidence=bool(value.get("requires_evidence", False)),
            acceptance_contract=(
                _normalize_result(value["acceptance_contract"])
                if value.get("acceptance_contract") is not None
                else None
            ),
            reviewer_role=value.get("reviewer_role"),
            cost_budget_units=value.get("cost_budget_units"),
            cost_used_units=int(value.get("cost_used_units", 0)),
            time_budget_seconds=value.get("time_budget_seconds"),
            started_at=(
                _utc(value.get("started_at")) if value.get("started_at") else None
            ),
            completed_at=_utc(value.get("completed_at")) if value.get("completed_at") else None,
            expired_at=_utc(value.get("expired_at")) if value.get("expired_at") else None,
            created_at=_utc(value.get("created_at")),
            updated_at=_utc(value.get("updated_at")),
        )

    @staticmethod
    def _serialize_observation(observation: TeamAgentObservation) -> dict[str, Any]:
        return {
            "observation_ref": observation.observation_ref,
            "session_ref": observation.session_ref,
            "task_ref": observation.task_ref,
            "kind": observation.kind,
            "payload_sha256": observation.payload_sha256,
            "evidence_refs": list(observation.evidence_refs),
            "recorded_at": observation.recorded_at.isoformat(),
        }

    @staticmethod
    def _deserialize_observation(value: Mapping[str, Any]) -> TeamAgentObservation:
        return TeamAgentObservation(
            observation_ref=_text(value["observation_ref"], "observation_ref"),
            session_ref=_text(value["session_ref"], "session_ref"),
            task_ref=_text(value["task_ref"], "task_ref"),
            kind=_text(value["kind"], "kind"),
            payload_sha256=_text(value["payload_sha256"], "payload_sha256", 64),
            evidence_refs=tuple(value.get("evidence_refs", ())),
            recorded_at=_utc(value.get("recorded_at")),
        )

    @staticmethod
    def _serialize_lease(lease: TaskLease) -> dict[str, Any]:
        return {
            "lease_ref": lease.lease_ref,
            "task_ref": lease.task_ref,
            "session_ref": lease.session_ref,
            "thread_ref": lease.thread_ref,
            "worker_id": lease.worker_id,
            "claimed_at": lease.claimed_at.isoformat(),
            "heartbeat_at": lease.heartbeat_at.isoformat(),
            "expires_at": lease.expires_at.isoformat(),
            "attempt_count": lease.attempt_count,
            "provider_id": lease.provider_id,
            "trace_id": lease.trace_id,
            "released_at": lease.released_at.isoformat() if lease.released_at else None,
            "released_reason": lease.released_reason,
            "state": lease.state,
        }

    @staticmethod
    def _deserialize_lease(value: Mapping[str, Any]) -> TaskLease:
        return TaskLease(
            lease_ref=_text(value["lease_ref"], "lease_ref"),
            task_ref=_text(value["task_ref"], "task_ref"),
            session_ref=_text(value["session_ref"], "session_ref"),
            thread_ref=_text(value["thread_ref"], "thread_ref"),
            worker_id=_text(value["worker_id"], "worker_id"),
            claimed_at=_utc(value.get("claimed_at")),
            heartbeat_at=_utc(value.get("heartbeat_at")),
            expires_at=_utc(value.get("expires_at")),
            attempt_count=int(value.get("attempt_count", 0)),
            provider_id=value.get("provider_id"),
            trace_id=value.get("trace_id"),
            released_at=_utc(value.get("released_at")) if value.get("released_at") else None,
            released_reason=value.get("released_reason"),
            state=value.get("state", "active"),
        )

    @staticmethod
    def _serialize_event(event: ControlEvent) -> dict[str, Any]:
        return {
            "event_ref": event.event_ref,
            "session_ref": event.session_ref,
            "sequence": event.sequence,
            "cursor": event.cursor,
            "previous_cursor": event.previous_cursor,
            "previous_hash": event.previous_hash,
            "event_type": event.event_type,
            "payload": _clone(event.payload),
            "payload_sha256": event.payload_sha256,
            "contract_id": event.contract_id,
            "contract_version": event.contract_version,
            "created_at": event.created_at.isoformat(),
            "scope": _clone(event.scope),
            "event_hash": event.event_hash,
        }

    @staticmethod
    def _deserialize_event(value: Mapping[str, Any] | ControlEvent) -> ControlEvent:
        if isinstance(value, ControlEvent):
            # ``ControlEvent`` is frozen, but its payload and scope mappings
            # are not.  Never retain caller-owned nested values in the
            # canonical event chain.
            return ControlEvent(
                event_ref=value.event_ref,
                session_ref=value.session_ref,
                sequence=value.sequence,
                cursor=value.cursor,
                previous_cursor=value.previous_cursor,
                previous_hash=value.previous_hash,
                event_type=value.event_type,
                payload=_clone(value.payload),
                payload_sha256=value.payload_sha256,
                contract_id=value.contract_id,
                contract_version=value.contract_version,
                created_at=value.created_at,
                scope=_clone(value.scope),
            )
        if "contract_id" not in value or "contract_version" not in value:
            raise OrchestrationError("event contract drift")
        event = ControlEvent(
            event_ref=_text(value["event_ref"], "event_ref"),
            session_ref=_text(value["session_ref"], "session_ref"),
            sequence=int(value["sequence"]),
            cursor=_text(value["cursor"], "cursor"),
            previous_cursor=value.get("previous_cursor"),
            previous_hash=_text(value["previous_hash"], "previous_hash", 64),
            event_type=_text(value["event_type"], "event_type", 80),
            payload=_clone(value.get("payload", {})),
            payload_sha256=_text(value["payload_sha256"], "payload_sha256", 64),
            contract_id=_text(value.get("contract_id"), "contract_id"),
            contract_version=_text(value.get("contract_version"), "contract_version"),
            created_at=_utc(value.get("created_at")),
            scope={
                str(key): str(item)
                for key, item in dict(value.get("scope", {})).items()
            },
        )
        supplied_hash = value.get("event_hash")
        if supplied_hash is not None and supplied_hash != event.event_hash:
            raise OrchestrationError("event hash conflict")
        return event

    @staticmethod
    def _serialize_handoff(handoff: TaskHandoff) -> dict[str, Any]:
        return {
            "handoff_ref": handoff.handoff_ref,
            "session_ref": handoff.session_ref,
            "source_thread_ref": handoff.source_thread_ref,
            "target_thread_ref": handoff.target_thread_ref,
            "source_task_ref": handoff.source_task_ref,
            "target_role": handoff.target_role,
            "input_evidence_refs": list(handoff.input_evidence_refs),
            "acceptance_contract": _clone(handoff.acceptance_contract),
            "trace_id": handoff.trace_id,
            "scope": _clone(handoff.scope),
            "created_at": handoff.created_at.isoformat(),
        }

    @staticmethod
    def _deserialize_handoff(value: Mapping[str, Any]) -> TaskHandoff:
        return TaskHandoff(
            handoff_ref=_text(value["handoff_ref"], "handoff_ref"),
            session_ref=_text(value["session_ref"], "session_ref"),
            source_thread_ref=_text(value["source_thread_ref"], "source_thread_ref"),
            target_thread_ref=_text(value["target_thread_ref"], "target_thread_ref"),
            source_task_ref=_text(value["source_task_ref"], "source_task_ref"),
            target_role=_text(value["target_role"], "target_role"),
            input_evidence_refs=tuple(value.get("input_evidence_refs", ())),
            acceptance_contract=_normalize_result(
                value.get("acceptance_contract", {})
            ),
            trace_id=_text(value["trace_id"], "trace_id"),
            scope={str(key): str(val) for key, val in dict(value.get("scope", {})).items()},
            created_at=_utc(value.get("created_at")),
        )

    @staticmethod
    def _idempotency_slot(session_ref: str, idempotency_key: str) -> str:
        """Namespace caller idempotency keys without exposing another interface."""

        return f"{_text(session_ref, 'session_ref')}\x1f{_text(idempotency_key, 'idempotency_key', 300)}"

    @staticmethod
    def _cursor_rank(cursor: str) -> tuple[str, int]:
        session_ref, sequence = cursor.rsplit(":", 1)
        return session_ref, int(sequence)

    @staticmethod
    def _min_dt(current: datetime | None, candidate: datetime | None) -> datetime | None:
        if candidate is None:
            return current
        if current is None or candidate < current:
            return candidate
        return current

    @staticmethod
    def _task_waves(tasks: Sequence[TeamAgentTask]) -> list[dict[str, Any]]:
        """Compile dependency barriers into deterministic parallel execution waves."""

        task_by_ref = {task.task_ref: task for task in tasks}
        depths: dict[str, int] = {}
        visiting: set[str] = set()

        def depth(task_ref: str) -> int:
            if task_ref in depths:
                return depths[task_ref]
            if task_ref in visiting:
                raise OrchestrationError("task dependency cycle detected")
            task = task_by_ref.get(task_ref)
            if task is None:
                raise OrchestrationError("task dependency does not exist")
            visiting.add(task_ref)
            dependency_depths = [depth(item) for item in task.dependencies]
            visiting.remove(task_ref)
            value = 0 if not dependency_depths else max(dependency_depths) + 1
            depths[task_ref] = value
            return value

        for task_ref in sorted(task_by_ref):
            depth(task_ref)
        grouped: dict[int, list[str]] = {}
        for task_ref, wave in depths.items():
            grouped.setdefault(wave, []).append(task_ref)
        return [
            {
                "wave": wave,
                "task_refs": sorted(grouped[wave]),
                "task_count": len(grouped[wave]),
            }
            for wave in sorted(grouped)
        ]

    def _validate_event(self, event: ControlEvent) -> None:
        if event.contract_id != CONTRACT_ID or event.contract_version != CONTRACT_VERSION:
            raise OrchestrationError("event contract drift")
        if event.sequence < 1:
            raise OrchestrationError("event sequence is invalid")
        expected_cursor = f"{event.session_ref}:{event.sequence:020d}"
        if event.cursor != expected_cursor:
            raise OrchestrationError("event cursor mismatch")
        if event.event_ref != f"evt-{event.session_ref}-{event.sequence}":
            raise OrchestrationError("event reference mismatch")
        if not _is_lower_hex_sha256(event.previous_hash):
            raise OrchestrationError("event previous hash is invalid")
        if not _is_lower_hex_sha256(event.payload_sha256):
            raise OrchestrationError("event payload hash is invalid")
        if _hash(event.payload) != event.payload_sha256:
            raise OrchestrationError("event payload hash mismatch")
        required_scope = {"tenant_ref", "entity_ref", "store_ref"}
        if set(event.scope) != required_scope:
            raise OrchestrationError("event scope is not exact")
        session = self._sessions.get(event.session_ref)
        if session is not None:
            expected_scope = {
                "tenant_ref": session.scope.tenant_ref,
                "entity_ref": session.scope.entity_ref,
                "store_ref": session.scope.store_ref,
            }
            if event.scope != expected_scope:
                raise OrchestrationError("event scope conflict")
        if event.sequence == 1:
            if event.previous_cursor is not None or event.previous_hash != "0" * 64:
                raise OrchestrationError("event genesis chain conflict")
        else:
            expected_previous_cursor = f"{event.session_ref}:{event.sequence - 1:020d}"
            if event.previous_cursor != expected_previous_cursor:
                raise OrchestrationError("event cursor chain conflict")

    def _validate_event_chains(self) -> None:
        by_session: dict[str, list[ControlEvent]] = {}
        for event in self._events:
            self._validate_event(event)
            by_session.setdefault(event.session_ref, []).append(event)
        for session_ref, events in by_session.items():
            previous: ControlEvent | None = None
            for event in sorted(events, key=lambda item: item.sequence):
                if previous is None:
                    if event.sequence != 1:
                        raise OrchestrationError("event sequence gap")
                else:
                    if event.sequence != previous.sequence + 1:
                        raise OrchestrationError("event sequence gap")
                    if event.previous_cursor != previous.cursor:
                        raise OrchestrationError("event cursor chain conflict")
                    if event.previous_hash != previous.event_hash:
                        raise OrchestrationError("event hash chain conflict")
                    if event.created_at < previous.created_at:
                        raise OrchestrationError("event created_at regression")
                if event.session_ref != session_ref:
                    raise OrchestrationError("event session chain conflict")
                previous = event

    def _validate_restored_state(self) -> None:
        task_slots: set[str] = set()
        submission_events: dict[str, ControlEvent] = {}
        for event in self._events:
            if event.event_type != "task.submitted":
                continue
            if not isinstance(event.payload, Mapping):
                raise OrchestrationError("checkpoint task submission is invalid")
            submitted_task_ref = event.payload.get("task_ref")
            if not isinstance(submitted_task_ref, str) or not submitted_task_ref:
                raise OrchestrationError("checkpoint task submission is invalid")
            if submitted_task_ref in submission_events:
                raise OrchestrationError("checkpoint task submission conflict")
            submission_events[submitted_task_ref] = event
        for thread in self._threads.values():
            session = self._sessions.get(thread.session_ref)
            if session is None:
                raise OrchestrationError("checkpoint thread session is missing")
            if thread.parent_thread_ref is not None:
                parent = self._threads.get(thread.parent_thread_ref)
                if parent is None or parent.session_ref != thread.session_ref:
                    raise OrchestrationError("checkpoint parent thread scope conflict")
        active_lease_by_task: dict[str, TaskLease] = {}
        for lease in self._leases.values():
            task = self._tasks.get(lease.task_ref)
            if (
                task is None
                or task.session_ref != lease.session_ref
                or task.thread_ref != lease.thread_ref
            ):
                raise OrchestrationError("checkpoint lease scope conflict")
            if lease.state == "active":
                if lease.task_ref in active_lease_by_task:
                    raise OrchestrationError("checkpoint has duplicate active leases")
                active_lease_by_task[lease.task_ref] = lease
        for task in self._tasks.values():
            session = self._sessions.get(task.session_ref)
            thread = self._threads.get(task.thread_ref)
            if session is None or thread is None or thread.session_ref != task.session_ref:
                raise OrchestrationError("checkpoint task scope conflict")
            for dependency_ref in task.dependencies:
                dependency = self._tasks.get(dependency_ref)
                if dependency is None or dependency.session_ref != task.session_ref:
                    raise OrchestrationError("checkpoint dependency scope conflict")
            if task.parent_task_ref is not None:
                parent_task = self._tasks.get(task.parent_task_ref)
                if parent_task is None or parent_task.session_ref != task.session_ref:
                    raise OrchestrationError("checkpoint parent task scope conflict")
            if task.handoff_ref is not None:
                task_handoff = self._handoffs.get(task.handoff_ref)
                if (
                    task_handoff is None
                    or task_handoff.session_ref != task.session_ref
                ):
                    raise OrchestrationError("checkpoint task handoff scope conflict")
                if task.task_ref != task_handoff.source_task_ref:
                    if task.thread_ref != task_handoff.target_thread_ref:
                        raise OrchestrationError(
                            "checkpoint handoff target thread conflict"
                        )
                    if task.role != task_handoff.target_role:
                        raise OrchestrationError(
                            "checkpoint handoff target role conflict"
                        )
                    if task.parent_task_ref != task_handoff.source_task_ref:
                        raise OrchestrationError(
                            "checkpoint handoff parent task conflict"
                        )
                    if task.acceptance_contract != task_handoff.acceptance_contract:
                        raise OrchestrationError(
                            "checkpoint handoff acceptance contract conflict"
                        )
                    if not set(task_handoff.input_evidence_refs) <= set(
                        task.evidence_refs
                    ):
                        raise OrchestrationError(
                            "checkpoint handoff input Evidence conflict"
                        )
                    if task.trace_id != task_handoff.trace_id:
                        raise OrchestrationError(
                            "checkpoint handoff trace conflict"
                        )
            lease = active_lease_by_task.get(task.task_ref)
            if task.state is TaskState.RUNNING:
                if (
                    lease is None
                    or task.lease_ref != lease.lease_ref
                    or task.claimed_by != lease.worker_id
                    or task.lease_expires_at != lease.expires_at
                ):
                    raise OrchestrationError("checkpoint running task lease conflict")
            elif lease is not None:
                raise OrchestrationError("checkpoint active lease has no running task")
            slot = self._idempotency_slot(task.session_ref, task.idempotency_key)
            if slot in task_slots:
                raise OrchestrationError("checkpoint idempotency key conflict")
            task_slots.add(slot)
            request_hash = self._idempotency.get(slot)
            if not _is_lower_hex_sha256(request_hash):
                raise OrchestrationError("checkpoint idempotency hash is invalid")
            submission = submission_events.get(task.task_ref)
            if submission is None or submission.session_ref != task.session_ref:
                raise OrchestrationError("checkpoint task submission is missing")
            submitted = submission.payload
            stable_projection = {
                "task_ref": task.task_ref,
                "thread_ref": task.thread_ref,
                "agent_id": task.agent_id,
                "role": task.role,
                "objective": task.objective,
                "dependencies": list(task.dependencies),
                "evidence_required": task.requires_evidence,
                "acceptance_contract": task.acceptance_contract,
                "max_attempts": task.max_attempts,
                "parent_task_ref": task.parent_task_ref,
                "reviewer_role": task.reviewer_role,
                "cost_budget_units": task.cost_budget_units,
                "time_budget_seconds": task.time_budget_seconds,
            }
            submitted_projection = {
                key: submitted.get(key)
                for key in stable_projection
            }
            if stable_projection != submitted_projection:
                raise OrchestrationError("checkpoint task submission conflict")
            submitted_evidence = submitted.get("evidence_refs", [])
            if (
                not isinstance(submitted_evidence, list)
                or not set(submitted_evidence) <= set(task.evidence_refs)
            ):
                raise OrchestrationError("checkpoint task Evidence conflict")
            if submission.created_at != task.created_at:
                raise OrchestrationError("checkpoint task creation time conflict")
            submitted_idempotency_key = submitted.get("idempotency_key")
            if submitted_idempotency_key is not None:
                if submitted_idempotency_key != task.idempotency_key:
                    raise OrchestrationError("checkpoint idempotency key conflict")
                reconstructed_request = {
                    "session_ref": task.session_ref,
                    "task_ref": submitted.get("task_ref"),
                    "thread_ref": submitted.get("thread_ref"),
                    "agent_id": submitted.get("agent_id"),
                    "role": submitted.get("role"),
                    "objective": submitted.get("objective"),
                    "dependencies": submitted.get("dependencies"),
                    "evidence_required": bool(submitted.get("evidence_required")),
                    "evidence_refs": submitted.get("evidence_refs"),
                    "acceptance_contract": submitted.get("acceptance_contract"),
                    "max_attempts": submitted.get("max_attempts"),
                    "provider_id": submitted.get("provider_id"),
                    "trace_id": submitted.get("trace_id"),
                    "parent_task_ref": submitted.get("parent_task_ref"),
                    "handoff_ref": submitted.get("handoff_ref"),
                    "reviewer_role": submitted.get("reviewer_role"),
                    "reviewer_agent_id": submitted.get("reviewer_agent_id"),
                    "cost_budget_units": submitted.get("cost_budget_units"),
                    "time_budget_seconds": submitted.get("time_budget_seconds"),
                }
                if _hash(reconstructed_request) != request_hash:
                    raise OrchestrationError("checkpoint idempotency hash conflict")
        for observation in self._observations:
            task = self._tasks.get(observation.task_ref)
            is_control = observation.task_ref == f"{observation.session_ref}:control"
            if observation.session_ref not in self._sessions or (
                not is_control
                and (task is None or task.session_ref != observation.session_ref)
            ):
                raise OrchestrationError("checkpoint observation scope conflict")
        for handoff in self._handoffs.values():
            source_task = self._tasks.get(handoff.source_task_ref)
            source_thread = self._threads.get(handoff.source_thread_ref)
            target_thread = self._threads.get(handoff.target_thread_ref)
            if (
                source_task is None
                or source_task.session_ref != handoff.session_ref
                or source_thread is None
                or source_thread.session_ref != handoff.session_ref
                or target_thread is None
                or target_thread.session_ref != handoff.session_ref
            ):
                raise OrchestrationError("checkpoint handoff scope conflict")
            if target_thread.parent_thread_ref != source_thread.thread_ref:
                raise OrchestrationError("checkpoint handoff lineage conflict")
            if source_task.thread_ref != source_thread.thread_ref:
                raise OrchestrationError("checkpoint handoff source thread conflict")
            if source_task.state is not TaskState.COMPLETED:
                raise OrchestrationError(
                    "checkpoint handoff source task is not completed"
                )
            if not set(handoff.input_evidence_refs) <= set(
                source_task.evidence_refs
            ):
                raise OrchestrationError(
                    "checkpoint handoff source Evidence conflict"
                )
            if source_task.trace_id != handoff.trace_id:
                raise OrchestrationError("checkpoint handoff source trace conflict")
            if (
                source_task.completed_at is None
                or handoff.created_at < source_task.completed_at
            ):
                raise OrchestrationError("checkpoint handoff time conflict")
            if (
                target_thread.handoff_ref != handoff.handoff_ref
                or target_thread.target_role != handoff.target_role
            ):
                raise OrchestrationError(
                    "checkpoint handoff target thread binding conflict"
                )
            session = self._sessions[handoff.session_ref]
            expected_scope = {
                "tenant_ref": session.scope.tenant_ref,
                "entity_ref": session.scope.entity_ref,
                "store_ref": session.scope.store_ref,
                "session_ref": session.session_ref,
            }
            if handoff.scope != expected_scope:
                raise OrchestrationError("checkpoint handoff exact scope conflict")
            if not handoff.input_evidence_refs or not handoff.acceptance_contract:
                raise OrchestrationError("checkpoint handoff contract is incomplete")
        for session_ref, _provider_id in self._circuit_breakers:
            if session_ref not in self._sessions:
                raise OrchestrationError("checkpoint circuit breaker scope conflict")

    @staticmethod
    def _serialize_breaker(value: Mapping[str, Any]) -> dict[str, Any]:
        state = str(value.get("state", CircuitState.CLOSED.value))
        if state not in {item.value for item in CircuitState}:
            raise OrchestrationError("circuit breaker state is invalid")
        open_until = value.get("open_until")
        if isinstance(open_until, datetime):
            open_until = _utc(open_until).isoformat()
        elif open_until is not None:
            open_until = _utc(str(open_until)).isoformat()
        last_failure_at = value.get("last_failure_at")
        if isinstance(last_failure_at, datetime):
            last_failure_at = _utc(last_failure_at).isoformat()
        elif last_failure_at is not None:
            last_failure_at = _utc(str(last_failure_at)).isoformat()
        failure_count = int(value.get("failure_count", 0))
        if failure_count < 0:
            raise OrchestrationError("circuit breaker failure count is invalid")
        probe_in_flight = bool(value.get("probe_in_flight", False))
        if probe_in_flight and state != CircuitState.HALF_OPEN.value:
            raise OrchestrationError("circuit breaker probe state is invalid")
        if state == CircuitState.OPEN.value and open_until is None:
            raise OrchestrationError("open circuit breaker requires a deadline")
        return {
            "state": state,
            "failure_count": failure_count,
            "open_until": open_until,
            "probe_in_flight": probe_in_flight,
            "last_failure_at": last_failure_at,
        }

    @classmethod
    def _deserialize_breaker(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        serialized = cls._serialize_breaker(value)
        return {
            **serialized,
            "open_until": (
                _utc(serialized["open_until"])
                if serialized["open_until"] is not None
                else None
            ),
            "last_failure_at": (
                _utc(serialized["last_failure_at"])
                if serialized["last_failure_at"] is not None
                else None
            ),
        }

    @staticmethod
    def _classify_failure(
        failure_code: str,
        status_code: int | None,
        timeout: bool,
    ) -> str:
        normalized = failure_code.strip().lower().replace(" ", "_")
        if timeout or "timeout" in normalized or "timed_out" in normalized:
            return "timeout"
        if status_code == 429 or "429" in normalized or "rate_limit" in normalized:
            return "rate_limited"
        if (
            status_code is not None
            and 500 <= status_code <= 599
            or any(
                marker in normalized
                for marker in ("5xx", "bad_gateway", "server_error", "unavailable")
            )
        ):
            return "server_error"
        return normalized

    @staticmethod
    def _parse_retry_after(
        retry_after_seconds: float | None,
        retry_after: str | int | float | None,
        *,
        now: datetime,
    ) -> float | None:
        if retry_after_seconds is not None:
            if not math.isfinite(float(retry_after_seconds)) or retry_after_seconds < 0:
                raise OrchestrationError("retry_after_seconds cannot be negative")
            return float(retry_after_seconds)
        if retry_after is None:
            return None
        if isinstance(retry_after, (int, float)):
            if not math.isfinite(float(retry_after)) or retry_after < 0:
                raise OrchestrationError("retry_after cannot be negative")
            return float(retry_after)
        parsed = _text(retry_after, "retry_after")
        try:
            value = float(parsed)
        except ValueError:
            try:
                parsed_date = parsedate_to_datetime(parsed)
            except (TypeError, ValueError) as exc:
                raise OrchestrationError(
                    "retry_after must be seconds or an HTTP date"
                ) from exc
            value = (_utc(parsed_date) - now).total_seconds()
        if value < 0:
            raise OrchestrationError("retry_after cannot be negative")
        return value

    def _backoff_delay(
        self,
        attempt_count: int,
        *,
        jitter_seed: str | None = None,
    ) -> float:
        base = min(
            self._retry_max_seconds,
            self._retry_base_seconds * (2 ** max(0, attempt_count - 1)),
        )
        jitter = 0.0
        if self._jitter_fn is not None:
            try:
                jitter = float(self._jitter_fn(base, attempt_count))
            except TypeError:
                jitter = float(self._jitter_fn(base))
        elif jitter_seed is not None and base > 0:
            jitter = int(hashlib.sha256(jitter_seed.encode()).hexdigest(), 16) % max(
                1, int(base)
            )
        if not math.isfinite(jitter):
            raise OrchestrationError("retry jitter must be finite")
        return max(0.0, min(self._retry_max_seconds, base + jitter))

    def _touch_circuit_breaker(
        self,
        session_ref: str,
        provider_id: str | None,
        *,
        failed: bool,
        at: datetime,
    ) -> None:
        if provider_id is None:
            return
        key = (session_ref, provider_id)
        breaker = self._circuit_breakers.get(
            key,
            {
                "state": "closed",
                "failure_count": 0,
                "open_until": None,
                "probe_in_flight": False,
                "last_failure_at": None,
            },
        )
        if failed:
            breaker["failure_count"] = int(breaker["failure_count"]) + 1
            breaker["last_failure_at"] = at.isoformat()
            if (
                breaker.get("state") == "half_open"
                or breaker["failure_count"] >= self._breaker_failure_threshold
            ):
                breaker["state"] = "open"
                breaker["open_until"] = at + timedelta(
                    seconds=self._breaker_cooldown_seconds
                )
                breaker["probe_in_flight"] = False
        else:
            state = breaker.get("state", CircuitState.CLOSED.value)
            if state == CircuitState.OPEN.value:
                self._circuit_breakers[key] = breaker
                return
            if (
                state == CircuitState.HALF_OPEN.value
                and not breaker.get("probe_in_flight", False)
            ):
                self._circuit_breakers[key] = breaker
                return
            breaker = {
                "state": CircuitState.CLOSED.value,
                "failure_count": 0,
                "open_until": None,
                "probe_in_flight": False,
                "last_failure_at": None,
            }
        self._circuit_breakers[key] = breaker

    def _release_breaker_probe(
        self,
        session_ref: str,
        provider_id: str | None,
    ) -> None:
        if provider_id is None:
            return
        breaker = self._circuit_breakers.get((session_ref, provider_id))
        if breaker is not None and breaker.get("state") == "half_open":
            breaker["probe_in_flight"] = False

    def _circuit_breaker(self, session_ref: str, provider_id: str) -> dict[str, Any]:
        key = (session_ref, provider_id)
        breaker = self._circuit_breakers.get(
            key,
            {
                "state": "closed",
                "failure_count": 0,
                "open_until": None,
                "probe_in_flight": False,
                "last_failure_at": None,
            },
        )
        open_until = breaker.get("open_until")
        if isinstance(open_until, str):
            breaker["open_until"] = _utc(open_until)
        self._circuit_breakers[key] = breaker
        return breaker

    def _read_circuit_breaker(
        self,
        session_ref: str,
        provider_id: str,
    ) -> dict[str, Any]:
        breaker = self._circuit_breakers.get((session_ref, provider_id))
        if breaker is None:
            return {
                "state": CircuitState.CLOSED.value,
                "failure_count": 0,
                "open_until": None,
                "probe_in_flight": False,
                "last_failure_at": None,
            }
        return breaker

    def _assert_provider_bucket(self, session: TeamAgentSession, provider_id: str) -> None:
        limit = session.provider_buckets.get(provider_id)
        if limit is None:
            return
        if self._provider_running_count(session.session_ref, provider_id) >= limit:
            raise OrchestrationError("provider bucket budget exhausted")

    def _session_running_count(self, session_ref: str) -> int:
        return sum(
            1
            for candidate in self._tasks.values()
            if candidate.session_ref == session_ref and candidate.state is TaskState.RUNNING
        )

    def _agent_running_count(self, session_ref: str, agent_id: str) -> int:
        return sum(
            1
            for candidate in self._tasks.values()
            if candidate.session_ref == session_ref
            and candidate.agent_id == agent_id
            and candidate.state is TaskState.RUNNING
        )

    def _provider_running_count(self, session_ref: str, provider_id: str) -> int:
        return sum(
            1
            for candidate in self._tasks.values()
            if candidate.session_ref == session_ref
            and candidate.provider_id == provider_id
            and candidate.state is TaskState.RUNNING
        )

    def _task_time_budget_deadline(
        self,
        task: TeamAgentTask,
    ) -> datetime | None:
        session = self._session(task.session_ref)
        deadlines: list[datetime] = []
        if session.time_budget_seconds is not None:
            deadlines.append(
                session.created_at
                + timedelta(seconds=session.time_budget_seconds)
            )
        if task.time_budget_seconds is not None and task.started_at is not None:
            deadlines.append(
                task.started_at
                + timedelta(seconds=task.time_budget_seconds)
            )
        return min(deadlines) if deadlines else None

    def _block_unleased_task(
        self,
        task: TeamAgentTask,
        *,
        reason: str,
        as_of: datetime,
    ) -> TeamAgentTask:
        """Record a queued terminal budget decision as replayable state."""

        normalized_reason = _text(reason, "blocked_reason", 120)
        if task.lease_ref is not None:
            raise OrchestrationError("unleased budget transition has an active lease")
        blocked = self._replace_task(
            task,
            state=TaskState.BLOCKED,
            blocked_reason=normalized_reason,
            retry_wait_until=None,
            retry_after_seconds=None,
            updated_at=as_of,
        )
        self._tasks[task.task_ref] = blocked
        self._record_event(
            session_ref=task.session_ref,
            event_type="task.time_budget_exhausted",
            payload={
                "task_ref": task.task_ref,
                "attempt_count": task.attempt_count,
                "max_attempts": task.max_attempts,
                "blocked_reason": normalized_reason,
            },
            created_at=as_of,
        )
        self._observations.append(
            self._observation(
                blocked,
                "task.blocked",
                {"blocked_reason": normalized_reason},
                blocked.evidence_refs,
                as_of,
            )
        )
        return blocked

    @staticmethod
    def _observation(
        task: TeamAgentTask,
        kind: str,
        payload: Mapping[str, Any],
        evidence_refs: tuple[str, ...],
        recorded_at: datetime,
    ) -> TeamAgentObservation:
        return TeamAgentObservation(
            observation_ref=f"obs-{task.task_ref}-{kind}",
            session_ref=task.session_ref,
            task_ref=task.task_ref,
            kind=kind,
            payload_sha256=_hash(payload),
            evidence_refs=evidence_refs,
            recorded_at=recorded_at,
        )

    def _next_control_observation_ref(self, session_ref: str) -> str:
        sequence = (
            sum(
                observation.session_ref == session_ref
                and observation.task_ref == f"{session_ref}:control"
                for observation in self._observations
            )
            + 1
        )
        return f"obs-{session_ref}-control-{sequence}"

    def _task_to_dict(self, task: TeamAgentTask) -> dict[str, Any]:
        return self._serialize_task(task)

    def _observation_payload(self, result: Mapping[str, Any]) -> dict[str, Any]:
        return _normalize_result(result)

    def _hydrate_task(self, task: TeamAgentTask) -> None:
        self._tasks[task.task_ref] = task

    def _hydrate_session(self, session: TeamAgentSession) -> None:
        self._sessions[session.session_ref] = session


class TeamAgentObservationSink(Protocol):
    def record_observation(self, payload: dict[str, Any], *, principal: Any) -> dict[str, Any]: ...


class TeamAgentHarnessBridge:
    """Project terminal task outcomes into the existing Harness observation contract."""

    def __init__(
        self,
        *,
        coordinator: TeamAgentCoordinator,
        sink: TeamAgentObservationSink,
    ) -> None:
        self.coordinator = coordinator
        self.sink = sink
        self._published: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

    def publish_completed(
        self,
        *,
        session_ref: str,
        project_id: str,
        verifier_id: str,
        verifier_version: str,
        principal: Any,
        scope: ExactScope | None = None,
        authority_sha256: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        coordinator = self.coordinator
        if getattr(coordinator, "requires_durable_scope", False) and (
            scope is None or authority_sha256 is None
        ):
            raise OrchestrationError(
                "durable TeamAgent publication requires exact scope and authority"
            )
        if scope is not None or authority_sha256 is not None:
            if scope is None or authority_sha256 is None or not hasattr(
                coordinator, "restore_session"
            ):
                raise OrchestrationError(
                    "scoped TeamAgent publication requires durable session restore"
                )
            coordinator = coordinator.restore_session(
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
            )
        session = coordinator.session(session_ref)
        project_id = _text(project_id, "project_id")
        verifier_id = _text(verifier_id, "verifier_id")
        verifier_version = _text(verifier_version, "verifier_version")
        if (
            verifier_id != TEAM_AGENT_HARNESS_VERIFIER_ID
            or verifier_version != TEAM_AGENT_HARNESS_VERIFIER_VERSION
        ):
            raise OrchestrationError(
                "TeamAgent outcomes require the fixed observation-only verifier"
            )
        results: list[dict[str, Any]] = []
        with self._lock:
            observations = coordinator.observations(session_ref=session_ref)
            for observation in observations:
                terminal_states = {
                    "task.completed": "passed",
                    "task.failed": "failed",
                    "task.blocked": "blocked",
                }
                if observation.kind not in terminal_states:
                    continue
                cache_key = (
                    session_ref,
                    observation.observation_ref,
                    project_id,
                    self._scope_cache_fingerprint(session),
                    self._principal_cache_fingerprint(principal),
                )
                task = coordinator.task(observation.task_ref)
                state = terminal_states[observation.kind]
                input_sha256 = _hash(
                    {
                        "session_ref": session_ref,
                        "task_ref": task.task_ref,
                        "payload_sha256": observation.payload_sha256,
                    }
                )
                artifact_ref = (
                    f"team-agent://{session_ref}/{task.task_ref}/{observation.observation_ref}"
                )
                payload = {
                    "project_id": project_id,
                    "verifier_id": TEAM_AGENT_HARNESS_VERIFIER_ID,
                    "verifier_version": TEAM_AGENT_HARNESS_VERIFIER_VERSION,
                    "source": TEAM_AGENT_HARNESS_SOURCE,
                    "source_type": TEAM_AGENT_HARNESS_VERIFIER_SOURCE_TYPE,
                    "authority": TEAM_AGENT_HARNESS_VERIFIER_AUTHORITY,
                    "store_ref": session.scope.store_ref,
                    "state": state,
                    "summary": (
                        f"TeamAgent {task.role} terminal outcome: {state}; "
                        f"kind={observation.kind}; task={task.task_ref}"
                    ),
                    "input_sha256": input_sha256,
                    "artifact_ref": artifact_ref,
                    "evidence_ref": observation.evidence_refs[0]
                    if observation.evidence_refs
                    else None,
                    "observed_at": observation.recorded_at.isoformat(),
                    "scope": {
                        "tenant_ref": session.scope.tenant_ref,
                        "entity_ref": session.scope.entity_ref,
                        "store_ref": session.scope.store_ref,
                        "authority_sha256": session.authority_sha256,
                        "session_ref": session_ref,
                        "task_ref": task.task_ref,
                        "observation_only": True,
                        "gate_eligible": False,
                    },
                }
                recorded = self.sink.record_observation(payload, principal=principal)
                result = {
                    "observation_ref": observation.observation_ref,
                    "harness_observation": recorded,
                    "external_write_allowed": False,
                }
                cached = self._published.get(cache_key)
                if cached is not None:
                    # The sink owns current project/verifier/principal
                    # authorization and durable idempotency.  Never let an
                    # in-process cache bypass that authorization on replay;
                    # revalidate through the sink and fail closed if its
                    # canonical readback no longer matches the first result.
                    if cached != result:
                        raise OrchestrationError(
                            "Harness publication replay result conflict"
                        )
                    results.append(_clone(cached))
                    continue
                self._published[cache_key] = _clone(result)
                results.append(_clone(result))
        return tuple(results)

    @staticmethod
    def _scope_cache_fingerprint(session: TeamAgentSession) -> str:
        return _hash(
            {
                "tenant_ref": session.scope.tenant_ref,
                "entity_ref": session.scope.entity_ref,
                "store_ref": session.scope.store_ref,
                "authority_sha256": session.authority_sha256,
            }
        )

    @staticmethod
    def _principal_cache_fingerprint(principal: Any) -> str:
        actor_id = getattr(principal, "actor_id", None)
        tenant_ref = getattr(principal, "tenant_ref", None)
        roles = getattr(principal, "roles", None)
        store_refs = getattr(principal, "store_refs", None)
        if actor_id is None or tenant_ref is None:
            return _hash(
                {
                    "principal_type": type(principal).__qualname__,
                    "object_identity": id(principal),
                }
            )
        return _hash(
            {
                "actor_id": str(actor_id),
                "tenant_ref": str(tenant_ref),
                "roles": sorted(str(role) for role in (roles or ())),
                "store_refs": sorted(
                    str(store_ref) for store_ref in (store_refs or ())
                ),
            }
        )


__all__ = [
    "CONTRACT_ID",
    "TEAM_AGENT_HARNESS_SOURCE",
    "TEAM_AGENT_HARNESS_VERIFIER_AUTHORITY",
    "TEAM_AGENT_HARNESS_VERIFIER_ID",
    "TEAM_AGENT_HARNESS_VERIFIER_SOURCE_TYPE",
    "TEAM_AGENT_HARNESS_VERIFIER_VERSION",
    "CircuitState",
    "EventMergeResult",
    "OrchestrationError",
    "OrchestrationReplayConflict",
    "SessionState",
    "TaskState",
    "TaskLease",
    "ControlEvent",
    "TaskHandoff",
    "TeamAgentCoordinator",
    "TeamAgentHandoff",
    "TeamAgentHarnessBridge",
    "TeamAgentObservation",
    "TeamAgentObservationSink",
    "TeamAgentSession",
    "TeamAgentTask",
    "TeamAgentThread",
    "ThreadState",
]
