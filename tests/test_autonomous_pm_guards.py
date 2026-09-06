from datetime import UTC, datetime, timedelta
from decimal import Decimal

from apps.control_plane.autonomous_pm_heartbeat import HeartbeatInput, evaluate_heartbeat
from apps.control_plane.economic_guard_service import EconomicGuardInput, evaluate_economic_guard
from apps.control_plane.stuck_task_detector import TaskLivenessObservation, detect_stuck_tasks


def test_economic_guard_blocks_cash_and_margin_floor():
    result = evaluate_economic_guard(
        EconomicGuardInput(
            cash_available=Decimal("10"),
            min_cash=Decimal("100"),
            margin_rate=Decimal("0.05"),
            min_margin_rate=Decimal("0.10"),
        )
    )
    assert result.status == "blocked"
    assert result.reasons == ("cash_below_floor", "margin_below_floor")
    assert len(result.snapshot_sha256) == 64


def test_economic_guard_fails_closed_for_non_finite_and_negative_snapshots():
    non_finite = evaluate_economic_guard(
        EconomicGuardInput(
            cash_available=Decimal("NaN"),
            min_cash=Decimal("-1"),
            budget_remaining=Decimal("Infinity"),
        )
    )
    assert non_finite.status == "blocked"
    assert "cash_available_non_finite" in non_finite.reasons
    assert "budget_remaining_non_finite" in non_finite.reasons

    negative = evaluate_economic_guard(
        EconomicGuardInput(
            cash_available=Decimal("-1"),
            min_cash=Decimal("-2"),
            budget_remaining=Decimal("-0.01"),
            min_budget_remaining=Decimal("-1"),
        )
    )
    assert negative.status == "blocked"
    assert "cash_available_negative" in negative.reasons
    assert "budget_remaining_negative" in negative.reasons
    assert "min_budget_remaining_negative" in negative.reasons


def test_stuck_detector_handles_deadline_heartbeat_and_consumer():
    now = datetime(2026, 9, 6, 12, tzinfo=UTC)
    result = detect_stuck_tasks(
        (
            TaskLivenessObservation(
                task_ref="t1",
                state="running",
                last_heartbeat=now - timedelta(minutes=10),
                deadline=now - timedelta(seconds=1),
            ),
            TaskLivenessObservation(
                task_ref="t2",
                state="running",
                last_heartbeat=now,
                deadline=now + timedelta(minutes=1),
                consumer_id="worker-1",
            ),
        ),
        now=now,
    )
    assert result[0].status == "stuck"
    assert "deadline_expired" in result[0].reasons
    assert result[1].status == "healthy"


def test_heartbeat_isolates_unknown_external_readback():
    guard = evaluate_economic_guard(EconomicGuardInput(cash_available=Decimal("100")))
    decision = evaluate_heartbeat(
        HeartbeatInput(
            head="abc",
            graph_snapshot_sha256="0" * 64,
            proof_ready=True,
            evidence_fresh=True,
            data_quality_valid=True,
            external_readback_passed=False,
            rollback_available=True,
            economic_guard=guard,
        )
    )
    assert decision.status == "isolate"
    assert "external_readback_not_passed" in decision.reasons


def test_heartbeat_pauses_contaminated_experiments():
    guard = evaluate_economic_guard(EconomicGuardInput(cash_available=Decimal("100")))
    decision = evaluate_heartbeat(
        HeartbeatInput(
            head="abc",
            graph_snapshot_sha256="0" * 64,
            proof_ready=True,
            evidence_fresh=True,
            data_quality_valid=True,
            external_readback_passed=True,
            rollback_available=True,
            economic_guard=guard,
            experiment_clear=False,
        )
    )
    assert decision.status == "hold"
    assert "experiment_contamination_detected" in decision.reasons


def test_heartbeat_requires_current_operational_snapshots_before_dispatch():
    guard = evaluate_economic_guard(EconomicGuardInput(cash_available=Decimal("100")))
    decision = evaluate_heartbeat(
        HeartbeatInput(
            head="abc",
            graph_snapshot_sha256="0" * 64,
            proof_ready=True,
            evidence_fresh=True,
            data_quality_valid=True,
            external_readback_passed=True,
            rollback_available=True,
            economic_guard=guard,
            head_verified=False,
            workspace_state_known=False,
            task_queue_known=False,
            lease_snapshot_known=False,
            test_receipts_current=False,
            proof_receipts_current=False,
        )
    )

    assert decision.status == "hold"
    assert {
        "head_unverified",
        "workspace_state_unknown",
        "task_queue_unknown",
        "lease_snapshot_unknown",
        "test_receipts_stale",
        "proof_receipts_stale",
    }.issubset(decision.reasons)
    assert len(decision.decision_sha256) == 64


def test_stuck_task_recovery_action_is_carried_into_isolation_decision():
    guard = evaluate_economic_guard(EconomicGuardInput(cash_available=Decimal("100")))
    stuck = detect_stuck_tasks(
        (
            TaskLivenessObservation(
                task_ref="t-recover",
                state="completed",
                last_heartbeat=datetime(2026, 9, 6, 12, tzinfo=UTC),
                evidence_required=True,
            ),
        ),
        now=datetime(2026, 9, 6, 12, tzinfo=UTC),
    )
    decision = evaluate_heartbeat(
        HeartbeatInput(
            head="abc",
            graph_snapshot_sha256="0" * 64,
            proof_ready=True,
            evidence_fresh=True,
            data_quality_valid=True,
            external_readback_passed=True,
            rollback_available=True,
            economic_guard=guard,
            stuck_tasks=stuck,
            head_verified=True,
            workspace_state_known=True,
            workspace_clean=True,
            task_queue_known=True,
            lease_snapshot_known=True,
            test_receipts_current=True,
            proof_receipts_current=True,
        )
    )

    assert decision.status == "isolate"
    assert "quarantine_until_evidence_attached" in decision.recovery_actions
