from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from apps.control_plane.enterprise_control import ExactScope
from apps.control_plane.team_agent_persistence import (
    DurableTaskState,
    InMemoryTeamAgentPersistence,
    PostgresTeamAgentPersistence,
    TeamAgentPersistenceConflict,
    TeamAgentTaskNotFound,
    TeamAgentTaskRegistration,
)
from apps.control_plane.team_agent_result_contract import (
    TeamAgentResultContractError,
)

SCOPE = ExactScope("tenant-a", "entity-a", "ozon-primary")
OTHER_SCOPE = ExactScope("tenant-b", "entity-b", "ozon-secondary")
T0 = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
UNSAFE_RESULTS = (
    pytest.param({"secret": "credential-material"}, id="secret-key"),
    pytest.param(
        {"message": "Authorization: Bearer abcdefghijklmnop"},
        id="bearer-value",
    ),
    pytest.param(
        {"summary": "Contact the operator at operator@example.com"},
        id="personal-email-value",
    ),
    pytest.param({"Fact": {"status": "minted"}}, id="fact"),
    pytest.param({"FinanceEntry": {"amount": "1.00"}}, id="finance-entry"),
    pytest.param({"Approval": {"status": "approved"}}, id="approval"),
    pytest.param({"Permit": {"status": "issued"}}, id="permit"),
    pytest.param({"external-write": True}, id="external-write"),
)


def registration(
    *,
    task_ref: str = "catalog-read",
    idempotency_key: str = "idem-catalog-read",
    objective: str = "read catalog",
    max_attempts: int = 3,
    payload_extra: dict[str, object] | None = None,
) -> TeamAgentTaskRegistration:
    payload = {
        "agent_id": "catalog-reader",
        "objective": objective,
        "dependencies": [],
        **(payload_extra or {}),
    }
    return TeamAgentTaskRegistration(
        session_ref="session-a",
        task_ref=task_ref,
        idempotency_key=idempotency_key,
        payload=payload,
        max_attempts=max_attempts,
    )


def test_registration_is_idempotent_and_payload_drift_fails_closed() -> None:
    store = InMemoryTeamAgentPersistence()
    created = store.register_task(scope=SCOPE, task=registration(), as_of=T0)
    replay = store.register_task(scope=SCOPE, task=registration(), as_of=T0)

    assert replay == created
    assert created.state is DurableTaskState.QUEUED
    assert created.revision == 0
    with pytest.raises(TeamAgentPersistenceConflict, match="idempotency"):
        store.register_task(
            scope=SCOPE,
            task=registration(objective="changed objective"),
            as_of=T0,
        )


def test_mutation_timestamp_cannot_regress_task_event_chain() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(), as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=2),
    )

    with pytest.raises(TeamAgentPersistenceConflict, match="regresses"):
        store.heartbeat_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
            worker_id="worker-a",
            lease_ref=claimed.lease_ref or "missing",
            extend_seconds=10,
            as_of=T0 + timedelta(seconds=1),
        )

    current = store.task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
    )
    assert current.revision == claimed.revision
    assert [event["event_type"] for event in store.checkpoint(
        scope=SCOPE, session_ref="session-a"
    )["events"]] == ["registered", "claimed"]


def test_heartbeat_preserves_an_exact_budget_capped_deadline() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(), as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )

    capped_deadline = T0 + timedelta(seconds=3, microseconds=250_000)
    heartbeat = store.heartbeat_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref or "missing",
        extend_seconds=5,
        lease_expires_at=capped_deadline,
        as_of=T0 + timedelta(seconds=2),
    )

    assert heartbeat.lease_expires_at == capped_deadline
    assert store.task(
        scope=SCOPE, session_ref="session-a", task_ref="catalog-read"
    ).lease_expires_at == capped_deadline


