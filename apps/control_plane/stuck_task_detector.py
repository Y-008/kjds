"""Liveness checks for unattended TeamAgent tasks.

The detector is deliberately a pure projection.  It never changes a task or
requeues work by itself; instead it emits a deterministic recovery instruction
that a caller can submit through the durable TeamAgent control plane.  Keeping
the observation and the recovery decision separate makes a stuck task
replayable and prevents a watchdog from accidentally executing the same remote
action twice.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

STUCK_DETECTOR_VERSION = "kjds-stuck-detector-v2"

_RECOVERY_ACTIONS: dict[str, str] = {
    "deadline_expired": "quarantine_and_replan",
    "heartbeat_expired": "reclaim_lease_and_recover",
    "lease_expired": "reclaim_lease_and_recover",
    "consumer_missing": "bind_consumer_or_quarantine",
    "queued_without_consumer": "bind_consumer_or_quarantine",
    "progress_cursor_missing": "request_progress_checkpoint",
    "progress_stalled": "reclaim_lease_and_recover",
    "external_readback_unknown": "reconcile_external_state_before_retry",
    "terminal_evidence_missing": "quarantine_until_evidence_attached",
    "duplicate_execution_detected": "deduplicate_by_idempotency_and_reconcile",
    "idempotency_key_missing": "quarantine_until_idempotency_bound",
    "unknown_state": "quarantine_unknown_task_state",
    "timestamp_timezone_missing": "quarantine_invalid_liveness_observation",
    "deadline_conflict": "quarantine_invalid_liveness_observation",
    "external_readback_failed": "reconcile_external_state_before_retry",
}

_TERMINAL_STATES = frozenset({"completed", "failed", "blocked", "expired"})
_ACTIVE_STATES = frozenset({"running", "queued", "retry_wait", "paused"})


@dataclass(frozen=True, slots=True)
class TaskLivenessObservation:
    """The immutable liveness slice used by :func:`detect_stuck_tasks`.

    ``deadline`` is retained for compatibility with the first contract;
    ``liveness_deadline`` is its explicit name in the public data model.  If
    both are supplied they must agree.  All fields after ``consumer_id`` are
    optional so existing TeamAgent adapters can be upgraded incrementally.
    """

    task_ref: str
    state: str
    last_heartbeat: datetime | None
    deadline: datetime | None = None
    progress_cursor: str | None = None
    expected_next_event: str | None = None
    consumer_id: str | None = None
    liveness_deadline: datetime | None = None
    progress_updated_at: datetime | None = None
    lease_expires_at: datetime | None = None
    external_readback_state: Literal["passed", "failed", "unknown", "pending"] | None = None
    external_readback_required: bool = False
    evidence_refs: tuple[str, ...] = ()
    evidence_required: bool = False
    idempotency_key: str | None = None
    duplicate_execution_count: int = 0
    compensation_action: str | None = None
    recovery_ref: str | None = None


@dataclass(frozen=True, slots=True)
class StuckTask:
    task_ref: str
    status: Literal["stuck", "healthy"]
    reasons: tuple[str, ...]
    recovery_required: bool = False
    compensation_action: str | None = None
    recovery_ref: str | None = None
    detector_version: str = STUCK_DETECTOR_VERSION
    observation_sha256: str | None = None


def _utc(value: datetime | None) -> datetime | None:
    """Normalize database timestamps without inheriting the host timezone."""

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _observation_hash(item: TaskLivenessObservation) -> str:
    payload = {
        "task_ref": item.task_ref,
        "state": item.state,
        "last_heartbeat": _utc(item.last_heartbeat).isoformat()
        if _utc(item.last_heartbeat)
        else None,
        "deadline": _utc(item.deadline).isoformat() if _utc(item.deadline) else None,
        "liveness_deadline": (
            _utc(item.liveness_deadline).isoformat()
            if _utc(item.liveness_deadline)
            else None
        ),
        "progress_cursor": item.progress_cursor,
        "progress_updated_at": (
            _utc(item.progress_updated_at).isoformat()
            if _utc(item.progress_updated_at)
            else None
        ),
        "expected_next_event": item.expected_next_event,
        "consumer_id": item.consumer_id,
        "lease_expires_at": (
            _utc(item.lease_expires_at).isoformat()
            if _utc(item.lease_expires_at)
            else None
        ),
        "external_readback_state": item.external_readback_state,
        "external_readback_required": item.external_readback_required,
        "evidence_refs": list(item.evidence_refs),
        "evidence_required": item.evidence_required,
        "idempotency_key": item.idempotency_key,
        "duplicate_execution_count": item.duplicate_execution_count,
        "recovery_ref": item.recovery_ref,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _effective_deadline(item: TaskLivenessObservation) -> datetime | None:
    deadline = _utc(item.liveness_deadline)
    legacy = _utc(item.deadline)
    if deadline is not None and legacy is not None and deadline != legacy:
        # The caller cannot safely decide which deadline is authoritative.
        # Returning ``None`` lets the detector emit an explicit malformed
        # observation reason instead of silently choosing one.
        return None
    return deadline or legacy


def _action_for(item: TaskLivenessObservation, reasons: list[str]) -> str:
    if item.compensation_action and item.compensation_action.strip():
        return item.compensation_action.strip()
    # Keep action selection stable even when a caller supplies reasons in a
    # different order.  The first item in this ordered map is the strongest
    # containment action for that observation.
    for reason in (
        "unknown_state",
        "deadline_conflict",
        "external_readback_unknown",
        "external_readback_failed",
        "duplicate_execution_detected",
        "lease_expired",
        "deadline_expired",
        "heartbeat_expired",
        "progress_stalled",
        "terminal_evidence_missing",
        "consumer_missing",
        "queued_without_consumer",
        "idempotency_key_missing",
        "timestamp_timezone_missing",
    ):
        if reason in reasons:
            return _RECOVERY_ACTIONS[reason]
    return "inspect_and_replan"


def detect_stuck_tasks(
    observations: tuple[TaskLivenessObservation, ...],
    *,
    now: datetime | None = None,
    heartbeat_timeout: timedelta = timedelta(minutes=5),
    progress_timeout: timedelta | None = None,
) -> tuple[StuckTask, ...]:
    """Classify observations and emit a replayable recovery projection.

    The function treats missing or contradictory liveness data as a stuck
    condition.  A task is never marked healthy merely because it has no error
    string: completed work needs terminal evidence, and remote work with an
    unknown readback must be reconciled before any retry.
    """

    if heartbeat_timeout.total_seconds() <= 0:
        raise ValueError("heartbeat_timeout must be positive")
    effective_progress_timeout = progress_timeout or heartbeat_timeout
    if effective_progress_timeout.total_seconds() <= 0:
        raise ValueError("progress_timeout must be positive")
    current = _utc(now or datetime.now(UTC))
    assert current is not None
    result: list[StuckTask] = []
    for item in observations:
        reasons: list[str] = []
        state = item.state.strip().lower() if isinstance(item.state, str) else ""
        if not isinstance(item.task_ref, str) or not item.task_ref.strip():
            reasons.append("unknown_state")
        if state not in _ACTIVE_STATES | _TERMINAL_STATES:
            reasons.append("unknown_state")

        # A naive timestamp is not trusted.  ``_utc`` normalizes it for local
        # replay, but we retain a reason so the operator can repair the source
        # contract instead of mistaking it for a fresh observation.
        timestamp_values = (
            item.last_heartbeat,
            item.deadline,
            item.liveness_deadline,
            item.progress_updated_at,
            item.lease_expires_at,
        )
        if any(value is not None and value.tzinfo is None for value in timestamp_values):
            reasons.append("timestamp_timezone_missing")

        deadline = _effective_deadline(item)
        if item.liveness_deadline is not None and item.deadline is not None and deadline is None:
            reasons.append("deadline_conflict")

        if state in _ACTIVE_STATES:
            if deadline is not None and deadline <= current:
                reasons.append("deadline_expired")
            heartbeat = _utc(item.last_heartbeat)
            if heartbeat is None or heartbeat + heartbeat_timeout <= current:
                reasons.append("heartbeat_expired")
            if _is_blank(item.consumer_id):
                reasons.append("consumer_missing")
            lease_expires = _utc(item.lease_expires_at)
            if lease_expires is not None and lease_expires <= current:
                reasons.append("lease_expired")
            if item.expected_next_event and _is_blank(item.progress_cursor):
                reasons.append("progress_cursor_missing")
            progress_at = _utc(item.progress_updated_at) or heartbeat
            if item.expected_next_event and (
                progress_at is None or progress_at + effective_progress_timeout <= current
            ):
                reasons.append("progress_stalled")
        elif state == "queued" and _is_blank(item.consumer_id):
            reasons.append("queued_without_consumer")

        if item.external_readback_required and item.external_readback_state in {None, "pending", "unknown"}:
            reasons.append("external_readback_unknown")
        if item.external_readback_state == "unknown":
            reasons.append("external_readback_unknown")
        elif item.external_readback_state == "failed":
            reasons.append("external_readback_failed")
        if state == "completed" and item.evidence_required and not tuple(
            ref.strip() for ref in item.evidence_refs if isinstance(ref, str) and ref.strip()
        ):
            reasons.append("terminal_evidence_missing")
        if item.duplicate_execution_count < 0 or item.duplicate_execution_count > 0:
            reasons.append("duplicate_execution_detected")
        if reasons and item.duplicate_execution_count > 0 and _is_blank(item.idempotency_key):
            reasons.append("idempotency_key_missing")

        deduped = tuple(dict.fromkeys(reasons))
        stuck = bool(deduped)
        action = _action_for(item, list(deduped)) if stuck else None
        observation_hash = _observation_hash(item)
        result.append(
            StuckTask(
                task_ref=item.task_ref,
                status="stuck" if stuck else "healthy",
                reasons=deduped,
                recovery_required=stuck,
                compensation_action=action,
                recovery_ref=item.recovery_ref,
                detector_version=STUCK_DETECTOR_VERSION,
                observation_sha256=observation_hash,
            )
        )
    return tuple(result)


__all__ = [
    "STUCK_DETECTOR_VERSION",
    "StuckTask",
    "TaskLivenessObservation",
    "detect_stuck_tasks",
]
