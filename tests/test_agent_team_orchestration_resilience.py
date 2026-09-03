from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.agent_team_orchestration import (
    CircuitState,
    OrchestrationError,
    SessionState,
    TaskState,
    TeamAgentCoordinator,
)
from apps.control_plane.enterprise_control import ExactScope

SCOPE = ExactScope("tenant-a", "entity-a", "ozon-primary")
OTHER_SCOPE = ExactScope("tenant-b", "entity-b", "ozon-secondary")
T0 = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)


def _coordinator(
    *,
    session_ref: str = "session-a",
    max_parallel: int = 4,
    **options: object,
) -> TeamAgentCoordinator:
    coordinator = TeamAgentCoordinator(**options)
    coordinator.create_session(
        session_ref=session_ref,
        scope=SCOPE,
        objective="shadow hardening",
        owner_id="control-owner",
        max_parallel=max_parallel,
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref=session_ref,
        thread_ref=f"{session_ref}:work",
        title="work",
        created_at=T0,
    )
    return coordinator


def _submit(
    coordinator: TeamAgentCoordinator,
    task_ref: str,
    *,
    session_ref: str = "session-a",
    agent_id: str | None = None,
    provider_id: str | None = None,
    created_at: datetime = T0,
    **options: object,
):
    return coordinator.submit_task(
        session_ref=session_ref,
        task_ref=task_ref,
        thread_ref=f"{session_ref}:work",
        agent_id=agent_id or f"agent-{task_ref}",
        role="reader",
        objective=f"read {task_ref}",
        idempotency_key=f"idem-{task_ref}",
        provider_id=provider_id,
        created_at=created_at,
        **options,
    )


def test_429_retry_after_budget_and_circuit_half_open_probe() -> None:
    coordinator = _coordinator(
        lease_ttl_seconds=10,
        retry_base_seconds=1,
        jitter_fn=lambda _delay, _attempt: 0,
    )
    _submit(coordinator, "rate-task", provider_id="provider-a")

    first = coordinator.claim_task(
        task_ref="rate-task",
        worker_id="worker-a",
        as_of=T0,
    )
    assert first.attempt_count == 1
    retry = coordinator.fail_task(
        task_ref="rate-task",
        worker_id="worker-a",
        failure_code="429 Too Many Requests",
        status_code=429,
        retry_after_seconds=7,
        as_of=T0,
    )
    assert retry.state is TaskState.RETRY_WAIT
    assert retry.failure_kind == "rate_limited"
    assert retry.retry_wait_until == T0 + timedelta(seconds=7)
    assert coordinator.tick(as_of=T0 + timedelta(seconds=6))["retry_ready_tasks"] == []
    assert coordinator.tick(as_of=T0 + timedelta(seconds=7))["retry_ready_tasks"] == [
        "rate-task"
    ]

    second = coordinator.claim_task(
        task_ref="rate-task",
        worker_id="worker-a",
        as_of=T0 + timedelta(seconds=7),
    )
    assert second.attempt_count == 2
    retry = coordinator.fail_task(
        task_ref="rate-task",
        worker_id="worker-a",
        failure_code="upstream unavailable",
        status_code=503,
        lease_ref=second.lease_ref,
        as_of=T0 + timedelta(seconds=7),
    )
    assert retry.retry_wait_until == T0 + timedelta(seconds=9)
    coordinator.tick(as_of=T0 + timedelta(seconds=9))

    third = coordinator.claim_task(
        task_ref="rate-task",
        worker_id="worker-a",
        as_of=T0 + timedelta(seconds=9),
    )
    assert third.attempt_count == 3
    blocked = coordinator.fail_task(
        task_ref="rate-task",
        worker_id="worker-a",
        failure_code="provider timeout",
        timeout=True,
        lease_ref=third.lease_ref,
        as_of=T0 + timedelta(seconds=9),
    )
    assert blocked.state is TaskState.BLOCKED
    assert blocked.blocked_reason == "retry_budget_exhausted"
    breaker = coordinator.breaker_state(
        session_ref="session-a",
        provider_id="provider-a",
    )
    assert breaker["state"] == CircuitState.OPEN.value
    assert breaker["failure_count"] == 3

    _submit(
        coordinator,
        "probe",
        provider_id="provider-a",
        created_at=T0 + timedelta(seconds=9),
    )
    with pytest.raises(OrchestrationError, match="circuit breaker"):
        coordinator.claim_task(
            task_ref="probe",
            worker_id="probe-worker",
            as_of=T0 + timedelta(seconds=10),
        )

    coordinator.tick(as_of=T0 + timedelta(seconds=69))
    probe = coordinator.claim_task(
        task_ref="probe",
        worker_id="probe-worker",
        as_of=T0 + timedelta(seconds=69),
    )
    assert probe.state is TaskState.RUNNING
    _submit(
        coordinator,
        "second-probe",
        provider_id="provider-a",
        created_at=T0 + timedelta(seconds=69),
    )
    with pytest.raises(OrchestrationError, match="probe"):
        coordinator.claim_task(
            task_ref="second-probe",
            worker_id="second-worker",
            as_of=T0 + timedelta(seconds=69),
        )
    coordinator.complete_task(
        task_ref="probe",
        worker_id="probe-worker",
        result={"status": "healthy"},
        as_of=T0 + timedelta(seconds=70),
    )
    assert coordinator.breaker_state(
        session_ref="session-a",
        provider_id="provider-a",
    )["state"] == CircuitState.CLOSED.value