def test_complete_roundtrips_result_evidence_and_reviewer() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(), as_of=T0)
    first = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert first.lease_ref is not None

    reclaimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-b",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=30),
    )
    assert reclaimed.lease_ref is not None

    with pytest.raises(TeamAgentPersistenceConflict, match="does not match"):
        store.complete_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
            worker_id="worker-a",
            lease_ref=first.lease_ref,
            result={"status": "stale"},
            as_of=T0 + timedelta(seconds=31),
        )

    completed = store.complete_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-b",
        lease_ref=reclaimed.lease_ref,
        result={"status": "ok", "items": 3},
        evidence_refs=("evd-1", "evd-2"),
        reviewer_id="reviewer-a",
        as_of=T0 + timedelta(seconds=31),
    )
    assert completed.state is DurableTaskState.COMPLETED
    assert completed.result == {"items": 3, "status": "ok"}
    assert completed.evidence_refs == ("evd-1", "evd-2")
    assert completed.reviewer_id == "reviewer-a"
    assert completed.completed_at == T0 + timedelta(seconds=31)

    checkpoint = store.checkpoint(scope=SCOPE, session_ref="session-a")
    task = checkpoint["tasks"][0]
    assert task["result"] == {"items": 3, "status": "ok"}
    assert task["evidence_refs"] == ["evd-1", "evd-2"]
    assert task["reviewer_id"] == "reviewer-a"
    assert checkpoint["events"][-1]["event_type"] == "completed"


def test_completion_policy_requires_evidence_and_independent_reviewer() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(
        scope=SCOPE,
        task=registration(
            task_ref="policy-task",
            idempotency_key="idem-policy-task",
            payload_extra={
                "requires_evidence": True,
                "reviewer_role": "independent-reviewer",
            },
        ),
        as_of=T0,
    )
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="policy-task",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    with pytest.raises(TeamAgentPersistenceConflict, match="Evidence"):
        store.complete_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="policy-task",
            worker_id="worker-a",
            lease_ref=claimed.lease_ref or "missing",
            result={"status": "done"},
            reviewer_id="reviewer-a",
            as_of=T0 + timedelta(seconds=1),
        )
    with pytest.raises(TeamAgentPersistenceConflict, match="reviewer"):
        store.complete_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="policy-task",
            worker_id="worker-a",
            lease_ref=claimed.lease_ref or "missing",
            result={"status": "done"},
            evidence_refs=("ev-policy",),
            reviewer_id="worker-a",
            as_of=T0 + timedelta(seconds=1),
        )
    completed = store.complete_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="policy-task",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref or "missing",
        result={"status": "done"},
        evidence_refs=("ev-policy",),
        reviewer_id="reviewer-a",
        as_of=T0 + timedelta(seconds=1),
    )
    assert completed.state is DurableTaskState.COMPLETED


def test_retry_wait_schedule_is_bounded_and_non_retry_metadata_is_cleared() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(max_attempts=2), as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    retry = store.fail_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref or "missing",
        failure_code="timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=T0 + timedelta(minutes=5),
        as_of=T0 + timedelta(seconds=1),
    )
    assert retry.retry_wait_until == T0 + timedelta(seconds=31)
    assert retry.retry_after_seconds == 30
    second = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-b",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=31),
    )
    failed = store.fail_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-b",
        lease_ref=second.lease_ref or "missing",
        failure_code="fatal",
        failure_kind="business",
        next_state=DurableTaskState.FAILED,
        retry_after_seconds=30,
        as_of=T0 + timedelta(seconds=32),
    )
    assert failed.retry_wait_until is None
    assert failed.retry_after_seconds is None


@pytest.mark.parametrize("unsafe_result", UNSAFE_RESULTS)
def test_complete_rejects_unsafe_results_without_consuming_the_lease(
    unsafe_result: dict[str, object],
) -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(), as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None

    with pytest.raises(TeamAgentResultContractError):
        store.complete_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            result=unsafe_result,
            as_of=T0 + timedelta(seconds=1),
        )

    persisted = store.task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
    )
    assert persisted.state is DurableTaskState.RUNNING
    assert persisted.revision == claimed.revision
    assert [
        event["event_type"]
        for event in store.checkpoint(scope=SCOPE, session_ref="session-a")["events"]
    ] == ["registered", "claimed"]


