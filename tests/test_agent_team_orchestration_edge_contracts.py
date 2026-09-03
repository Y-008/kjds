from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import pytest

from apps.control_plane import agent_team_orchestration as orchestration
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


def _zero_jitter(_delay: float, _attempt: int) -> int:
    return 0


def _checkpoint_sha256(checkpoint: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            checkpoint,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _event_payload_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _coordinator(
    *,
    session_time_budget_seconds: int | None = None,
    lease_ttl_seconds: int = 30,
    breaker_failure_threshold: int = 3,
    breaker_cooldown_seconds: int = 60,
) -> TeamAgentCoordinator:
    coordinator = TeamAgentCoordinator(
        lease_ttl_seconds=lease_ttl_seconds,
        breaker_failure_threshold=breaker_failure_threshold,
        breaker_cooldown_seconds=breaker_cooldown_seconds,
        jitter_fn=_zero_jitter,
    )
    coordinator.create_session(
        session_ref="session-a",
        scope=SCOPE,
        objective="edge contracts",
        owner_id="control-owner",
        max_parallel=4,
        time_budget_seconds=session_time_budget_seconds,
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref="session-a",
        thread_ref="session-a:work",
        title="work",
        created_at=T0,
    )
    return coordinator


def _submit(
    coordinator: TeamAgentCoordinator,
    task_ref: str,
    *,
    session_ref: str = "session-a",
    thread_ref: str | None = None,
    provider_id: str | None = None,
    time_budget_seconds: int | None = None,
    trace_id: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    acceptance_contract: dict[str, object] | None = None,
) -> None:
    coordinator.submit_task(
        session_ref=session_ref,
        task_ref=task_ref,
        thread_ref=thread_ref or f"{session_ref}:work",
        agent_id=f"agent-{task_ref}",
        role="reader",
        objective=f"read {task_ref}",
        idempotency_key=f"idem-{task_ref}",
        provider_id=provider_id,
        time_budget_seconds=time_budget_seconds,
        trace_id=trace_id,
        evidence_refs=evidence_refs,
        acceptance_contract=acceptance_contract,
        created_at=T0,
    )


def test_fork_thread_defaults_to_current_utc_instead_of_session_timestamp() -> None:
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref="session-a",
        scope=SCOPE,
        objective="default thread timestamp",
        owner_id="control-owner",
        max_parallel=4,
        created_at=datetime(1970, 1, 1, tzinfo=UTC),
    )
    session_before = coordinator.session("session-a")

    thread = coordinator.fork_thread(
        session_ref="session-a",
        thread_ref="session-a:work",
        title="work",
    )

    assert thread.created_at > session_before.updated_at


def test_public_exports_include_new_orchestration_contract_types() -> None:
    assert {
        "CircuitState",
        "EventMergeResult",
        "TeamAgentHandoff",
    } <= set(orchestration.__all__)


def test_completed_response_loss_replay_is_idempotent_and_drift_conflicts() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "response-loss", trace_id="trace-response-loss")
    claimed = coordinator.claim_task(
        task_ref="response-loss",
        worker_id="worker-a",
        as_of=T0 + timedelta(seconds=1),
    )
    assert claimed.lease_ref is not None
    request = {
        "task_ref": "response-loss",
        "worker_id": "worker-a",
        "lease_ref": claimed.lease_ref,
        "result": {"status": "observed", "items": 2},
        "evidence_refs": ("ev-response-loss",),
        "reviewer_id": "reviewer-a",
        "cost_units": 3,
    }
    completed = coordinator.complete_task(
        **request,
        as_of=T0 + timedelta(seconds=2),
    )
    event_count = len(coordinator.events(session_ref="session-a"))

    replayed = coordinator.complete_task(
        **request,
        as_of=T0 + timedelta(seconds=3),
    )

    assert replayed == completed
    assert len(coordinator.events(session_ref="session-a")) == event_count
    with pytest.raises(OrchestrationError, match="completion replay conflict"):
        coordinator.complete_task(
            **{**request, "result": {"status": "different"}},
            as_of=T0 + timedelta(seconds=3),
        )
    assert len(coordinator.events(session_ref="session-a")) == event_count