def test_lease_heartbeat_expiry_reentry_and_release() -> None:
    coordinator = _coordinator(lease_ttl_seconds=5)
    _submit(coordinator, "leased")
    claimed = coordinator.claim_task(
        task_ref="leased",
        worker_id="worker-a",
        as_of=T0,
    )
    reentered = coordinator.claim_task(
        task_ref="leased",
        worker_id="worker-a",
        as_of=T0 + timedelta(seconds=1),
    )
    assert reentered.lease_ref == claimed.lease_ref
    assert reentered.attempt_count == 1

    heartbeat = coordinator.heartbeat_task(
        task_ref="leased",
        worker_id="worker-a",
        lease_id=claimed.lease_ref,
        extend_seconds=5,
        as_of=T0 + timedelta(seconds=4),
    )
    assert heartbeat.lease_expires_at == T0 + timedelta(seconds=9)
    assert coordinator.tick(as_of=T0 + timedelta(seconds=8))["expired_tasks"] == []
    assert coordinator.tick(as_of=T0 + timedelta(seconds=9))["expired_tasks"] == [
        "leased"
    ]
    assert coordinator.task("leased").state is TaskState.EXPIRED

    reclaimed = coordinator.claim_task(
        task_ref="leased",
        worker_id="worker-b",
        as_of=T0 + timedelta(seconds=10),
    )
    assert reclaimed.attempt_count == 2
    released = coordinator.release_task(
        task_ref="leased",
        worker_id="worker-b",
        lease_id=reclaimed.lease_ref,
        as_of=T0 + timedelta(seconds=11),
    )
    assert released.state is TaskState.QUEUED
    assert coordinator.lease(task_ref="leased") is None


def test_parallel_agent_provider_cost_and_time_budgets() -> None:
    coordinator = TeamAgentCoordinator(
        provider_buckets={"provider-a": 1},
        cost_budget_units=5,
        time_budget_seconds=100,
    )
    coordinator.create_session(
        session_ref="session-a",
        scope=SCOPE,
        objective="budgeted",
        owner_id="owner",
        max_parallel=3,
        max_active_per_agent=1,
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref="session-a",
        thread_ref="session-a:work",
        title="work",
        created_at=T0,
    )
    _submit(coordinator, "a", agent_id="same-agent", provider_id="provider-a")
    _submit(coordinator, "b", agent_id="same-agent", provider_id="provider-b")
    _submit(coordinator, "c", agent_id="other-agent", provider_id="provider-a")
    coordinator.claim_task(task_ref="a", worker_id="wa", as_of=T0)
    with pytest.raises(OrchestrationError, match="single agent"):
        coordinator.claim_task(task_ref="b", worker_id="wb", as_of=T0)
    with pytest.raises(OrchestrationError, match="provider bucket"):
        coordinator.claim_task(task_ref="c", worker_id="wc", as_of=T0)
    coordinator.complete_task(
        task_ref="a",
        worker_id="wa",
        result={"status": "done"},
        cost_units=5,
        as_of=T0 + timedelta(seconds=1),
    )
    with pytest.raises(OrchestrationError, match="cost budget"):
        coordinator.claim_task(
            task_ref="b",
            worker_id="wb",
            as_of=T0 + timedelta(seconds=2),
        )

    timed = _coordinator(
        session_ref="timed",
        time_budget_seconds=10,
    )
    _submit(timed, "late", session_ref="timed")
    with pytest.raises(OrchestrationError, match="time budget"):
        timed.claim_task(
            task_ref="late",
            worker_id="late-worker",
            as_of=T0 + timedelta(seconds=10),
        )
    assert timed.task("late").state is TaskState.BLOCKED


