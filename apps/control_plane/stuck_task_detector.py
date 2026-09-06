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
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

STUCK_DETECTOR_VERSION = "kjds-stuck-detector-v2"
RECOVERY_PLAN_VERSION = "kjds-stuck-recovery-v1"

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
_ACTIVE_STATES = frozenset({"running", "retry_wait", "paused"})
_QUEUED_STATE = "queued"

# Recovery is a proposal assembled from immutable observation data.  These
# steps are deliberately descriptive: the detector never claims that a lease
# was reclaimed, a remote state was reconciled, or a compensation command was
# executed.  A separately governed worker must consume the plan and produce
# its own receipt.
_RECOVERY_STEPS: dict[str, tuple[str, ...]] = {
    "unknown_state": (
        "quarantine_task",
        "repair_liveness_observation",
        "recompute_from_fresh_heartbeat",
    ),
    "timestamp_timezone_missing": (
        "quarantine_task",
        "normalize_source_timestamps",
        "recompute_from_fresh_heartbeat",
    ),
    "deadline_conflict": (
        "quarantine_task",
        "resolve_deadline_alias_conflict",
        "recompute_from_fresh_heartbeat",
    ),
    "external_readback_unknown": (
        "freeze_retries",
        "reconcile_external_state",
        "record_authoritative_readback",
        "decide_compensation",
    ),
    "external_readback_failed": (
        "freeze_retries",
        "reconcile_external_state",
        "record_authoritative_readback",
        "decide_compensation",
    ),
    "duplicate_execution_detected": (
        "freeze_retries",
        "deduplicate_by_idempotency",
        "reconcile_execution_receipts",
        "decide_compensation",
    ),
    "idempotency_key_missing": (
        "quarantine_task",
        "bind_idempotency_key",
        "recompute_from_fresh_heartbeat",
    ),
    "lease_expired": (
        "freeze_retries",
        "reclaim_or_expire_lease",
        "read_durable_checkpoint",
        "resume_only_after_fresh_heartbeat",
    ),
    "heartbeat_expired": (
        "freeze_retries",
        "inspect_consumer_and_checkpoint",
        "resume_only_after_fresh_heartbeat",
    ),
    "progress_stalled": (
        "freeze_retries",
        "inspect_consumer_and_checkpoint",
        "resume_only_after_progress_receipt",
    ),
    "progress_cursor_missing": (
        "quarantine_task",
        "request_progress_checkpoint",
        "resume_only_after_progress_receipt",
    ),
    "consumer_missing": (
        "quarantine_task",
        "bind_consumer",
        "resume_only_after_fresh_heartbeat",
    ),
    "queued_without_consumer": (
        "quarantine_task",
        "bind_consumer",
        "resume_only_after_fresh_heartbeat",
    ),
    "deadline_expired": (
        "freeze_retries",
        "quarantine_or_replan",
        "append_recovery_receipt",
    ),
    "terminal_evidence_missing": (
        "quarantine_terminal_result",
        "attach_terminal_evidence",
        "reopen_or_close_after_review",
    ),
}

_RECOVERY_CHECKS: dict[str, tuple[str, ...]] = {
    "unknown_state": ("state_contract_valid", "fresh_heartbeat_recorded"),
    "timestamp_timezone_missing": ("source_timestamps_are_timezone_aware",),
    "deadline_conflict": ("one_authoritative_liveness_deadline",),
    "external_readback_unknown": (
        "external_state_reconciled",
        "retry_decision_is_receipted",
    ),
    "external_readback_failed": (
        "external_state_reconciled",
        "compensation_decision_is_receipted",
    ),
    "duplicate_execution_detected": (
        "idempotency_winner_identified",
        "execution_receipts_reconciled",
    ),
    "idempotency_key_missing": ("idempotency_key_bound",),
    "lease_expired": ("lease_reclaimed_or_expired", "checkpoint_readback_recorded"),
    "heartbeat_expired": ("consumer_health_checked", "fresh_heartbeat_recorded"),
    "progress_stalled": ("checkpoint_readback_recorded", "progress_receipt_recorded"),
    "progress_cursor_missing": ("progress_cursor_recorded",),
    "consumer_missing": ("consumer_binding_recorded",),
    "queued_without_consumer": ("consumer_binding_recorded",),
    "deadline_expired": ("replan_or_terminal_receipt_recorded",),
    "terminal_evidence_missing": ("terminal_evidence_attached", "independent_review_recorded"),
}

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
    recovery_plan: RecoveryPlan | None = None