def test_failed_response_loss_replay_is_idempotent_and_drift_conflicts() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "failed-response-loss", trace_id="trace-failed-response")
    claimed = coordinator.claim_task(
        task_ref="failed-response-loss",
        worker_id="worker-a",
        as_of=T0 + timedelta(seconds=1),
    )
    assert claimed.lease_ref is not None
    request = {
        "task_ref": "failed-response-loss",
        "worker_id": "worker-a",
        "lease_ref": claimed.lease_ref,
        "failure_code": "business_validation_failed",
        "retryable": False,
        "trace_id": "trace-failed-response",
    }
    failed = coordinator.fail_task(
        **request,
        as_of=T0 + timedelta(seconds=2),
    )
    assert failed.state is TaskState.FAILED
    event_count = len(coordinator.events(session_ref="session-a"))

    replayed = coordinator.fail_task(
        **request,
        as_of=T0 + timedelta(seconds=3),
    )

    assert replayed == failed
    assert len(coordinator.events(session_ref="session-a")) == event_count
    with pytest.raises(OrchestrationError, match="failure replay conflict"):
        coordinator.fail_task(
            **{**request, "failure_code": "different_failure"},
            as_of=T0 + timedelta(seconds=3),
        )
    with pytest.raises(OrchestrationError, match="failure replay conflict"):
        coordinator.fail_task(
            **{**request, "timeout": True},
            as_of=T0 + timedelta(seconds=3),
        )
    with pytest.raises(OrchestrationError, match="failure replay conflict"):
        coordinator.fail_task(
            **{**request, "thread_id": "wrong-thread"},
            as_of=T0 + timedelta(seconds=3),
        )
    assert len(coordinator.events(session_ref="session-a")) == event_count


def test_retry_wait_response_loss_replay_preserves_original_schedule() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "retry-response-loss", trace_id="trace-retry-response")
    claimed = coordinator.claim_task(
        task_ref="retry-response-loss",
        worker_id="worker-a",
        as_of=T0 + timedelta(seconds=1),
    )
    assert claimed.lease_ref is not None
    request = {
        "task_ref": "retry-response-loss",
        "worker_id": "worker-a",
        "lease_ref": claimed.lease_ref,
        "failure_code": "provider_timeout",
        "status_code": 504,
        "retry_after_seconds": 30,
        "trace_id": "trace-retry-response",
    }
    failed = coordinator.fail_task(**request, as_of=T0 + timedelta(seconds=2))
    assert failed.state is TaskState.RETRY_WAIT
    event_count = len(coordinator.events(session_ref="session-a"))
    replayed = coordinator.fail_task(**request, as_of=T0 + timedelta(seconds=3))
    assert replayed == failed
    assert len(coordinator.events(session_ref="session-a")) == event_count


def test_handoff_replay_is_idempotent_and_changed_request_conflicts() -> None:
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
        trace_id="trace-1",
        evidence_refs=("ev-input",),
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
    request = {
        "session_ref": "session-a",
        "source_task_ref": "source",
        "source_thread_ref": "session-a:work",
        "target_thread_ref": "session-a:child",
        "target_role": "reviewer",
        "input_evidence_refs": ("ev-input",),
        "acceptance_contract": {"required_status": "checked"},
        "trace_id": "trace-1",
        "scope": SCOPE,
    }

    first = coordinator.handoff_task(**request, created_at=T0)
    replay = coordinator.handoff_task(
        **request,
        created_at=T0 + timedelta(seconds=1),
    )

    assert replay == first
    assert coordinator.handoffs(session_ref="session-a") == (first,)
    assert sum(event["event_type"] == "task.handoff" for event in coordinator.events(session_ref="session-a")) == 1

    changed_request = dict(request)
    changed_request["trace_id"] = "trace-2"
    with pytest.raises(OrchestrationError, match="idempotency_conflict"):
        coordinator.handoff_task(**changed_request)


def test_handoff_source_task_must_belong_to_source_thread() -> None:
    coordinator = _coordinator()
    coordinator.fork_thread(
        session_ref="session-a",
        thread_ref="session-a:other",
        title="other",
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref="session-a",
        thread_ref="session-a:other-child",
        title="other child",
        parent_thread_ref="session-a:other",
        created_at=T0,
    )
    _submit(coordinator, "source", thread_ref="session-a:work")

    with pytest.raises(OrchestrationError, match="source task.*thread"):
        coordinator.handoff_task(
            session_ref="session-a",
            source_task_ref="source",
            source_thread_ref="session-a:other",
            target_thread_ref="session-a:other-child",
            target_role="reviewer",
            input_evidence_refs=("ev-input",),
            acceptance_contract={"required_status": "checked"},
            trace_id="trace-1",
            scope=SCOPE,
            created_at=T0,
        )


@pytest.mark.parametrize(
    ("session_budget", "task_budget"),
    [(10, None), (None, 10)],
)
def test_completion_at_time_budget_deadline_blocks_and_releases_lease(
    session_budget: int | None,
    task_budget: int | None,
) -> None:
    coordinator = _coordinator(session_time_budget_seconds=session_budget)
    _submit(coordinator, "timed", time_budget_seconds=task_budget)
    claimed = coordinator.claim_task(
        task_ref="timed",
        worker_id="worker-a",
        as_of=T0,
    )

    with pytest.raises(OrchestrationError, match="time budget"):
        coordinator.complete_task(
            task_ref="timed",
            worker_id="worker-a",
            lease_id=claimed.lease_ref,
            result={"status": "late"},
            as_of=T0 + timedelta(seconds=10),
        )

    blocked = coordinator.task("timed")
    assert blocked.state is TaskState.BLOCKED
    assert blocked.blocked_reason == "time_budget_exhausted"
    assert blocked.lease_ref is None
    assert coordinator.lease(task_ref="timed") is None