def test_evidence_review_and_recursive_result_boundary() -> None:
    coordinator = _coordinator()
    _submit(
        coordinator,
        "reviewed",
        evidence_required=True,
        reviewer_role="independent-reviewer",
    )
    coordinator.claim_task(task_ref="reviewed", worker_id="worker", as_of=T0)
    with pytest.raises(OrchestrationError, match="Evidence"):
        coordinator.complete_task(
            task_ref="reviewed",
            worker_id="worker",
            result={"status": "done"},
            reviewer_id="reviewer",
            as_of=T0 + timedelta(seconds=1),
        )
    with pytest.raises(OrchestrationError, match="authority"):
        coordinator.complete_task(
            task_ref="reviewed",
            worker_id="worker",
            result={"nested": [{"permit": True}]},
            evidence_refs=("ev-1",),
            reviewer_id="reviewer",
            as_of=T0 + timedelta(seconds=1),
        )
    with pytest.raises(OrchestrationError, match="sensitive"):
        coordinator.complete_task(
            task_ref="reviewed",
            worker_id="worker",
            result={"nested": {"api_key": "redacted"}},
            evidence_refs=("ev-1",),
            reviewer_id="reviewer",
            as_of=T0 + timedelta(seconds=1),
        )
    with pytest.raises(OrchestrationError, match="reviewer"):
        coordinator.complete_task(
            task_ref="reviewed",
            worker_id="worker",
            result={"status": "done"},
            evidence_refs=("ev-1",),
            reviewer_id="agent-reviewed",
            as_of=T0 + timedelta(seconds=1),
        )
    completed = coordinator.complete_task(
        task_ref="reviewed",
        worker_id="worker",
        result={"status": "done"},
        evidence_refs=("ev-1",),
        reviewer_id="reviewer",
        as_of=T0 + timedelta(seconds=1),
    )
    assert completed.state is TaskState.COMPLETED
    assert completed.evidence_refs == ("ev-1",)


@pytest.mark.parametrize(
    "result",
    [
        {"externalWrite": True},
        {"external_write_request": {"target": "marketplace"}},
        {"approval_status": "approved"},
        {"facts": [{"status": "claimed"}]},
        {"kind": "permit"},
        {"nested": {"financeEntry": {"amount": 1}}},
        {"apiKey": "redacted"},
        {"customer": {"emailAddress": "nobody@example.invalid"}},
        {"summary": "contact nobody@example.invalid for approval"},
        {"items": [{"phoneNumber": "+86-000-0000"}]},
        {"passportNumber": "X0000000"},
    ],
)
def test_result_boundary_rejects_camel_case_authority_and_pii(
    result: dict[str, object],
) -> None:
    coordinator = _coordinator()
    _submit(coordinator, "camel-sensitive")
    claimed = coordinator.claim_task(
        task_ref="camel-sensitive",
        worker_id="worker",
        as_of=T0,
    )

    with pytest.raises(OrchestrationError, match="authority|sensitive"):
        coordinator.complete_task(
            task_ref="camel-sensitive",
            worker_id="worker",
            lease_ref=claimed.lease_ref,
            result=result,
            as_of=T0 + timedelta(seconds=1),
        )


def test_completed_result_exports_are_defensive_copies() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "immutable-result")
    claimed = coordinator.claim_task(
        task_ref="immutable-result",
        worker_id="worker-a",
        as_of=T0,
    )

    completed = coordinator.complete_task(
        task_ref="immutable-result",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        result={"nested": {"status": "observed"}},
        as_of=T0 + timedelta(seconds=1),
    )
    assert completed.result is not None
    completed.result["nested"]["status"] = "tampered"
    exported = coordinator.task("immutable-result")
    assert exported.result == {"nested": {"status": "observed"}}

    assert exported.result is not None
    exported.result["nested"]["status"] = "tampered-again"
    assert coordinator.task("immutable-result").result == {
        "nested": {"status": "observed"}
    }


def test_structured_handoff_requires_exact_scope_evidence_and_contract() -> None:
    coordinator = _coordinator()
    coordinator.fork_thread(
        session_ref="session-a",
        thread_ref="session-a:child",
        title="child",
        parent_thread_ref="session-a:work",
        created_at=T0,
    )
    _submit(
        coordinator,
        "source",
        evidence_refs=("ev-input",),
        trace_id="trace-1",
    )
    source_claim = coordinator.claim_task(
        task_ref="source",
        worker_id="source-worker",
        as_of=T0,
    )
    coordinator.complete_task(
        task_ref="source",
        worker_id="source-worker",
        lease_ref=source_claim.lease_ref,
        result={"status": "observed"},
        as_of=T0,
    )
    handoff = coordinator.handoff_task(
        session_ref="session-a",
        source_task_ref="source",
        source_thread_ref="session-a:work",
        target_thread_ref="session-a:child",
        target_role="reviewer",
        input_evidence_refs=("ev-input",),
        acceptance_contract={"required_status": "checked"},
        trace_id="trace-1",
        scope=SCOPE,
        created_at=T0,
    )
    assert handoff.target_role == "reviewer"
    assert coordinator.task("source").handoff_ref == handoff.handoff_ref
    with pytest.raises(OrchestrationError, match="scope conflict"):
        coordinator.handoff_task(
            session_ref="session-a",
            source_task_ref="source",
            source_thread_ref="session-a:work",
            target_thread_ref="session-a:child",
            target_role="reviewer",
            input_evidence_refs=("ev-input",),
            acceptance_contract={"required_status": "checked"},
            trace_id="trace-2",
            scope=OTHER_SCOPE,
        )