def test_fail_task_supports_retry_wait_and_blocked_metadata() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(max_attempts=2), as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None

    retry_wait = store.fail_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        failure_code="provider_timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=T0 + timedelta(seconds=45),
        retry_after_seconds=30,
        as_of=T0 + timedelta(seconds=15),
    )
    assert retry_wait.state is DurableTaskState.RETRY_WAIT
    assert retry_wait.failure_code == "provider_timeout"
    assert retry_wait.failure_kind == "timeout"
    assert retry_wait.retry_wait_until == T0 + timedelta(seconds=45)
    assert retry_wait.retry_after_seconds == 30.0

    with pytest.raises(TeamAgentPersistenceConflict, match="waiting for retry"):
        store.claim_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
            worker_id="worker-b",
            lease_seconds=30,
            as_of=T0 + timedelta(seconds=44),
        )

    second = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-b",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=45),
    )
    assert second.lease_ref is not None
    assert second.failure_code is None
    assert second.failure_kind is None
    assert second.result is None
    assert second.evidence_refs == ()
    assert second.reviewer_id is None
    blocked = store.fail_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-b",
        lease_ref=second.lease_ref,
        failure_code="provider_fatal",
        failure_kind="server_error",
        next_state=DurableTaskState.BLOCKED,
        blocked_reason="retry_budget_exhausted",
        as_of=T0 + timedelta(seconds=50),
    )
    assert blocked.state is DurableTaskState.BLOCKED
    assert blocked.blocked_reason == "retry_budget_exhausted"
    assert [event["event_type"] for event in store.checkpoint(scope=SCOPE, session_ref="session-a")["events"]] == [
        "registered",
        "claimed",
        "retry_wait",
        "claimed",
        "blocked",
    ]


def test_retry_wait_rejects_an_exhausted_attempt_budget() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(
        scope=SCOPE,
        task=registration(max_attempts=1),
        as_of=T0,
    )
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert claimed.lease_ref is not None

    with pytest.raises(TeamAgentPersistenceConflict, match="retry budget"):
        store.fail_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            failure_code="provider_timeout",
            failure_kind="timeout",
            next_state=DurableTaskState.RETRY_WAIT,
            retry_wait_until=T0 + timedelta(seconds=20),
            as_of=T0 + timedelta(seconds=1),
        )

    still_running = store.task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
    )
    assert still_running.state is DurableTaskState.RUNNING
    assert still_running.revision == claimed.revision
    failed = store.fail_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        failure_code="provider_timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.FAILED,
        as_of=T0 + timedelta(seconds=1),
    )
    assert failed.state is DurableTaskState.FAILED


def test_retry_then_complete_has_only_current_success_metadata() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(
        scope=SCOPE,
        task=registration(max_attempts=2),
        as_of=T0,
    )
    first = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert first.lease_ref is not None
    store.fail_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_ref=first.lease_ref,
        failure_code="provider_timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=T0 + timedelta(seconds=20),
        as_of=T0 + timedelta(seconds=1),
    )
    second = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-b",
        lease_seconds=30,
        as_of=T0 + timedelta(seconds=20),
    )
    assert second.lease_ref is not None

    completed = store.complete_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-b",
        lease_ref=second.lease_ref,
        result={"status": "observed"},
        evidence_refs=("evd-current",),
        reviewer_id="reviewer-current",
        as_of=T0 + timedelta(seconds=21),
    )
    assert completed.state is DurableTaskState.COMPLETED
    assert completed.failure_code is None
    assert completed.failure_kind is None
    assert completed.blocked_reason is None
    assert completed.evidence_refs == ("evd-current",)
    assert completed.reviewer_id == "reviewer-current"