@pytest.mark.parametrize("mutation", ["release", "fail"])
def test_lease_mutations_at_time_budget_deadline_record_terminal_before_fence(
    mutation: str,
) -> None:
    coordinator = _coordinator(session_time_budget_seconds=10)
    _submit(coordinator, f"timed-{mutation}")
    claimed = coordinator.claim_task(
        task_ref=f"timed-{mutation}",
        worker_id="worker-a",
        as_of=T0,
    )

    with pytest.raises(OrchestrationError, match="time budget"):
        if mutation == "release":
            coordinator.release_task(
                task_ref="timed-release",
                worker_id="worker-a",
                lease_ref=claimed.lease_ref,
                as_of=T0 + timedelta(seconds=10),
            )
        else:
            coordinator.fail_task(
                task_ref="timed-fail",
                worker_id="worker-a",
                lease_ref=claimed.lease_ref,
                failure_code="late failure",
                as_of=T0 + timedelta(seconds=10),
            )

    task = coordinator.task(f"timed-{mutation}")
    assert task.state is TaskState.BLOCKED
    assert task.blocked_reason == "time_budget_exhausted"
    assert task.lease_ref is None
    assert coordinator.observations(session_ref="session-a")[-1].kind == (
        "task.blocked"
    )
    restored = TeamAgentCoordinator.restore(
        coordinator.checkpoint(session_ref="session-a"),
        jitter_fn=_zero_jitter,
    )
    assert restored.task(f"timed-{mutation}").state is TaskState.BLOCKED


def test_first_event_batch_is_bound_to_expected_scope_and_contract() -> None:
    source = _coordinator()
    _submit(source, "event-task")
    stream = source.events(session_ref="session-a")

    wrong_scope = TeamAgentCoordinator().merge_events(
        stream,
        expected_scope=OTHER_SCOPE,
        expected_contract_id=orchestration.CONTRACT_ID,
        expected_contract_version=orchestration.CONTRACT_VERSION,
    )
    assert wrong_scope.status == "conflict"
    assert "event scope conflict" in wrong_scope.conflicts

    wrong_contract = TeamAgentCoordinator().merge_events(
        stream,
        expected_scope=SCOPE,
        expected_contract_id="other-orchestration-contract",
        expected_contract_version=orchestration.CONTRACT_VERSION,
    )
    assert wrong_contract.status == "conflict"
    assert "event contract drift" in wrong_contract.conflicts


@pytest.mark.parametrize("missing_field", ["contract_id", "contract_version"])
def test_event_missing_contract_field_is_a_merge_conflict(missing_field: str) -> None:
    source = _coordinator()
    stream = deepcopy(source.events(session_ref="session-a"))
    stream[0].pop(missing_field)

    result = TeamAgentCoordinator().merge_events(
        stream,
        expected_scope=SCOPE,
        expected_contract_id=orchestration.CONTRACT_ID,
        expected_contract_version=orchestration.CONTRACT_VERSION,
    )

    assert result.status == "conflict"
    assert "event contract drift" in result.conflicts


def test_event_hash_rejects_created_at_tampering() -> None:
    source = _coordinator()
    event = deepcopy(source.events(session_ref="session-a")[0])
    event["created_at"] = (T0 + timedelta(seconds=1)).isoformat()

    result = TeamAgentCoordinator().merge_events(
        (event,),
        expected_scope=SCOPE,
    )

    assert result.status == "conflict"
    assert "event hash conflict" in result.conflicts


def test_event_merge_rejects_same_session_created_at_regression() -> None:
    source = _coordinator()
    _submit(source, "regressed-event")
    stream = list(deepcopy(source.events(session_ref="session-a")))
    stream[-1]["created_at"] = (T0 - timedelta(seconds=1)).isoformat()
    stream[-1].pop("event_hash")

    result = TeamAgentCoordinator().merge_events(
        stream,
        expected_scope=SCOPE,
    )

    assert result.status == "conflict"
    assert "event created_at regression" in result.conflicts


def test_event_merge_treats_same_batch_duplicate_as_idempotent_replay() -> None:
    source = _coordinator()
    _submit(source, "same-batch")
    stream = list(source.events(session_ref="session-a"))

    replica = TeamAgentCoordinator()
    result = replica.merge_events(
        (*stream, deepcopy(stream[-1])),
        expected_scope=SCOPE,
    )

    assert result.status == "merged"
    assert len(replica.events(session_ref="session-a")) == len(stream)
    assert replica.task("same-batch").state is TaskState.QUEUED