@dataclass(frozen=True, slots=True)
class RecoveryPlan:
    """A deterministic, proposal-only recovery contract for one stuck task.

    ``retry_allowed`` is intentionally false for every plan emitted by the
    detector.  Recovery workers may only change that decision after they have
    produced the checks listed in ``required_checks`` and a new authoritative
    heartbeat/readback.  ``external_write_allowed`` is permanently false at
    this projection boundary.
    """

    task_ref: str
    observation_sha256: str
    action: str
    required_checks: tuple[str, ...]
    steps: tuple[str, ...]
    retry_allowed: bool
    compensation_required: bool
    action_source: Literal["detector"] = "detector"
    external_write_allowed: bool = False
    plan_sha256: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.task_ref, str) or not self.task_ref.strip():
            raise ValueError("recovery plan task_ref is required")
        if self.observation_sha256 and (
            len(self.observation_sha256) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in self.observation_sha256)
        ):
            raise ValueError("recovery plan observation digest is invalid")
        if not isinstance(self.action, str) or not self.action.strip():
            raise ValueError("recovery plan action is required")
        if self.action_source != "detector":
            raise ValueError("recovery plan action source is invalid")
        if not self.required_checks:
            raise ValueError("recovery plan requires at least one check")
        if not self.steps:
            raise ValueError("recovery plan requires at least one step")
        if self.retry_allowed:
            raise ValueError("stuck recovery plans cannot allow retry before checks")
        if self.external_write_allowed:
            raise ValueError("stuck recovery plans cannot authorize external writes")
        expected = _recovery_plan_hash(
            task_ref=self.task_ref,
            observation_sha256=self.observation_sha256,
            action=self.action,
            required_checks=self.required_checks,
            steps=self.steps,
            retry_allowed=self.retry_allowed,
            compensation_required=self.compensation_required,
        )
        if self.plan_sha256 and self.plan_sha256 != expected:
            raise ValueError("recovery plan digest is invalid")
        object.__setattr__(self, "plan_sha256", expected)


def _recovery_plan_hash(
    *,
    task_ref: str,
    observation_sha256: str,
    action: str,
    required_checks: tuple[str, ...],
    steps: tuple[str, ...],
    retry_allowed: bool,
    compensation_required: bool,
) -> str:
    payload = {
        "contract_id": RECOVERY_PLAN_VERSION,
        "task_ref": task_ref,
        "observation_sha256": observation_sha256,
        "action": action,
        "required_checks": list(required_checks),
        "steps": list(steps),
        "retry_allowed": retry_allowed,
        "compensation_required": compensation_required,
        "external_write_allowed": False,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def build_recovery_plan(stuck: StuckTask) -> RecoveryPlan | None:
    """Build a stable recovery proposal from a detector result.

    The plan is derived from the result's immutable reason tuple and
    observation digest.  It is therefore safe to persist/replay and it never
    treats a caller-supplied compensation string as an executable command.
    """

    if stuck.status != "stuck":
        return None
    reasons = tuple(dict.fromkeys(reason for reason in stuck.reasons if reason in _RECOVERY_STEPS))
    if not reasons:
        reasons = ("unknown_state",)
    # Keep the plan action detector-owned even when the legacy result carries
    # a caller-provided compensation string.  That string remains visible on
    # ``StuckTask.compensation_action`` for diagnostics but cannot become an
    # executable recovery instruction at this boundary.
    action = _canonical_action_for_reasons(reasons)
    # Make the plan's steps deterministic across reason ordering and duplicate
    # observations.
    steps: list[str] = ["capture_immutable_observation"]
    checks: list[str] = []
    for reason in reasons:
        for step in _RECOVERY_STEPS[reason]:
            if step not in steps:
                steps.append(step)
        for check in _RECOVERY_CHECKS.get(reason, ()):
            if check not in checks:
                checks.append(check)
    if "append_recovery_receipt" not in steps:
        steps.append("append_recovery_receipt")
    compensation_required = bool(
        set(reasons)
        & {
            "external_readback_unknown",
            "external_readback_failed",
            "duplicate_execution_detected",
            "lease_expired",
            "deadline_expired",
        }
    )
    plan = RecoveryPlan(
        task_ref=stuck.task_ref,
        observation_sha256=stuck.observation_sha256 or "",
        action=action,
        required_checks=tuple(checks),
        steps=tuple(steps),
        retry_allowed=False,
        compensation_required=compensation_required,
    )
    # Include the observation digest in the action identity when available by
    # requiring callers to retain it next to this plan.  The plan itself stays
    # compact and can be recomputed from the immutable StuckTask fields.
    return plan


def _canonical_action_for_reasons(reasons: tuple[str, ...]) -> str:
    """Select the strongest detector-owned action for a reason set."""

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
        "compensation_action": item.compensation_action,
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
        if state not in _ACTIVE_STATES | _TERMINAL_STATES | {_QUEUED_STATE}:
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
        elif state == _QUEUED_STATE:
            # Queue admission has no heartbeat yet; use the queue deadline and
            # consumer binding instead of falsely treating a pre-dispatch task
            # as heartbeat-expired.
            if deadline is not None and deadline <= current:
                reasons.append("deadline_expired")
            if _is_blank(item.consumer_id):
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
        detected_task = StuckTask(
                task_ref=item.task_ref,
                status="stuck" if stuck else "healthy",
                reasons=deduped,
                recovery_required=stuck,
                compensation_action=action,
                recovery_ref=item.recovery_ref,
                detector_version=STUCK_DETECTOR_VERSION,
                observation_sha256=observation_hash,
            )
        result.append(replace(detected_task, recovery_plan=build_recovery_plan(detected_task)))
    return tuple(result)


__all__ = [
    "RECOVERY_PLAN_VERSION",
    "STUCK_DETECTOR_VERSION",
    "RecoveryPlan",
    "StuckTask",
    "TaskLivenessObservation",
    "build_recovery_plan",
    "detect_stuck_tasks",
]