def test_pause_and_expire_are_guarded_and_roundtrip() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(task_ref="queued-task"), as_of=T0)
    paused = store.pause_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="queued-task",
        reason="controlled_pause",
        as_of=T0,
    )
    assert paused.state is DurableTaskState.PAUSED
    assert paused.blocked_reason == "controlled_pause"
    resumed = store.resume_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="queued-task",
        as_of=T0 + timedelta(seconds=1),
    )
    assert resumed.state is DurableTaskState.QUEUED
    assert resumed.blocked_reason is None

    store.register_task(
        scope=SCOPE,
        task=registration(task_ref="expiring-task", idempotency_key="idem-expiring", max_attempts=2),
        as_of=T0,
    )
    running = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="expiring-task",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    assert running.lease_ref is not None
    with pytest.raises(TeamAgentPersistenceConflict, match="not expired"):
        store.expire_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="expiring-task",
            as_of=T0 + timedelta(seconds=29),
        )
    expired = store.expire_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="expiring-task",
        as_of=T0 + timedelta(seconds=30),
    )
    assert expired.state is DurableTaskState.EXPIRED
    assert expired.blocked_reason == "lease_expired"
    assert expired.expired_at == T0 + timedelta(seconds=30)

    store.register_task(
        scope=SCOPE,
        task=registration(task_ref="blocked-task", idempotency_key="idem-blocked", max_attempts=1),
        as_of=T0,
    )
    blocked_running = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="blocked-task",
        worker_id="worker-b",
        lease_seconds=30,
        as_of=T0,
    )
    assert blocked_running.lease_ref is not None
    blocked = store.expire_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="blocked-task",
        as_of=T0 + timedelta(seconds=30),
    )
    assert blocked.state is DurableTaskState.BLOCKED
    assert blocked.blocked_reason == "retry_budget_exhausted"

    store.register_task(
        scope=SCOPE,
        task=registration(
            task_ref="revoked-task",
            idempotency_key="idem-revoked",
        ),
        as_of=T0,
    )
    revoking = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="revoked-task",
        worker_id="worker-c",
        lease_seconds=30,
        as_of=T0,
    )
    revoked = store.revoke_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="revoked-task",
        reason="session kill switch",
        as_of=T0 + timedelta(seconds=1),
    )
    assert revoking.lease_ref is not None
    assert revoked.state is DurableTaskState.EXPIRED
    assert revoked.blocked_reason == "session kill switch"
    assert revoked.expired_at == T0 + timedelta(seconds=1)


def test_unleased_budget_terminal_is_replayable_and_fail_closed() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(), as_of=T0)

    blocked = store.block_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        reason="time_budget_exhausted",
        as_of=T0 + timedelta(seconds=10),
    )

    assert blocked.state is DurableTaskState.BLOCKED
    assert blocked.blocked_reason == "time_budget_exhausted"
    assert [
        event["event_type"]
        for event in store.checkpoint(scope=SCOPE, session_ref="session-a")[
            "events"
        ]
    ] == ["registered", "blocked"]
    with pytest.raises(TeamAgentPersistenceConflict, match="not unleased"):
        store.block_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
            reason="time_budget_exhausted",
            as_of=T0 + timedelta(seconds=11),
        )


def test_expired_lease_accepts_only_the_coordinator_budget_terminal() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(max_attempts=2), as_of=T0)
    store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=10,
        lease_expires_at=T0 + timedelta(seconds=5),
        as_of=T0,
    )

    blocked = store.expire_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        next_state=DurableTaskState.BLOCKED,
        blocked_reason="time_budget_exhausted",
        as_of=T0 + timedelta(seconds=5),
    )

    assert blocked.state is DurableTaskState.BLOCKED
    assert blocked.blocked_reason == "time_budget_exhausted"
    assert blocked.expired_at is None


def test_pause_resume_preserves_a_future_retry_schedule() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(max_attempts=2), as_of=T0)
    claimed = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    retry_at = T0 + timedelta(seconds=20)
    retrying = store.fail_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref or "missing",
        failure_code="provider_timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=retry_at,
        retry_after_seconds=19,
        as_of=T0 + timedelta(seconds=1),
    )
    paused = store.pause_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        reason="controlled pause",
        as_of=T0 + timedelta(seconds=2),
    )
    resumed = store.resume_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        as_of=T0 + timedelta(seconds=3),
    )
    assert retrying.retry_wait_until == paused.retry_wait_until == retry_at
    assert resumed.state is DurableTaskState.RETRY_WAIT
    assert resumed.retry_wait_until == retry_at
    assert resumed.retry_after_seconds == 19
    assert [
        event["event_type"]
        for event in store.checkpoint(scope=SCOPE, session_ref="session-a")["events"]
    ] == ["registered", "claimed", "retry_wait", "paused", "resumed"]