def test_duplicate_merge_returns_the_replayed_sessions_cursor() -> None:
    source = _coordinator()
    _submit(source, "session-a-task")
    source.create_session(
        session_ref="session-b",
        scope=OTHER_SCOPE,
        objective="independent session",
        owner_id="control-owner",
        created_at=T0,
    )
    source.submit_task(
        session_ref="session-b",
        task_ref="session-b-task",
        thread_ref="session-b:root",
        agent_id="agent-b",
        role="reader",
        objective="read B",
        idempotency_key="idem-b",
        created_at=T0,
    )
    stream_a = source.events(session_ref="session-a")
    stream_b = source.events(session_ref="session-b")
    replica = TeamAgentCoordinator()
    replica.merge_events(stream_a, expected_scope=SCOPE)
    replica.merge_events(stream_b, expected_scope=OTHER_SCOPE)

    replay = replica.merge_events(stream_a, expected_scope=SCOPE)

    assert replay.status == "merged"
    assert replay.cursor == stream_a[-1]["cursor"]


def test_event_merge_rebuilds_completed_in_process_projection() -> None:
    source = _coordinator()
    _submit(source, "projected")
    claimed = source.claim_task(
        task_ref="projected",
        worker_id="worker-a",
        as_of=T0,
    )
    source.complete_task(
        task_ref="projected",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        result={"status": "observed"},
        evidence_refs=("ev-projected",),
        as_of=T0 + timedelta(seconds=1),
    )

    replica = TeamAgentCoordinator()
    merged = replica.merge_events(
        source.events(session_ref="session-a"),
        expected_scope=SCOPE,
    )

    assert merged.status == "merged"
    assert replica.snapshot(session_ref="session-a") == source.snapshot(
        session_ref="session-a"
    )
    restored = TeamAgentCoordinator.restore(
        replica.checkpoint(session_ref="session-a"),
        scope=SCOPE,
    )
    assert restored.task("projected").state is TaskState.COMPLETED


def test_event_merge_rejects_rehashed_task_attempt_budget_escalation() -> None:
    source = _coordinator()
    _submit(source, "bounded")
    stream = list(deepcopy(source.events(session_ref="session-a")))
    submitted = stream[-1]
    assert submitted["event_type"] == "task.submitted"
    submitted["payload"]["max_attempts"] = 99
    submitted["payload_sha256"] = _event_payload_sha256(submitted["payload"])
    submitted.pop("event_hash")

    replica = TeamAgentCoordinator()
    result = replica.merge_events(stream, expected_scope=SCOPE)

    assert result.status == "conflict"
    assert "event projection max attempts conflict" in result.conflicts
    with pytest.raises(KeyError, match="session"):
        replica.session("session-a")


def test_event_merge_conflict_is_isolated_from_other_session_snapshot() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "scoped-conflict")
    coordinator.create_session(
        session_ref="session-b",
        scope=OTHER_SCOPE,
        objective="unrelated session",
        owner_id="control-owner",
        created_at=T0,
    )
    before = coordinator.snapshot(session_ref="session-b")
    tampered = deepcopy(coordinator.events(session_ref="session-a")[-1])
    tampered["payload"]["max_attempts"] = 99
    tampered["payload_sha256"] = _event_payload_sha256(tampered["payload"])
    tampered.pop("event_hash")

    conflict = coordinator.merge_events((tampered,), expected_scope=SCOPE)

    assert conflict.status == "conflict"
    assert coordinator.snapshot(session_ref="session-b") == before
    checkpoint = coordinator.checkpoint(session_ref="session-b")
    assert checkpoint["conflicts"] == []


@pytest.mark.parametrize(
    ("field", "value", "expected_conflict"),
    [
        ("provider_id", "provider-b", "provider association"),
        ("trace_id", "trace-b", "trace association"),
        (
            "expires_at",
            (T0 + timedelta(days=30)).isoformat(),
            "lease expiry",
        ),
    ],
)
def test_event_merge_rejects_rehashed_claim_association_or_lease_escalation(
    field: str,
    value: str,
    expected_conflict: str,
) -> None:
    source = _coordinator()
    _submit(
        source,
        "frozen",
        provider_id="provider-a",
        trace_id="trace-a",
    )
    source.claim_task(
        task_ref="frozen",
        worker_id="worker-a",
        as_of=T0,
    )
    stream = list(deepcopy(source.events(session_ref="session-a")))
    claimed = stream[-1]
    assert claimed["event_type"] == "task.claimed"
    claimed["payload"][field] = value
    claimed["payload_sha256"] = _event_payload_sha256(claimed["payload"])
    claimed.pop("event_hash")

    result = TeamAgentCoordinator().merge_events(stream, expected_scope=SCOPE)

    assert result.status == "conflict"
    assert any(expected_conflict in reason for reason in result.conflicts)


