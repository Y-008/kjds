from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.stuck_task_detector import (
    RECOVERY_PLAN_VERSION,
    STUCK_DETECTOR_VERSION,
    TaskLivenessObservation,
    build_recovery_plan,
    detect_stuck_tasks,
)

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


def test_running_task_with_expired_lease_emits_recovery_projection():
    result = detect_stuck_tasks(
        (
            TaskLivenessObservation(
                task_ref="task-1",
                state="running",
                last_heartbeat=NOW - timedelta(minutes=1),
                liveness_deadline=NOW + timedelta(minutes=10),
                lease_expires_at=NOW - timedelta(seconds=1),
                consumer_id="worker-1",
                progress_cursor="page:3",
                expected_next_event="page:4",
                progress_updated_at=NOW - timedelta(minutes=1),
            ),
        ),
        now=NOW,
    )

    item = result[0]
    assert item.status == "stuck"
    assert item.recovery_required is True
    assert "lease_expired" in item.reasons
    assert item.compensation_action == "reclaim_lease_and_recover"
    assert item.detector_version == STUCK_DETECTOR_VERSION
    assert len(item.observation_sha256 or "") == 64


def test_completed_task_without_terminal_evidence_is_not_healthy():
    result = detect_stuck_tasks(
        (
            TaskLivenessObservation(
                task_ref="task-2",
                state="completed",
                last_heartbeat=NOW,
                evidence_required=True,
            ),
        ),
        now=NOW,
    )

    assert result[0].status == "stuck"
    assert result[0].reasons == ("terminal_evidence_missing",)
    assert result[0].compensation_action == "quarantine_until_evidence_attached"


def test_unknown_external_readback_blocks_retry_and_explicit_action_wins():
    result = detect_stuck_tasks(
        (
            TaskLivenessObservation(
                task_ref="task-3",
                state="failed",
                last_heartbeat=NOW,
                external_readback_required=True,
                external_readback_state="unknown",
                compensation_action="open_reconciliation_incident",
            ),
        ),
        now=NOW,
    )

    item = result[0]
    assert item.status == "stuck"
    assert item.reasons == ("external_readback_unknown",)
    assert item.compensation_action == "open_reconciliation_incident"


def test_conflicting_deadline_aliases_fail_closed_and_hash_is_stable():
    observation = TaskLivenessObservation(
        task_ref="task-4",
        state="queued",
        last_heartbeat=NOW,
        deadline=NOW + timedelta(hours=1),
        liveness_deadline=NOW + timedelta(hours=2),
        consumer_id="worker-1",
    )
    first = detect_stuck_tasks((observation,), now=NOW)[0]
    second = detect_stuck_tasks((observation,), now=NOW)[0]

    assert first.status == "stuck"
    assert "deadline_conflict" in first.reasons
    assert first.observation_sha256 == second.observation_sha256


def test_queued_task_does_not_require_pre_dispatch_heartbeat():
    observation = TaskLivenessObservation(
        task_ref="queued-healthy", state="queued", last_heartbeat=None,
        deadline=NOW + timedelta(hours=1), consumer_id="worker-1",
    )
    result = detect_stuck_tasks((observation,), now=NOW)[0]
    assert result.status == "healthy"


def test_invalid_timeout_is_rejected():
    with pytest.raises(ValueError, match="heartbeat_timeout"):
        detect_stuck_tasks((), heartbeat_timeout=timedelta(0))


def test_unknown_remote_outcome_emits_deterministic_proposal_only_recovery_plan():
    observation = TaskLivenessObservation(
        task_ref="remote-write-1",
        state="failed",
        last_heartbeat=NOW,
        external_readback_required=True,
        external_readback_state="unknown",
        duplicate_execution_count=1,
        idempotency_key="write-1",
    )

    first = detect_stuck_tasks((observation,), now=NOW)[0]
    second = detect_stuck_tasks((observation,), now=NOW)[0]
    plan = first.recovery_plan

    assert plan is not None
    assert plan.plan_sha256 == second.recovery_plan.plan_sha256
    assert len(plan.plan_sha256) == 64
    assert plan.action == "reconcile_external_state_before_retry"
    assert plan.retry_allowed is False
    assert plan.external_write_allowed is False
    assert plan.compensation_required is True
    assert "reconcile_external_state" in plan.steps
    assert "record_authoritative_readback" in plan.steps
    assert "external_state_reconciled" in plan.required_checks
    assert RECOVERY_PLAN_VERSION == "kjds-stuck-recovery-v1"


def test_healthy_observation_has_no_recovery_plan_and_custom_action_cannot_authorize_write():
    healthy = detect_stuck_tasks(
        (
            TaskLivenessObservation(
                task_ref="healthy-1",
                state="queued",
                last_heartbeat=None,
                deadline=NOW + timedelta(hours=1),
                consumer_id="worker-1",
            ),
        ),
        now=NOW,
    )[0]
    assert healthy.recovery_plan is None

    stuck = detect_stuck_tasks(
        (
            TaskLivenessObservation(
                task_ref="custom-action-1",
                state="failed",
                last_heartbeat=NOW,
                external_readback_state="unknown",
                compensation_action="caller-supplied-action",
            ),
        ),
        now=NOW,
    )[0]
    plan = build_recovery_plan(stuck)
    assert plan is not None
    assert stuck.compensation_action == "caller-supplied-action"
    assert plan.action == "reconcile_external_state_before_retry"
    assert plan.action_source == "detector"
    assert plan.external_write_allowed is False
    with pytest.raises(ValueError, match="cannot authorize external writes"):
        type(plan)(
            task_ref=plan.task_ref,
            observation_sha256=plan.observation_sha256,
            action=plan.action,
            required_checks=plan.required_checks,
            steps=plan.steps,
            retry_allowed=False,
            compensation_required=True,
            external_write_allowed=True,
        )