def test_requested_lease_pause_resume_and_kill_revocation_roundtrip() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(), as_of=T0)
    requested_lease = "tal_runtime_selected_lease"
    running = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        worker_id="worker-a",
        lease_seconds=30,
        lease_ref=requested_lease,
        as_of=T0,
    )
    assert running.lease_ref == requested_lease
    with pytest.raises(TeamAgentPersistenceConflict, match="lease identity"):
        store.claim_task(
            scope=SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
            worker_id="worker-a",
            lease_seconds=30,
            lease_ref="tal_conflicting_lease",
            as_of=T0,
        )

    revoked = store.revoke_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="catalog-read",
        reason="kill switch",
        as_of=T0 + timedelta(seconds=1),
    )
    assert revoked.state is DurableTaskState.EXPIRED
    assert revoked.blocked_reason == "kill switch"
    assert revoked.expired_at == T0 + timedelta(seconds=1)

    store.register_task(
        scope=SCOPE,
        task=registration(
            task_ref="retry-task",
            idempotency_key="idem-retry-task",
        ),
        as_of=T0,
    )
    retry_running = store.claim_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="retry-task",
        worker_id="worker-b",
        lease_seconds=30,
        as_of=T0,
    )
    assert retry_running.lease_ref is not None
    store.fail_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="retry-task",
        worker_id="worker-b",
        lease_ref=retry_running.lease_ref,
        failure_code="provider_timeout",
        failure_kind="timeout",
        next_state=DurableTaskState.RETRY_WAIT,
        retry_wait_until=T0 + timedelta(seconds=20),
        retry_after_seconds=19,
        as_of=T0 + timedelta(seconds=1),
    )
    paused = store.pause_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="retry-task",
        reason="controlled pause",
        as_of=T0 + timedelta(seconds=2),
    )
    assert paused.retry_wait_until == T0 + timedelta(seconds=20)
    resumed_waiting = store.resume_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="retry-task",
        as_of=T0 + timedelta(seconds=3),
    )
    assert resumed_waiting.state is DurableTaskState.RETRY_WAIT
    assert resumed_waiting.retry_wait_until == T0 + timedelta(seconds=20)

    store.pause_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="retry-task",
        reason="controlled pause",
        as_of=T0 + timedelta(seconds=4),
    )
    resumed_ready = store.resume_task(
        scope=SCOPE,
        session_ref="session-a",
        task_ref="retry-task",
        as_of=T0 + timedelta(seconds=20),
    )
    assert resumed_ready.state is DurableTaskState.QUEUED
    assert resumed_ready.retry_wait_until is None
    assert [
        event["event_type"]
        for event in store.checkpoint(scope=SCOPE, session_ref="session-a")["events"]
        if event["task_ref"] == "retry-task"
    ] == ["registered", "claimed", "retry_wait", "paused", "resumed", "paused", "resumed"]


def test_exact_scope_is_part_of_every_read_and_mutation() -> None:
    store = InMemoryTeamAgentPersistence()
    store.register_task(scope=SCOPE, task=registration(), as_of=T0)

    with pytest.raises(TeamAgentTaskNotFound):
        store.task(
            scope=OTHER_SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
        )
    with pytest.raises(TeamAgentTaskNotFound):
        store.claim_task(
            scope=OTHER_SCOPE,
            session_ref="session-a",
            task_ref="catalog-read",
            worker_id="worker-a",
            lease_seconds=30,
            as_of=T0,
        )


def test_postgres_adapter_rejects_a_non_postgres_engine() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        with pytest.raises(ValueError, match="requires PostgreSQL"):
            PostgresTeamAgentPersistence(engine)
    finally:
        engine.dispose()


def test_checkpoint_rejects_task_event_tail_divergence() -> None:
    store = InMemoryTeamAgentPersistence()
    registered = registration()
    store.register_task(scope=SCOPE, task=registered, as_of=T0)
    store._events[-1]["payload"]["state"] = "running"  # noqa: SLF001

    with pytest.raises(TeamAgentPersistenceConflict, match="event tail"):
        store.checkpoint(
            scope=SCOPE,
            session_ref=registered.session_ref,
        )