def test_expired_task_reclaim_remains_checkpoint_restore_safe() -> None:
    coordinator = _coordinator(lease_ttl_seconds=2)
    _submit(coordinator, "reclaimed")
    coordinator.claim_task(
        task_ref="reclaimed",
        worker_id="worker-a",
        as_of=T0,
    )
    coordinator.tick(as_of=T0 + timedelta(seconds=2))

    reclaimed = coordinator.claim_task(
        task_ref="reclaimed",
        worker_id="worker-b",
        as_of=T0 + timedelta(seconds=3),
    )

    assert reclaimed.state is TaskState.RUNNING
    assert reclaimed.expired_at is None
    restored = TeamAgentCoordinator.restore(
        coordinator.checkpoint(session_ref="session-a"),
        scope=SCOPE,
        jitter_fn=_zero_jitter,
    )
    assert restored.snapshot(session_ref="session-a") == coordinator.snapshot(
        session_ref="session-a"
    )


def test_targeted_expiry_does_not_advance_unrelated_retry_work() -> None:
    coordinator = _coordinator(lease_ttl_seconds=2)
    _submit(coordinator, "expiring")
    _submit(coordinator, "waiting")
    coordinator.claim_task(task_ref="expiring", worker_id="worker-a", as_of=T0)
    coordinator.claim_task(task_ref="waiting", worker_id="worker-b", as_of=T0)
    coordinator.fail_task(
        task_ref="waiting",
        worker_id="worker-b",
        failure_code="rate_limited",
        status_code=429,
        retry_after_seconds=1,
        as_of=T0,
    )

    expired = coordinator.expire_task(
        task_ref="expiring",
        as_of=T0 + timedelta(seconds=2),
    )

    assert expired.state is TaskState.EXPIRED
    assert expired.expired_at == T0 + timedelta(seconds=2)
    waiting = coordinator.task("waiting")
    assert waiting.state is TaskState.RETRY_WAIT
    assert waiting.retry_wait_until == T0 + timedelta(seconds=1)


def test_budget_expiry_blocks_without_expired_timestamp() -> None:
    coordinator = _coordinator(session_time_budget_seconds=1)
    _submit(coordinator, "budgeted")
    coordinator.claim_task(task_ref="budgeted", worker_id="worker-a", as_of=T0)

    blocked = coordinator.expire_task(
        task_ref="budgeted",
        as_of=T0 + timedelta(seconds=1),
    )

    assert blocked.state is TaskState.BLOCKED
    assert blocked.blocked_reason == "time_budget_exhausted"
    assert blocked.expired_at is None


def test_same_worker_claim_reentry_cannot_rebind_provider_or_trace() -> None:
    coordinator = _coordinator()
    _submit(
        coordinator,
        "reentry",
        provider_id="provider-a",
        trace_id="trace-a",
    )
    coordinator.claim_task(
        task_ref="reentry",
        worker_id="worker-a",
        as_of=T0,
    )

    with pytest.raises(OrchestrationError, match="provider association"):
        coordinator.claim_task(
            task_ref="reentry",
            worker_id="worker-a",
            provider_id="provider-b",
            as_of=T0 + timedelta(seconds=1),
        )
    with pytest.raises(OrchestrationError, match="trace association"):
        coordinator.claim_task(
            task_ref="reentry",
            worker_id="worker-a",
            trace_id="trace-b",
            as_of=T0 + timedelta(seconds=1),
        )


def test_same_worker_claim_reentry_cannot_accept_a_stale_lease_id() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "reentry-lease")
    claimed = coordinator.claim_task(
        task_ref="reentry-lease",
        worker_id="worker-a",
        lease_id="lease-current",
        as_of=T0,
    )

    with pytest.raises(OrchestrationError, match="lease_id"):
        coordinator.claim_task(
            task_ref="reentry-lease",
            worker_id="worker-a",
            lease_id="lease-stale",
            as_of=T0 + timedelta(seconds=1),
        )

    assert coordinator.task("reentry-lease").lease_ref == claimed.lease_ref


def test_handoff_target_thread_cannot_be_rebound_by_another_source() -> None:
    coordinator = _coordinator()
    coordinator.fork_thread(
        session_ref="session-a",
        thread_ref="session-a:target",
        title="target",
        parent_thread_ref="session-a:work",
        created_at=T0,
    )
    for task_ref, trace_id, evidence_ref in (
        ("source-a", "trace-a", "ev-a"),
        ("source-b", "trace-b", "ev-b"),
    ):
        _submit(
            coordinator,
            task_ref,
            trace_id=trace_id,
            evidence_refs=(evidence_ref,),
        )
        claimed = coordinator.claim_task(
            task_ref=task_ref,
            worker_id=f"worker-{task_ref}",
            as_of=T0,
        )
        coordinator.complete_task(
            task_ref=task_ref,
            worker_id=f"worker-{task_ref}",
            lease_ref=claimed.lease_ref,
            result={"status": "observed"},
            as_of=T0,
        )

    coordinator.handoff_task(
        session_ref="session-a",
        source_task_ref="source-a",
        source_thread_ref="session-a:work",
        target_thread_ref="session-a:target",
        target_role="reviewer",
        input_evidence_refs=("ev-a",),
        acceptance_contract={"required_status": "checked"},
        trace_id="trace-a",
        scope=SCOPE,
        created_at=T0,
    )

    with pytest.raises(OrchestrationError, match="already bound"):
        coordinator.handoff_task(
            session_ref="session-a",
            source_task_ref="source-b",
            source_thread_ref="session-a:work",
            target_thread_ref="session-a:target",
            target_role="reviewer",
            input_evidence_refs=("ev-b",),
            acceptance_contract={"required_status": "checked"},
            trace_id="trace-b",
            scope=SCOPE,
            created_at=T0,
        )

    restored = TeamAgentCoordinator.restore(
        coordinator.checkpoint(session_ref="session-a"),
        scope=SCOPE,
        jitter_fn=_zero_jitter,
    )
    assert len(restored.handoffs(session_ref="session-a")) == 1