def test_event_cursor_merge_resume_and_conflicts() -> None:
    source = _coordinator()
    _submit(source, "event-task")
    stream = source.events(session_ref="session-a")
    assert source.events(after_cursor=stream[0]["cursor"]) == stream[1:]

    replica = TeamAgentCoordinator()
    first_merge = replica.merge_events(stream)
    assert first_merge.status == "merged"
    assert len(first_merge) == len(stream)
    replay = replica.merge_events(stream)
    assert replay.status == "merged"
    assert len(replay) == len(stream)

    gap_replica = TeamAgentCoordinator()
    gap = gap_replica.merge_events(stream[1:])
    assert gap.status == "conflict"
    assert "event sequence gap" in gap.conflicts

    tampered = deepcopy(stream)
    tampered[0]["payload"]["owner_id"] = "other-owner"
    hash_conflict = TeamAgentCoordinator().merge_events(tampered)
    assert hash_conflict.status == "conflict"
    assert any("hash" in reason for reason in hash_conflict.conflicts)

    scope_replica = TeamAgentCoordinator()
    assert scope_replica.merge_events(stream[:1]).status == "merged"
    second = source._deserialize_event(stream[1])
    wrong_scope = replace(
        second,
        scope={
            "tenant_ref": "tenant-b",
            "entity_ref": "entity-b",
            "store_ref": "ozon-secondary",
        },
    )
    scope_conflict = scope_replica.merge_events((wrong_scope,))
    assert scope_conflict.status == "conflict"
    assert "event scope conflict" in scope_conflict.conflicts
    assert scope_replica.conflict_count == 1


def test_checkpoint_restore_tamper_scope_and_deterministic_snapshot() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "checkpointed", evidence_required=True)
    checkpoint = coordinator.checkpoint(session_ref="session-a")
    restored = TeamAgentCoordinator.restore(checkpoint, scope=SCOPE)
    assert restored.snapshot(session_ref="session-a")["snapshot_sha256"] == coordinator.snapshot(
        session_ref="session-a"
    )["snapshot_sha256"]

    tampered = deepcopy(checkpoint)
    tampered["tasks"][0]["objective"] = "tampered"
    with pytest.raises(OrchestrationError, match="checkpoint hash"):
        TeamAgentCoordinator.restore(tampered)
    with pytest.raises(OrchestrationError, match="scope conflict"):
        TeamAgentCoordinator.restore(checkpoint, scope=OTHER_SCOPE)

    snapshot = coordinator.snapshot(session_ref="session-a")
    assert snapshot["task_waves"] == [
        {"wave": 0, "task_refs": ["checkpointed"], "task_count": 1}
    ]
    assert snapshot["evidence_completeness"]["missing_tasks"] == ["checkpointed"]
    assert snapshot["control_boundary"]["external_write_allowed"] is False
    assert snapshot == coordinator.snapshot(session_ref="session-a")


def test_pause_and_kill_switch_do_not_create_new_execution() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "stopped")
    coordinator.pause(
        session_ref="session-a",
        reason="manual hold",
        actor_id="risk-owner",
        as_of=T0,
    )
    with pytest.raises(OrchestrationError, match="active"):
        coordinator.claim_task(
            task_ref="stopped",
            worker_id="worker",
            as_of=T0,
        )
    coordinator.resume(
        session_ref="session-a",
        actor_id="risk-owner",
        as_of=T0 + timedelta(seconds=1),
    )
    assert coordinator.session("session-a").state is SessionState.ACTIVE
    coordinator.kill_switch(
        session_ref="session-a",
        reason="P0",
        actor_id="risk-owner",
        as_of=T0 + timedelta(seconds=2),
    )
    with pytest.raises(OrchestrationError, match="active"):
        coordinator.claim_task(
            task_ref="stopped",
            worker_id="worker",
            as_of=T0 + timedelta(seconds=2),
        )
    tick = coordinator.tick(as_of=T0 + timedelta(seconds=100))
    assert tick["retry_ready_tasks"] == []
