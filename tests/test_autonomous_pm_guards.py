from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from apps.control_plane.autonomous_pm_heartbeat import (
    SERVER_AUTHORITY_FIELDS,
    AuthorityObservation,
    GitWorktreeObservation,
    HeartbeatInput,
    ServerAuthoritySnapshot,
    evaluate_heartbeat,
    observe_server_authority,
    observe_server_git_worktree,
)
from apps.control_plane.economic_guard_service import EconomicGuardInput, evaluate_economic_guard
from apps.control_plane.stuck_task_detector import TaskLivenessObservation, detect_stuck_tasks


def _server_authority_readers(scope: str, *, status: str = "valid"):
    def make_reader(name: str):
        def read(**values):
            return AuthorityObservation(
                name=name,
                status=status,
                scope_key=values["scope_key"],
                observed_at=values["observed_at"],
                source_ref=f"server://test/{name}",
                payload_sha256=(name.encode().hex() + "0" * 64)[:64],
                reason="test_blocked" if status in {"blocked", "unknown"} else None,
            )

        return read

    return {name: make_reader(name) for name in SERVER_AUTHORITY_FIELDS}


def _server_git(observed_at: datetime, *, clean: bool = True):
    return GitWorktreeObservation(
        status="observed",
        head="a" * 40,
        worktree_clean=clean,
        status_sha256="b" * 64,
        observed_at=observed_at,
    )


def test_server_git_observation_derives_flags_from_actual_probe():
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        if args[1] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout="A" * 40, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    observed = observe_server_git_worktree(
        repository_root=".",
        observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        runner=runner,
    )

    assert observed.status == "observed"
    assert observed.available is True
    assert observed.head == "a" * 40
    assert observed.worktree_clean is True
    assert observed.flags_for("A" * 40) == {
        "head_verified": True,
        "workspace_state_known": True,
        "workspace_clean": True,
    }
    assert observed.flags_for("b" * 40)["head_verified"] is False
    assert len(observed.snapshot_sha256) == 64
    assert all(kwargs["shell"] is False for _args, kwargs in calls)


def test_server_git_observation_failure_is_explicit_and_fail_closed():
    def runner(_args, **_kwargs):
        raise OSError("git unavailable")

    observed = observe_server_git_worktree(
        repository_root=".",
        observed_at=datetime(2026, 9, 6, 12, tzinfo=UTC),
        runner=runner,
    )

    assert observed.status == "blocked"
    assert observed.reason == "git_probe_failed"
    assert observed.flags_for("a" * 40) == {
        "head_verified": False,
        "workspace_state_known": False,
        "workspace_clean": False,
    }
    assert len(observed.snapshot_sha256) == 64


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


def test_heartbeat_defaults_to_experiment_hold():
    guard = evaluate_economic_guard(EconomicGuardInput(cash_available=Decimal("100")))
    decision = evaluate_heartbeat(
        HeartbeatInput(
            head="abc", graph_snapshot_sha256="0" * 64, proof_ready=True,
            evidence_fresh=True, data_quality_valid=True,
            external_readback_passed=True, rollback_available=True,
            economic_guard=guard,
        )
    )
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


def test_server_authority_snapshot_derives_all_dispatch_gates_from_readers():
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    scope = "tenant-a/entity-a/store-a"
    calls: list[tuple[str, datetime]] = []
    readers = {}
    for name in SERVER_AUTHORITY_FIELDS:
        def read(*, scope_key, observed_at, _name=name):
            calls.append((scope_key, observed_at))
            return AuthorityObservation(
                name=_name,
                status="valid",
                scope_key=scope_key,
                observed_at=observed_at,
                source_ref=f"server://test/{_name}",
                payload_sha256="a" * 64,
            )

        readers[name] = read
    guard = evaluate_economic_guard(
        EconomicGuardInput(cash_available=Decimal("100"))
    )

    snapshot = observe_server_authority(
        readers,
        scope_key=scope,
        economic_guard_reader=lambda **_values: guard,
        git_observation=_server_git(now),
        observed_at=now,
    )
    heartbeat = HeartbeatInput.from_server_authority(
        snapshot,
        head="a" * 40,
        graph_snapshot_sha256="c" * 64,
        proof_ready=True,
    )

    assert snapshot.status == "ready"
    assert snapshot.authority_reasons() == ()
    assert heartbeat.task_queue_known is True
    assert heartbeat.lease_snapshot_known is True
    assert heartbeat.test_receipts_current is True
    assert heartbeat.proof_receipts_current is True
    assert heartbeat.evidence_fresh is True
    assert heartbeat.data_quality_valid is True
    assert heartbeat.external_readback_passed is True
    assert heartbeat.rollback_available is True
    assert heartbeat.experiment_clear is True
    assert heartbeat.economic_guard.status == "allowed"
    assert evaluate_heartbeat(heartbeat).status == "dispatch"
    assert calls == [(scope, now)] * len(SERVER_AUTHORITY_FIELDS)