def test_release_task_rejects_non_running_and_terminal_tasks() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "release")

    with pytest.raises(OrchestrationError, match="running"):
        coordinator.release_task(task_ref="release", worker_id="worker-a")
    assert coordinator.task("release").state is TaskState.QUEUED

    coordinator.claim_task(task_ref="release", worker_id="worker-a", as_of=T0)
    coordinator.complete_task(
        task_ref="release",
        worker_id="worker-a",
        result={"status": "done"},
        as_of=T0 + timedelta(seconds=1),
    )
    with pytest.raises(OrchestrationError, match="running"):
        coordinator.release_task(task_ref="release", worker_id="worker-a")
    assert coordinator.task("release").state is TaskState.COMPLETED


def test_expired_half_open_probe_releases_probe_and_has_no_stale_next_check() -> None:
    coordinator = _coordinator(
        lease_ttl_seconds=2,
        breaker_failure_threshold=1,
        breaker_cooldown_seconds=5,
    )
    _submit(coordinator, "trigger", provider_id="provider-a")
    coordinator.claim_task(task_ref="trigger", worker_id="worker-a", as_of=T0)
    coordinator.fail_task(
        task_ref="trigger",
        worker_id="worker-a",
        failure_code="upstream unavailable",
        status_code=503,
        as_of=T0,
    )
    _submit(coordinator, "probe", provider_id="provider-a")

    coordinator.tick(as_of=T0 + timedelta(seconds=5))
    coordinator.claim_task(
        task_ref="probe",
        worker_id="probe-worker",
        lease_seconds=2,
        as_of=T0 + timedelta(seconds=5),
    )
    expired_at = T0 + timedelta(seconds=7)
    tick = coordinator.tick(as_of=expired_at)

    assert tick["expired_tasks"] == ["probe"]
    assert tick["next_check_at"] is None or datetime.fromisoformat(tick["next_check_at"]) > expired_at
    breaker = coordinator.breaker_state(
        session_ref="session-a",
        provider_id="provider-a",
    )
    assert breaker["state"] == CircuitState.HALF_OPEN.value
    assert breaker["probe_in_flight"] is False


def test_rehashed_internal_checkpoint_tamper_is_rejected_atomically() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "checkpointed")
    before = coordinator.snapshot(session_ref="session-a")
    tampered = deepcopy(coordinator.checkpoint(session_ref="session-a"))
    tampered["tasks"][0]["objective"] = "tampered objective"
    tampered.pop("checkpoint_sha256")
    tampered["checkpoint_sha256"] = _checkpoint_sha256(tampered)

    with pytest.raises(OrchestrationError):
        coordinator.load_checkpoint(tampered, scope=SCOPE)

    assert coordinator.snapshot(session_ref="session-a") == before


def test_kill_switch_cannot_be_cleared_through_pause_or_resume() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "stopped")
    coordinator.engage_kill_switch(
        session_ref="session-a",
        reason="P0 incident",
        actor_id="risk-owner",
        as_of=T0,
    )

    with pytest.raises(OrchestrationError, match="active sessions"):
        coordinator.pause(
            session_ref="session-a",
            reason="alternate pause path",
            actor_id="risk-owner",
            as_of=T0 + timedelta(seconds=1),
        )
    with pytest.raises(OrchestrationError, match="release_kill_switch"):
        coordinator.resume(
            session_ref="session-a",
            actor_id="risk-owner",
            as_of=T0 + timedelta(seconds=1),
        )

    stopped = coordinator.session("session-a")
    assert stopped.state is SessionState.CLOSED
    assert stopped.kill_switch_engaged is True

    released = coordinator.release_kill_switch(
        session_ref="session-a",
        reason="incident resolved",
        actor_id="risk-owner",
        as_of=T0 + timedelta(seconds=2),
    )
    assert released.state is SessionState.ACTIVE
    assert released.kill_switch_engaged is False


def test_cross_thread_dependency_barrier_waits_for_parent_completion() -> None:
    coordinator = _coordinator()
    coordinator.fork_thread(
        session_ref="session-a",
        thread_ref="session-a:dependent",
        title="dependent thread",
        created_at=T0,
    )
    _submit(coordinator, "source", thread_ref="session-a:work")
    coordinator.submit_task(
        session_ref="session-a",
        task_ref="dependent",
        thread_ref="session-a:dependent",
        agent_id="agent-dependent",
        role="reviewer",
        objective="wait for source",
        idempotency_key="idem-dependent",
        dependencies=("source",),
        created_at=T0,
    )

    with pytest.raises(OrchestrationError, match="dependencies"):
        coordinator.claim_task(
            task_ref="dependent",
            worker_id="dependent-worker",
            as_of=T0,
        )

    coordinator.claim_task(task_ref="source", worker_id="source-worker", as_of=T0)
    coordinator.complete_task(
        task_ref="source",
        worker_id="source-worker",
        result={"status": "done"},
        as_of=T0 + timedelta(seconds=1),
    )
    claimed = coordinator.claim_task(
        task_ref="dependent",
        worker_id="dependent-worker",
        as_of=T0 + timedelta(seconds=1),
    )
    assert claimed.state is TaskState.RUNNING
    assert claimed.thread_ref == "session-a:dependent"


def test_429_event_uses_canonical_session_thread_and_trace_associations() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "rate-limited", provider_id="provider-a")
    coordinator.claim_task(
        task_ref="rate-limited",
        worker_id="worker-a",
        trace_id="trace-429",
        as_of=T0,
    )

    with pytest.raises(OrchestrationError, match="session association conflict"):
        coordinator.fail_task(
            task_ref="rate-limited",
            worker_id="worker-a",
            failure_code="429 Too Many Requests",
            status_code=429,
            session_id="other-session",
            as_of=T0,
        )
    with pytest.raises(OrchestrationError, match="thread association conflict"):
        coordinator.fail_task(
            task_ref="rate-limited",
            worker_id="worker-a",
            failure_code="429 Too Many Requests",
            status_code=429,
            thread_id="other-thread",
            as_of=T0,
        )

    retry = coordinator.fail_task(
        task_ref="rate-limited",
        worker_id="worker-a",
        failure_code="429 Too Many Requests",
        status_code=429,
        retry_after_seconds=4,
        as_of=T0,
    )
    assert retry.state is TaskState.RETRY_WAIT

    event = coordinator.events(session_ref="session-a")[-1]
    assert event["event_type"] == "task.retry_wait"
    assert (
        event["payload"]
        | {
            "session_ref": "session-a",
            "thread_ref": "session-a:work",
            "session_id": "session-a",
            "thread_id": "session-a:work",
            "trace_id": "trace-429",
        }
        == event["payload"]
    )


def test_http_date_retry_after_is_preferred_and_bounded() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "retry-after", provider_id="provider-a")
    coordinator.claim_task(
        task_ref="retry-after",
        worker_id="worker-a",
        as_of=T0,
    )

    retry_after = format_datetime(T0 + timedelta(seconds=45), usegmt=True)
    retry = coordinator.fail_task(
        task_ref="retry-after",
        worker_id="worker-a",
        failure_code="429 Too Many Requests",
        status_code=429,
        retry_after=retry_after,
        as_of=T0,
    )

    assert retry.retry_after_seconds == 45
    assert retry.retry_wait_until == T0 + timedelta(seconds=30)


def test_circuit_breakers_are_isolated_by_session_and_provider() -> None:
    coordinator = _coordinator(breaker_failure_threshold=1)
    coordinator.create_session(
        session_ref="session-b",
        scope=OTHER_SCOPE,
        objective="independent session",
        owner_id="control-owner",
        max_parallel=2,
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref="session-b",
        thread_ref="session-b:work",
        title="work",
        created_at=T0,
    )
    _submit(coordinator, "trigger", provider_id="provider-a")
    _submit(coordinator, "other-provider", provider_id="provider-b")
    _submit(
        coordinator,
        "other-session",
        session_ref="session-b",
        provider_id="provider-a",
    )

    coordinator.claim_task(task_ref="trigger", worker_id="worker-a", as_of=T0)
    coordinator.fail_task(
        task_ref="trigger",
        worker_id="worker-a",
        failure_code="upstream unavailable",
        status_code=503,
        as_of=T0,
    )

    assert coordinator.breaker_state(
        session_ref="session-a",
        provider_id="provider-a",
    )["state"] == CircuitState.OPEN.value
    assert coordinator.claim_task(
        task_ref="other-provider",
        worker_id="worker-b",
        as_of=T0,
    ).state is TaskState.RUNNING
    assert coordinator.claim_task(
        task_ref="other-session",
        worker_id="worker-c",
        as_of=T0,
    ).state is TaskState.RUNNING