def test_server_authority_reader_failures_and_expiry_hold_without_caller_claims():
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    scope = "tenant-a/entity-a/store-a"
    readers = _server_authority_readers(scope)
    readers.pop("task_queue")

    def failing_reader(**_values):
        raise RuntimeError("private platform payload")

    readers["lease_snapshot"] = failing_reader
    readers["evidence"] = lambda **values: AuthorityObservation(
        name="evidence",
        status="valid",
        scope_key=values["scope_key"],
        observed_at=now - timedelta(minutes=5),
        expires_at=now - timedelta(seconds=1),
        source_ref="server://test/evidence",
        payload_sha256="d" * 64,
    )
    guard = evaluate_economic_guard(
        EconomicGuardInput(cash_available=Decimal("100"))
    )
    snapshot = observe_server_authority(
        readers,
        scope_key=scope,
        economic_guard_reader=lambda **_values: guard,
        git_observation=_server_git(now),
        observed_at=now,
    )
    heartbeat = snapshot.to_heartbeat_input(
        head="a" * 40,
        graph_snapshot_sha256="c" * 64,
        proof_ready=True,
    )
    decision = evaluate_heartbeat(heartbeat)

    assert heartbeat.task_queue_known is False
    assert heartbeat.lease_snapshot_known is False
    assert heartbeat.evidence_fresh is False
    assert decision.status == "hold"
    assert "server_observation_unavailable:task_queue" in decision.reasons
    assert "server_observation_unavailable:lease_snapshot" in decision.reasons
    assert "server_observation_stale:evidence" in decision.reasons
    assert "private platform payload" not in " ".join(decision.reasons)


def test_server_authority_rejects_scope_or_source_tampering_and_fails_closed():
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    scope = "tenant-a/entity-a/store-a"
    readers = _server_authority_readers(scope)
    readers["data_quality"] = lambda **values: AuthorityObservation(
        name="data_quality",
        status="valid",
        scope_key="tenant-b/entity-b/store-b",
        observed_at=values["observed_at"],
        source_ref="server://test/data-quality",
        payload_sha256="e" * 64,
    )
    readers["rollback"] = lambda **values: {
        "status": "valid",
        "scope_key": values["scope_key"],
        "observed_at": values["observed_at"].isoformat(),
        "source_ref": "client://rollback",
        "payload_sha256": "f" * 64,
    }
    guard = evaluate_economic_guard(
        EconomicGuardInput(cash_available=Decimal("100"))
    )
    snapshot = observe_server_authority(
        readers,
        scope_key=scope,
        economic_guard_reader=lambda **_values: guard,
        git_observation=_server_git(now),
        observed_at=now,
    )

    heartbeat = snapshot.to_heartbeat_input(
        head="a" * 40,
        graph_snapshot_sha256="c" * 64,
        proof_ready=True,
    )
    assert heartbeat.data_quality_valid is False
    assert heartbeat.rollback_available is False
    reasons = snapshot.authority_reasons()
    assert "server_observation_unavailable:data_quality" in reasons
    assert "server_observation_unavailable:rollback" in reasons


def test_server_authority_snapshot_is_replayable_and_digest_bound():
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    scope = "tenant-a/entity-a/store-a"
    readers = _server_authority_readers(scope)
    guard = evaluate_economic_guard(
        EconomicGuardInput(cash_available=Decimal("100"))
    )
    first = observe_server_authority(
        readers,
        scope_key=scope,
        economic_guard_reader=lambda **_values: guard,
        git_observation=_server_git(now),
        observed_at=now,
    )
    replayed = ServerAuthoritySnapshot(
        scope_key=first.scope_key,
        observed_at=first.observed_at,
        observations=first.observations,
        economic_guard=first.economic_guard,
        economic_observation=first.economic_observation,
        git=first.git,
        snapshot_sha256=first.snapshot_sha256,
    )

    assert replayed.snapshot_sha256 == first.snapshot_sha256
    assert replayed.to_heartbeat_input(
        head="a" * 40,
        graph_snapshot_sha256="c" * 64,
        proof_ready=True,
    ) == first.to_heartbeat_input(
        head="a" * 40,
        graph_snapshot_sha256="c" * 64,
        proof_ready=True,
    )