def test_preclaim_time_budget_terminal_is_event_replayable_and_observable() -> None:
    coordinator = _coordinator(session_time_budget_seconds=10)
    _submit(coordinator, "queued-budget")

    with pytest.raises(OrchestrationError, match="time budget"):
        coordinator.claim_task(
            task_ref="queued-budget",
            worker_id="worker-a",
            as_of=T0 + timedelta(seconds=10),
        )

    blocked = coordinator.task("queued-budget")
    assert blocked.state is TaskState.BLOCKED
    assert blocked.blocked_reason == "time_budget_exhausted"
    assert coordinator.events(session_ref="session-a")[-1]["event_type"] == (
        "task.time_budget_exhausted"
    )
    assert [
        observation.kind
        for observation in coordinator.observations(session_ref="session-a")
    ] == ["task.blocked"]

    restored = TeamAgentCoordinator.restore(
        coordinator.checkpoint(),
        jitter_fn=_zero_jitter,
    )
    assert restored.task("queued-budget").state is TaskState.BLOCKED
    assert restored.observations(session_ref="session-a")[0].kind == "task.blocked"


def test_mixed_session_event_batch_fails_closed_without_a_cursor() -> None:
    sender = _coordinator()
    sender.create_session(
        session_ref="session-b",
        scope=OTHER_SCOPE,
        objective="independent scope",
        owner_id="owner-b",
        created_at=T0,
    )
    result = TeamAgentCoordinator().merge_events(
        tuple(sender.events(session_ref="session-a"))
        + tuple(sender.events(session_ref="session-b"))
    )
    assert result.status == "conflict"
    assert "event batch spans multiple sessions" in result.conflicts
    assert result.cursor is None


def test_control_event_object_merge_detaches_nested_payload_and_scope() -> None:
    sender = _coordinator()
    _submit(
        sender,
        "event-copy",
        acceptance_contract={"nested": {"status": "required"}},
    )
    incoming = [
        sender._deserialize_event(item)
        for item in sender.events(session_ref="session-a")
    ]
    receiver = TeamAgentCoordinator(jitter_fn=_zero_jitter)

    result = receiver.merge_events(incoming, expected_scope=SCOPE)
    assert result.status == "merged"

    submitted = next(
        event for event in incoming if event.event_type == "task.submitted"
    )
    submitted.payload["acceptance_contract"]["nested"]["status"] = "tampered"
    submitted.scope["entity_ref"] = "tampered"

    stored = next(
        event
        for event in receiver.events(session_ref="session-a")
        if event["event_type"] == "task.submitted"
    )
    assert stored["payload"]["acceptance_contract"] == {
        "nested": {"status": "required"}
    }
    assert stored["scope"]["entity_ref"] == "entity-a"
    restored = TeamAgentCoordinator.restore(
        receiver.checkpoint(session_ref="session-a"),
        jitter_fn=_zero_jitter,
    )
    assert restored.task("event-copy").acceptance_contract == {
        "nested": {"status": "required"}
    }


def test_public_nested_dataclass_exports_are_defensive_copies() -> None:
    coordinator = TeamAgentCoordinator(provider_buckets={"provider-a": 2})
    coordinator.create_session(
        session_ref="copy-session",
        scope=SCOPE,
        objective="copy boundary",
        owner_id="owner-a",
        created_at=T0,
        provider_buckets={"provider-a": 2},
    )
    coordinator.fork_thread(
        session_ref="copy-session",
        thread_ref="copy-session:work",
        title="work",
        created_at=T0,
    )
    coordinator.submit_task(
        session_ref="copy-session",
        task_ref="copy-task",
        thread_ref="copy-session:work",
        agent_id="agent-copy",
        role="reader",
        objective="copy boundary",
        idempotency_key="copy-task-v1",
        acceptance_contract={"nested": {"status": "required"}},
        created_at=T0,
    )

    session = coordinator.session("copy-session")
    session.provider_buckets["provider-a"] = 99
    task = coordinator.task("copy-task")
    task.acceptance_contract["nested"]["status"] = "tampered"

    assert coordinator.session("copy-session").provider_buckets == {"provider-a": 2}
    assert coordinator.task("copy-task").acceptance_contract == {
        "nested": {"status": "required"}
    }


def test_completed_task_result_export_is_a_defensive_copy() -> None:
    coordinator = _coordinator()
    _submit(coordinator, "result-copy")
    claimed = coordinator.claim_task(
        task_ref="result-copy",
        worker_id="worker-result",
        as_of=T0,
    )
    coordinator.complete_task(
        task_ref="result-copy",
        worker_id="worker-result",
        lease_ref=claimed.lease_ref,
        result={"nested": {"status": "observed"}},
        as_of=T0 + timedelta(seconds=1),
    )

    exported = coordinator.task("result-copy")
    assert exported.result is not None
    exported.result["nested"]["status"] = "tampered"

    assert coordinator.task("result-copy").result == {
        "nested": {"status": "observed"}
    }
