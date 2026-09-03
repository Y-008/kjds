import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.agent_team_orchestration import (
    TEAM_AGENT_HARNESS_VERIFIER_ID,
    TEAM_AGENT_HARNESS_VERIFIER_VERSION,
    OrchestrationError,
    SessionState,
    TaskState,
    TeamAgentCoordinator,
    TeamAgentHarnessBridge,
)
from apps.control_plane.enterprise_control import ExactScope
from apps.control_plane.security import Principal

SCOPE = ExactScope("tenant-a", "entity-a", "ozon-primary")
T0 = datetime(2026, 8, 19, tzinfo=UTC)


def _coordinator() -> TeamAgentCoordinator:
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref="session-1",
        scope=SCOPE,
        objective="reconcile current Ozon facts",
        owner_id="owner-1",
        max_parallel=2,
        authority_sha256="a" * 64,
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref="session-1",
        thread_ref="thread-read",
        title="read facts",
        created_at=T0,
    )
    return coordinator


def test_multiple_threads_and_subagents_run_with_dependency_barrier():
    coordinator = _coordinator()
    first = coordinator.submit_task(
        session_ref="session-1",
        task_ref="catalog",
        thread_ref="thread-read",
        agent_id="agent-catalog",
        role="catalog-reader",
        objective="read official catalog",
        idempotency_key="catalog-v1",
        created_at=T0,
    )
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="orders",
        thread_ref="thread-read",
        agent_id="agent-orders",
        role="order-reader",
        objective="read official orders",
        idempotency_key="orders-v1",
        dependencies=(first.task_ref,),
        created_at=T0,
    )
    claimed = coordinator.claim_task(task_ref="catalog", worker_id="worker-a")
    assert claimed.state is TaskState.RUNNING
    with pytest.raises(OrchestrationError, match="dependencies"):
        coordinator.claim_task(task_ref="orders", worker_id="worker-b")
    coordinator.complete_task(task_ref="catalog", worker_id="worker-a", result={"status": "observed"}, evidence_refs=("ev-catalog",))
    coordinator.claim_task(task_ref="orders", worker_id="worker-b")
    coordinator.complete_task(task_ref="orders", worker_id="worker-b", result={"status": "observed"})
    snapshot = coordinator.snapshot(session_ref="session-1")
    assert snapshot["task_counts"]["completed"] == 2
    assert snapshot["authority"]["external_write_allowed"] is False


def test_parallelism_budget_and_idempotency_are_enforced():
    coordinator = _coordinator()
    for task_ref in ("a", "b"):
        coordinator.submit_task(
            session_ref="session-1",
            task_ref=task_ref,
            thread_ref="thread-read",
            agent_id=f"agent-{task_ref}",
            role="reader",
            objective=task_ref,
            idempotency_key=f"key-{task_ref}",
            created_at=T0,
        )
    coordinator.claim_task(task_ref="a", worker_id="worker-a", as_of=T0)
    coordinator.claim_task(task_ref="b", worker_id="worker-b", as_of=T0)
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="c",
        thread_ref="thread-read",
        agent_id="agent-c",
        role="reader",
        objective="c",
        idempotency_key="key-c",
        created_at=T0,
    )
    with pytest.raises(OrchestrationError, match="parallelism"):
        coordinator.claim_task(task_ref="c", worker_id="worker-c")
    replay = coordinator.submit_task(
        session_ref="session-1",
        task_ref="c",
        thread_ref="thread-read",
        agent_id="agent-c",
        role="reader",
        objective="c",
        idempotency_key="key-c",
        created_at=T0,
    )
    assert replay.task_ref == "c"
    with pytest.raises(OrchestrationError, match="idempotency"):
        coordinator.submit_task(
            session_ref="session-1",
            task_ref="other-c",
            thread_ref="thread-read",
            agent_id="agent-c",
            role="reader",
            objective="changed request",
            idempotency_key="key-c",
            created_at=T0,
        )


def test_authority_like_result_is_rejected_and_session_pause_is_fail_closed():
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="safe-task",
        thread_ref="thread-read",
        agent_id="agent-safe",
        role="reader",
        objective="read-only",
        idempotency_key="safe-key",
        created_at=T0,
    )
    coordinator.claim_task(task_ref="safe-task", worker_id="worker-a")
    with pytest.raises(OrchestrationError, match="authority"):
        coordinator.complete_task(task_ref="safe-task", worker_id="worker-a", result={"permit": True})
    coordinator.pause(session_ref="session-1", reason="P0", actor_id="risk-owner")
    snapshot = coordinator.snapshot(session_ref="session-1")
    assert snapshot["state"] == SessionState.PAUSED.value
    with pytest.raises(OrchestrationError, match="active"):
        coordinator.submit_task(
            session_ref="session-1",
            task_ref="blocked",
            thread_ref="thread-read",
            agent_id="agent-blocked",
            role="reader",
            objective="blocked",
            idempotency_key="blocked-key",
            created_at=T0,
        )
    coordinator.resume(session_ref="session-1", actor_id="admin")
    assert coordinator.snapshot(session_ref="session-1")["state"] == SessionState.ACTIVE.value


def test_dependency_cycle_is_rejected():
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="a",
        thread_ref="thread-read",
        agent_id="agent-a",
        role="reader",
        objective="a",
        idempotency_key="cycle-a",
        created_at=T0,
    )
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="b",
        thread_ref="thread-read",
        agent_id="agent-b",
        role="reader",
        objective="b",
        idempotency_key="cycle-b",
        dependencies=("a",),
        created_at=T0,
    )
    with pytest.raises(OrchestrationError, match="cycle"):
        coordinator.submit_task(
            session_ref="session-1",
            task_ref="a2",
            thread_ref="thread-read",
            agent_id="agent-a2",
            role="reader",
            objective="cycle",
            idempotency_key="cycle-a2",
            dependencies=("b", "a2"),
            created_at=T0,
        )


class _ObservationSink:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.calls = 0
        self._records: dict[str, dict[str, str]] = {}

    def record_observation(self, payload: dict, *, principal: object) -> dict:
        self.calls += 1
        replay_key = hashlib.sha256(
            json.dumps(
                {
                    "project_id": payload["project_id"],
                    "verifier_id": payload["verifier_id"],
                    "verifier_version": payload["verifier_version"],
                    "input_sha256": payload["input_sha256"],
                    "artifact_ref": payload["artifact_ref"],
                    "state": payload["state"],
                    "scope": payload["scope"],
                    "principal": {
                        "actor_id": getattr(principal, "actor_id", None),
                        "tenant_ref": getattr(principal, "tenant_ref", None),
                        "roles": sorted(getattr(principal, "roles", ())),
                        "store_refs": sorted(
                            getattr(principal, "store_refs", ())
                        ),
                        "object_identity": (
                            None
                            if getattr(principal, "actor_id", None) is not None
                            else id(principal)
                        ),
                    },
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if replay_key not in self._records:
            self.payloads.append(payload)
            self._records[replay_key] = {
                "id": f"harness-{replay_key[:16]}",
                "state": payload["state"],
            }
        return dict(self._records[replay_key])


class _RevocableObservationSink(_ObservationSink):
    def __init__(self) -> None:
        super().__init__()
        self.authorized = True
        self.attempts = 0

    def record_observation(self, payload: dict, *, principal: object) -> dict:
        self.attempts += 1
        if not self.authorized:
            raise PermissionError("Harness publication authority was revoked")
        return super().record_observation(payload, principal=principal)


class _ScopedCoordinatorFacade:
    requires_durable_scope = True

    def __init__(self, coordinator: TeamAgentCoordinator) -> None:
        self.coordinator = coordinator
        self.calls: list[dict[str, object]] = []

    def restore_session(self, **values: object) -> TeamAgentCoordinator:
        self.calls.append(values)
        return self.coordinator

    def session(self, _session_ref: str):
        raise AssertionError("global session lookup must not be used")


def test_harness_bridge_rejects_unscoped_durable_publication() -> None:
    facade = _ScopedCoordinatorFacade(_coordinator())
    bridge = TeamAgentHarnessBridge(coordinator=facade, sink=_ObservationSink())

    with pytest.raises(OrchestrationError, match="exact scope and authority"):
        bridge.publish_completed(
            session_ref="session-1",
            project_id="project-unscoped",
            verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
            verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
            principal=object(),
        )

    assert facade.calls == []


def test_harness_bridge_projects_only_terminal_tasks_and_is_idempotent():
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="read",
        thread_ref="thread-read",
        agent_id="agent-read",
        role="reader",
        objective="read official facts",
        idempotency_key="read-key",
        created_at=T0,
    )
    coordinator.claim_task(task_ref="read", worker_id="worker")
    coordinator.complete_task(
        task_ref="read",
        worker_id="worker",
        result={"status": "observed"},
        evidence_refs=("evidence-1",),
    )
    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=coordinator, sink=sink)
    principal = object()
    first = bridge.publish_completed(
        session_ref="session-1",
        project_id="project-1",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )
    second = bridge.publish_completed(
        session_ref="session-1",
        project_id="project-1",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )
    assert len(first) == len(second) == 1
    assert len(sink.payloads) == 1
    assert sink.calls == 2
    assert sink.payloads[0]["scope"] == {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "ozon-primary",
        "authority_sha256": "a" * 64,
        "session_ref": "session-1",
        "task_ref": "read",
        "observation_only": True,
        "gate_eligible": False,
    }
    assert sink.payloads[0]["source_type"] == "team_agent_terminal_observation"
    assert sink.payloads[0]["authority"] == "observation"
    assert first[0]["external_write_allowed"] is False


def test_harness_bridge_replay_revalidates_revoked_sink_authority() -> None:
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="revoked-publication",
        thread_ref="thread-read",
        agent_id="agent-read",
        role="reader",
        objective="read official facts",
        idempotency_key="revoked-publication-v1",
        created_at=T0,
    )
    claimed = coordinator.claim_task(
        task_ref="revoked-publication",
        worker_id="worker",
        as_of=T0,
    )
    coordinator.complete_task(
        task_ref="revoked-publication",
        worker_id="worker",
        lease_ref=claimed.lease_ref,
        result={"status": "observed"},
        as_of=T0 + timedelta(seconds=1),
    )
    sink = _RevocableObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=coordinator, sink=sink)
    principal = Principal(
        "monitor-a",
        frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )

    first = bridge.publish_completed(
        session_ref="session-1",
        project_id="project-revocable",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )
    sink.authorized = False

    with pytest.raises(PermissionError, match="revoked"):
        bridge.publish_completed(
            session_ref="session-1",
            project_id="project-revocable",
            verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
            verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
            principal=principal,
        )

    assert len(first) == 1
    assert sink.attempts == 2


def test_harness_bridge_scoped_publish_uses_admitted_durable_session() -> None:
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="scoped-publish",
        thread_ref="thread-read",
        agent_id="agent-reader",
        role="reader",
        objective="read official facts",
        idempotency_key="scoped-publish-v1",
        created_at=T0,
    )
    claimed = coordinator.claim_task(
        task_ref="scoped-publish",
        worker_id="worker",
        as_of=T0,
    )
    coordinator.complete_task(
        task_ref="scoped-publish",
        worker_id="worker",
        lease_ref=claimed.lease_ref,
        result={"status": "observed"},
        as_of=T0,
    )
    facade = _ScopedCoordinatorFacade(coordinator)
    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=facade, sink=sink)

    published = bridge.publish_completed(
        session_ref="session-1",
        project_id="project-scoped",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=object(),
        scope=SCOPE,
        authority_sha256="a" * 64,
    )

    assert len(published) == 1
    assert facade.calls == [
        {
            "scope": SCOPE,
            "session_ref": "session-1",
            "authority_sha256": "a" * 64,
        }
    ]
    assert sink.payloads[0]["scope"] == {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "ozon-primary",
        "authority_sha256": "a" * 64,
        "session_ref": "session-1",
        "task_ref": "scoped-publish",
        "observation_only": True,
        "gate_eligible": False,
    }


def test_harness_bridge_cache_is_scoped_by_project_and_principal() -> None:
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="cache-scope",
        thread_ref="thread-read",
        agent_id="agent-read",
        role="reader",
        objective="read official facts",
        idempotency_key="cache-scope-v1",
        created_at=T0,
    )
    claimed = coordinator.claim_task(
        task_ref="cache-scope",
        worker_id="worker",
    )
    coordinator.complete_task(
        task_ref="cache-scope",
        worker_id="worker",
        lease_ref=claimed.lease_ref,
        result={"status": "observed"},
    )
    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=coordinator, sink=sink)
    principal_a = Principal(
        "monitor-a",
        frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )
    principal_b = Principal(
        "monitor-b",
        frozenset({"monitor"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )

    first = bridge.publish_completed(
        session_ref="session-1",
        project_id="project-1",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal_a,
    )
    second = bridge.publish_completed(
        session_ref="session-1",
        project_id="project-2",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal_b,
    )
    replay = bridge.publish_completed(
        session_ref="session-1",
        project_id="project-2",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal_b,
    )

    assert len(sink.payloads) == 2
    assert [payload["project_id"] for payload in sink.payloads] == [
        "project-1",
        "project-2",
    ]
    assert first[0] != second[0]
    assert replay == second


def test_harness_bridge_publishes_same_project_for_distinct_exact_scopes() -> None:
    coordinator = _coordinator()
    coordinator.create_session(
        session_ref="session-2",
        scope=ExactScope("tenant-b", "entity-b", "ozon-secondary"),
        objective="independent scope",
        owner_id="owner-2",
        max_parallel=2,
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref="session-2",
        thread_ref="thread-read-2",
        title="read facts",
        created_at=T0,
    )
    for session_ref, thread_ref in (("session-1", "thread-read"), ("session-2", "thread-read-2")):
        coordinator.submit_task(
            session_ref=session_ref,
            task_ref=f"{session_ref}-same-task",
            thread_ref=thread_ref,
            agent_id="agent-read",
            role="reader",
            objective="read official facts",
            idempotency_key=f"{session_ref}-same-task-v1",
            created_at=T0,
        )
        claimed = coordinator.claim_task(
            task_ref=f"{session_ref}-same-task",
            worker_id=f"worker-{session_ref}",
            as_of=T0,
        )
        coordinator.complete_task(
            task_ref=f"{session_ref}-same-task",
            worker_id=f"worker-{session_ref}",
            lease_ref=claimed.lease_ref,
            result={"status": "observed"},
            as_of=T0 + timedelta(seconds=1),
        )

    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=coordinator, sink=sink)
    principal = object()
    bridge.publish_completed(
        session_ref="session-1",
        project_id="project-same",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )
    bridge.publish_completed(
        session_ref="session-2",
        project_id="project-same",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )

    assert len(sink.payloads) == 2
    assert {payload["scope"]["entity_ref"] for payload in sink.payloads} == {
        "entity-a",
        "entity-b",
    }


def test_harness_bridge_cache_includes_session_for_same_scope_recovery() -> None:
    def completed_coordinator(session_ref: str) -> TeamAgentCoordinator:
        coordinator = TeamAgentCoordinator()
        coordinator.create_session(
            session_ref=session_ref,
            scope=SCOPE,
            objective="publish a terminal observation",
            owner_id="owner-1",
            created_at=T0,
        )
        coordinator.fork_thread(
            session_ref=session_ref,
            thread_ref=f"{session_ref}:work",
            title="work",
            created_at=T0,
        )
        coordinator.submit_task(
            session_ref=session_ref,
            task_ref="same-task",
            thread_ref=f"{session_ref}:work",
            agent_id="agent-read",
            role="reader",
            objective="read official facts",
            idempotency_key="same-task-v1",
            created_at=T0,
        )
        claimed = coordinator.claim_task(
            task_ref="same-task",
            worker_id="worker",
            as_of=T0,
        )
        coordinator.complete_task(
            task_ref="same-task",
            worker_id="worker",
            lease_ref=claimed.lease_ref,
            result={"status": "observed"},
            as_of=T0 + timedelta(seconds=1),
        )
        return coordinator

    first = completed_coordinator("session-a")
    second = completed_coordinator("session-b")
    assert first.observations(session_ref="session-a")[0].observation_ref == (
        second.observations(session_ref="session-b")[0].observation_ref
    )

    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=first, sink=sink)
    principal = object()
    bridge.publish_completed(
        session_ref="session-a",
        project_id="project-same",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )
    bridge.coordinator = second
    bridge.publish_completed(
        session_ref="session-b",
        project_id="project-same",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )

    assert len(sink.payloads) == 2


def test_harness_bridge_cache_does_not_cross_restored_exact_scope() -> None:
    def completed_coordinator(scope: ExactScope) -> TeamAgentCoordinator:
        coordinator = TeamAgentCoordinator()
        coordinator.create_session(
            session_ref="recovered-session",
            scope=scope,
            objective="publish a terminal observation",
            owner_id="owner-1",
            created_at=T0,
        )
        coordinator.fork_thread(
            session_ref="recovered-session",
            thread_ref="recovered-thread",
            title="read facts",
            created_at=T0,
        )
        coordinator.submit_task(
            session_ref="recovered-session",
            task_ref="recovered-task",
            thread_ref="recovered-thread",
            agent_id="agent-read",
            role="reader",
            objective="read official facts",
            idempotency_key="recovered-task-v1",
            created_at=T0,
        )
        claimed = coordinator.claim_task(
            task_ref="recovered-task",
            worker_id="worker-recovered",
            as_of=T0,
        )
        coordinator.complete_task(
            task_ref="recovered-task",
            worker_id="worker-recovered",
            lease_ref=claimed.lease_ref,
            result={"status": "observed"},
            as_of=T0 + timedelta(seconds=1),
        )
        return coordinator

    first = completed_coordinator(SCOPE)
    second = completed_coordinator(
        ExactScope("tenant-b", "entity-b", "ozon-secondary")
    )
    assert first.observations(session_ref="recovered-session")[0].observation_ref == (
        second.observations(session_ref="recovered-session")[0].observation_ref
    )

    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=first, sink=sink)
    principal = object()
    bridge.publish_completed(
        session_ref="recovered-session",
        project_id="project-recovered",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )
    bridge.coordinator = second
    bridge.publish_completed(
        session_ref="recovered-session",
        project_id="project-recovered",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=principal,
    )

    assert [payload["scope"]["entity_ref"] for payload in sink.payloads] == [
        "entity-a",
        "entity-b",
    ]


def test_harness_bridge_publishes_retry_exhausted_blocked_terminal() -> None:
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="blocked-terminal",
        thread_ref="thread-read",
        agent_id="agent-read",
        role="reader",
        objective="read official facts",
        idempotency_key="blocked-terminal-v1",
        provider_id="provider-a",
        max_attempts=1,
        created_at=T0,
    )
    claimed = coordinator.claim_task(
        task_ref="blocked-terminal",
        worker_id="worker",
    )
    blocked = coordinator.fail_task(
        task_ref="blocked-terminal",
        worker_id="worker",
        lease_ref=claimed.lease_ref,
        failure_code="upstream unavailable",
        status_code=503,
    )
    assert blocked.state is TaskState.BLOCKED
    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=coordinator, sink=sink)

    published = bridge.publish_completed(
        session_ref="session-1",
        project_id="project-1",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=object(),
    )

    assert len(published) == 1
    assert sink.payloads[0]["state"] == "blocked"
    assert "blocked" in sink.payloads[0]["summary"]


def test_harness_bridge_publishes_preclaim_time_budget_blocked_terminal() -> None:
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref="budget-session",
        scope=SCOPE,
        objective="budget terminal",
        owner_id="owner-1",
        max_parallel=2,
        time_budget_seconds=10,
        created_at=T0,
    )
    coordinator.fork_thread(
        session_ref="budget-session",
        thread_ref="budget-session:work",
        title="work",
        created_at=T0,
    )
    coordinator.submit_task(
        session_ref="budget-session",
        task_ref="budget-task",
        thread_ref="budget-session:work",
        agent_id="agent-budget",
        role="reader",
        objective="budget terminal",
        idempotency_key="budget-task-v1",
        created_at=T0,
    )
    with pytest.raises(OrchestrationError, match="time budget"):
        coordinator.claim_task(
            task_ref="budget-task",
            worker_id="worker-budget",
            as_of=T0 + timedelta(seconds=10),
        )

    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=coordinator, sink=sink)
    published = bridge.publish_completed(
        session_ref="budget-session",
        project_id="project-budget",
        verifier_id=TEAM_AGENT_HARNESS_VERIFIER_ID,
        verifier_version=TEAM_AGENT_HARNESS_VERIFIER_VERSION,
        principal=object(),
    )

    assert len(published) == 1
    assert sink.payloads[0]["state"] == "blocked"
    assert "blocked" in sink.payloads[0]["summary"]


def test_harness_bridge_rejects_caller_selected_verifier():
    coordinator = _coordinator()
    sink = _ObservationSink()
    bridge = TeamAgentHarnessBridge(coordinator=coordinator, sink=sink)

    with pytest.raises(
        OrchestrationError,
        match="fixed observation-only verifier",
    ):
        bridge.publish_completed(
            session_ref="session-1",
            project_id="project-1",
            verifier_id="canonical-business-fact",
            verifier_version="99",
            principal=object(),
        )


def test_multiple_sessions_isolate_idempotency_and_event_cursors():
    coordinator = _coordinator()
    coordinator.create_session(
        session_ref="session-2",
        scope=ExactScope("tenant-b", "entity-b", "ozon-secondary"),
        objective="independent store facts",
        owner_id="owner-2",
        created_at=T0,
    )
    for session_ref in ("session-1", "session-2"):
        coordinator.submit_task(
            session_ref=session_ref,
            task_ref=f"{session_ref}-catalog",
            thread_ref=f"{session_ref}:root",
            agent_id="catalog-agent",
            role="reader",
            objective="read catalog",
            idempotency_key="same-caller-key",
            created_at=T0,
        )
    session_1_events = coordinator.events(session_ref="session-1")
    session_2_events = coordinator.events(session_ref="session-2")
    assert [event["event_type"] for event in session_1_events] == [
        "session.created",
        "thread.forked",
        "task.submitted",
    ]
    assert [event["event_type"] for event in session_2_events] == [
        "session.created",
        "task.submitted",
    ]
    assert all(event["session_ref"] == "session-1" for event in session_1_events)
    assert all(event["session_ref"] == "session-2" for event in session_2_events)
    cursor = session_1_events[0]["cursor"]
    with pytest.raises(OrchestrationError, match="scope"):
        coordinator.events(after_cursor=cursor, session_ref="session-2")


def test_completion_requires_live_exact_lease_and_rejects_secret_values():
    coordinator = _coordinator()
    started = T0
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="leased",
        thread_ref="thread-read",
        agent_id="reader-agent",
        role="reader",
        objective="read safely",
        idempotency_key="leased-v1",
        created_at=T0,
    )
    claimed = coordinator.claim_task(
        task_ref="leased",
        worker_id="worker-a",
        lease_seconds=10,
        as_of=started,
    )
    assert claimed.lease_ref
    with pytest.raises(OrchestrationError, match="expired"):
        coordinator.complete_task(
            task_ref="leased",
            worker_id="worker-a",
            result={"status": "observed"},
            as_of=started + timedelta(seconds=10),
        )
    reclaimed = coordinator.claim_task(task_ref="leased", worker_id="worker-a")
    with pytest.raises(OrchestrationError, match="sensitive"):
        coordinator.complete_task(
            task_ref="leased",
            worker_id="worker-a",
            lease_ref=reclaimed.lease_ref,
            result={"message": "Authorization: Bearer abcdefghijklmnop"},
        )


def test_checkpoint_restore_and_event_merge_keep_session_chains_independent():
    coordinator = _coordinator()
    coordinator.create_session(
        session_ref="session-2",
        scope=ExactScope("tenant-b", "entity-b", "ozon-secondary"),
        objective="independent store facts",
        owner_id="owner-2",
        created_at=T0,
    )
    restored = TeamAgentCoordinator.restore(coordinator.checkpoint())
    assert restored.snapshot(session_ref="session-1")["scope"]["tenant_ref"] == "tenant-a"
    assert restored.snapshot(session_ref="session-2")["scope"]["tenant_ref"] == "tenant-b"

    receiver = TeamAgentCoordinator()
    first_session_events = coordinator.events(session_ref="session-1")
    assert receiver.merge_events(first_session_events).status == "merged"
    second_session_events = coordinator.events(session_ref="session-2")
    assert receiver.merge_events(second_session_events).status == "merged"


def test_kill_switch_revokes_active_leases_and_stops_new_work():
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="running",
        thread_ref="thread-read",
        agent_id="reader-agent",
        role="reader",
        objective="read current facts",
        idempotency_key="running-v1",
        created_at=T0,
    )
    coordinator.claim_task(task_ref="running", worker_id="worker-a")
    coordinator.engage_kill_switch(
        session_ref="session-1",
        reason="P0 incident",
        actor_id="risk-owner",
    )
    snapshot = coordinator.snapshot(session_ref="session-1")
    assert snapshot["state"] == SessionState.CLOSED.value
    assert snapshot["active_leases"] == []
    assert snapshot["task_counts"][TaskState.EXPIRED.value] == 1
    with pytest.raises(OrchestrationError, match="active"):
        coordinator.claim_task(task_ref="running", worker_id="worker-a")


def test_blocked_expiry_roundtrips_checkpoint_without_expired_at():
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="blocked-expiry",
        thread_ref="thread-read",
        agent_id="reader-agent",
        role="reader",
        objective="read current facts",
        idempotency_key="blocked-expiry-v1",
        provider_id="provider-a",
        max_attempts=1,
        created_at=T0,
    )
    coordinator.claim_task(
        task_ref="blocked-expiry",
        worker_id="worker-a",
        lease_seconds=30,
        as_of=T0,
    )
    blocked = coordinator.expire_task(
        task_ref="blocked-expiry",
        as_of=T0 + timedelta(seconds=30),
    )
    assert blocked.state is TaskState.BLOCKED
    assert blocked.expired_at is None

    restored = TeamAgentCoordinator.restore(
        coordinator.checkpoint(session_ref="session-1"),
        scope=SCOPE,
    )
    restored_task = restored.task("blocked-expiry")
    assert restored_task.state is TaskState.BLOCKED
    assert restored_task.expired_at is None


def test_checkpoint_rejects_running_task_without_its_active_lease():
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="running",
        thread_ref="thread-read",
        agent_id="reader-agent",
        role="reader",
        objective="read current facts",
        idempotency_key="checkpoint-running-v1",
        created_at=T0,
    )
    coordinator.claim_task(task_ref="running", worker_id="worker-a")
    checkpoint = coordinator.checkpoint(session_ref="session-1")
    checkpoint["leases"] = []
    checkpoint.pop("checkpoint_sha256")
    checkpoint["checkpoint_sha256"] = hashlib.sha256(
        json.dumps(
            checkpoint,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()
    with pytest.raises(OrchestrationError, match="lease conflict"):
        TeamAgentCoordinator.restore(checkpoint)


def test_provider_and_trace_aliases_cannot_rebind_a_submitted_task():
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="provider-bound",
        thread_ref="thread-read",
        agent_id="reader-agent",
        role="reader",
        objective="read safely",
        idempotency_key="provider-bound-v1",
        provider_id="provider-a",
        trace_id="trace-a",
        created_at=T0,
    )
    with pytest.raises(OrchestrationError, match="provider_id and provider_ref conflict"):
        coordinator.claim_task(
            task_ref="provider-bound",
            worker_id="worker-a",
            provider_id="provider-a",
            provider_ref="provider-b",
        )
    with pytest.raises(OrchestrationError, match="provider association"):
        coordinator.claim_task(
            task_ref="provider-bound",
            worker_id="worker-a",
            provider_id="provider-b",
        )
    with pytest.raises(OrchestrationError, match="trace association"):
        coordinator.claim_task(
            task_ref="provider-bound",
            worker_id="worker-a",
            trace_id="trace-b",
        )
    claimed = coordinator.claim_task(
        task_ref="provider-bound",
        worker_id="worker-a",
        provider_ref="provider-a",
        trace_id="trace-a",
    )
    assert claimed.provider_id == "provider-a"
    with pytest.raises(OrchestrationError, match="provider_id and provider_ref conflict"):
        coordinator.breaker_state(
            session_ref="session-1",
            provider_id="provider-a",
            provider_ref="provider-b",
        )


def test_retry_after_backoff_and_half_open_breaker_are_bounded_and_deterministic():
    coordinator = TeamAgentCoordinator(
        retry_base_seconds=1,
        retry_max_seconds=30,
        breaker_failure_threshold=3,
        breaker_cooldown_seconds=60,
    )
    started = T0
    coordinator.create_session(
        session_ref="retry-session",
        scope=SCOPE,
        objective="retry provider work",
        owner_id="owner-1",
        created_at=T0,
    )
    for index in range(4):
        coordinator.submit_task(
            session_ref="retry-session",
            task_ref=f"retry-{index}",
            thread_ref="retry-session:root",
            agent_id=f"reader-agent-{index}",
            role="reader",
                objective="read provider",
                idempotency_key=f"retry-{index}",
                provider_id="provider-a",
                created_at=started,
            )

    first = coordinator.claim_task(
        task_ref="retry-0", worker_id="worker-a", as_of=started
    )
    first_failed = coordinator.fail_task(
        task_ref=first.task_ref,
        worker_id="worker-a",
        lease_ref=first.lease_ref,
        failure_code="429",
        status_code=429,
        retry_after="7",
        as_of=started,
    )
    assert first_failed.state is TaskState.RETRY_WAIT
    assert first_failed.retry_after_seconds == 7
    assert first_failed.retry_wait_until == started + timedelta(seconds=7)
    assert coordinator.tick(as_of=started + timedelta(seconds=6))["retry_ready_tasks"] == []
    assert coordinator.tick(as_of=started + timedelta(seconds=7))["retry_ready_tasks"] == ["retry-0"]

    # Independent failures on the same provider/session open one shared breaker.
    for index in (1, 2):
        claimed = coordinator.claim_task(
            task_ref=f"retry-{index}",
            worker_id="worker-a",
            as_of=started + timedelta(seconds=7),
        )
        coordinator.fail_task(
            task_ref=claimed.task_ref,
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            failure_code="upstream unavailable",
            status_code=503,
            as_of=started + timedelta(seconds=7),
        )
    assert coordinator.breaker_state(
        session_ref="retry-session", provider_id="provider-a"
    )["state"] == "open"
    with pytest.raises(OrchestrationError, match="circuit breaker is open"):
        coordinator.claim_task(
            task_ref="retry-3",
            worker_id="worker-b",
            as_of=started + timedelta(seconds=7),
        )
    tick = coordinator.tick(as_of=started + timedelta(seconds=67))
    assert tick["circuit_breakers"]["retry-session|provider-a"]["state"] == "half_open"
    probe = coordinator.claim_task(
        task_ref="retry-3",
        worker_id="worker-b",
        as_of=started + timedelta(seconds=67),
    )
    assert probe.state is TaskState.RUNNING
    with pytest.raises(OrchestrationError, match="probe is already active"):
        coordinator.claim_task(
            task_ref="retry-0",
            worker_id="worker-c",
            as_of=started + timedelta(seconds=67),
        )


def test_exact_scope_and_completion_boundaries_reject_untrusted_input():
    coordinator = TeamAgentCoordinator()
    with pytest.raises(OrchestrationError, match="ExactScope"):
        coordinator.create_session(
            session_ref="invalid-scope",
            scope={"tenant_ref": "tenant-a"},  # type: ignore[arg-type]
            objective="invalid",
            owner_id="owner",
        )

    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="reviewed",
        thread_ref="thread-read",
        agent_id="author-agent",
        role="author",
        objective="produce reviewable result",
        idempotency_key="reviewed-v1",
        evidence_required=True,
        reviewer_role="independent-reviewer",
        created_at=T0,
    )
    claimed = coordinator.claim_task(task_ref="reviewed", worker_id="worker-a")
    with pytest.raises(OrchestrationError, match="Evidence"):
        coordinator.complete_task(
            task_ref="reviewed",
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            result={"status": "observed"},
        )
    with pytest.raises(OrchestrationError, match="independent reviewer"):
        coordinator.complete_task(
            task_ref="reviewed",
            worker_id="worker-a",
            lease_ref=claimed.lease_ref,
            evidence_refs=("ev-reviewed",),
            reviewer_id="author-agent",
            result={"status": "observed"},
        )
    completed = coordinator.complete_task(
        task_ref="reviewed",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        evidence_refs=("ev-reviewed",),
        reviewer_id="reviewer-agent",
        result={"nested": [{"status": "observed"}]},
    )
    assert completed.state is TaskState.COMPLETED


def test_event_merge_is_repeatable_but_tampered_or_cross_scope_streams_conflict():
    sender = _coordinator()
    receiver = TeamAgentCoordinator()
    stream = sender.events(session_ref="session-1")
    first = receiver.merge_events(stream, expected_scope=SCOPE)
    assert first.status == "merged"
    replay = receiver.merge_events(stream, expected_scope=SCOPE)
    assert replay.status == "merged"
    assert len(replay) == len(stream)

    tampered = [dict(event) for event in stream]
    tampered[-1] = {**tampered[-1], "payload": {"title": "tampered"}}
    conflict = receiver.merge_events(tampered, expected_scope=SCOPE)
    assert conflict.status == "conflict"
    assert "event hash conflict" in conflict.conflicts
    assert receiver.conflict_count == 1


def test_provider_bucket_single_agent_quota_and_nested_authority_are_fail_closed():
    coordinator = TeamAgentCoordinator(
        max_active_per_agent=1,
        provider_buckets={"provider-a": 1},
    )
    coordinator.create_session(
        session_ref="quota-session",
        scope=SCOPE,
        objective="bounded concurrency",
        owner_id="owner-1",
        max_parallel=3,
        created_at=T0,
    )
    for task_ref, agent_id, provider_id in (
        ("first", "agent-a", "provider-a"),
        ("same-provider", "agent-b", "provider-a"),
        ("same-agent", "agent-a", "provider-b"),
    ):
        coordinator.submit_task(
            session_ref="quota-session",
            task_ref=task_ref,
            thread_ref="quota-session:root",
            agent_id=agent_id,
            role="reader",
            objective="read-only",
            idempotency_key=task_ref,
            provider_id=provider_id,
            created_at=T0,
        )
    first = coordinator.claim_task(task_ref="first", worker_id="worker-a")
    with pytest.raises(OrchestrationError, match="provider bucket"):
        coordinator.claim_task(task_ref="same-provider", worker_id="worker-b")
    with pytest.raises(OrchestrationError, match="single agent"):
        coordinator.claim_task(task_ref="same-agent", worker_id="worker-c")
    with pytest.raises(OrchestrationError, match="authority"):
        coordinator.complete_task(
            task_ref="first",
            worker_id="worker-a",
            lease_ref=first.lease_ref,
            result={"nested": {"permit": True}},
        )


def test_handoff_preserves_lineage_evidence_contract_and_trace():
    coordinator = _coordinator()
    source = coordinator.submit_task(
        session_ref="session-1",
        task_ref="source",
        thread_ref="thread-read",
        agent_id="author-agent",
        role="author",
        objective="prepare evidence",
        idempotency_key="source-v1",
        trace_id="trace-handoff",
        evidence_required=True,
        created_at=T0,
    )
    child = coordinator.fork_thread(
        session_ref="session-1",
        thread_ref="thread-review",
        title="independent review",
        parent_thread_ref="thread-read",
        parent_task_ref=source.task_ref,
        created_at=T0,
    )
    claimed = coordinator.claim_task(
        task_ref=source.task_ref,
        worker_id="worker-a",
        as_of=T0,
    )
    coordinator.complete_task(
        task_ref=source.task_ref,
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        evidence_refs=("ev-source",),
        result={"status": "observed"},
        as_of=T0 + timedelta(seconds=1),
    )
    handoff = coordinator.handoff_task(
        session_ref="session-1",
        source_task_ref=source.task_ref,
        source_thread_ref="thread-read",
        target_thread_ref=child.thread_ref,
        target_role="independent-reviewer",
        input_evidence_refs=("ev-source",),
        acceptance_contract={"acceptance": "verify evidence"},
        created_at=T0 + timedelta(seconds=1),
        trace_id="trace-handoff",
    )
    received = coordinator.submit_task(
        session_ref="session-1",
        task_ref="review",
        thread_ref=child.thread_ref,
        agent_id="reviewer-agent",
        role="independent-reviewer",
        objective="review evidence",
        idempotency_key="review-v1",
        parent_task_ref=source.task_ref,
        handoff_ref=handoff.handoff_ref,
        trace_id="trace-handoff",
        evidence_refs=("ev-source",),
        acceptance_contract={"acceptance": "verify evidence"},
        created_at=T0 + timedelta(seconds=2),
    )
    assert received.handoff_ref == handoff.handoff_ref
    with pytest.raises(OrchestrationError, match="handoff trace conflict"):
        coordinator.submit_task(
            session_ref="session-1",
            task_ref="review-bad-trace",
            thread_ref=child.thread_ref,
            agent_id="reviewer-agent-2",
            role="independent-reviewer",
            objective="review evidence",
            idempotency_key="review-bad-trace-v1",
            parent_task_ref=source.task_ref,
            handoff_ref=handoff.handoff_ref,
            trace_id="other-trace",
            evidence_refs=("ev-source",),
            acceptance_contract={"acceptance": "verify evidence"},
            created_at=T0 + timedelta(seconds=2),
        )


def test_heartbeat_and_release_keep_lease_fencing_and_reentry_safe():
    coordinator = _coordinator()
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="renewable",
        thread_ref="thread-read",
        agent_id="reader-agent",
        role="reader",
        objective="read safely",
        idempotency_key="renewable-v1",
        created_at=T0,
    )
    started = datetime(2026, 8, 19, tzinfo=UTC)
    claimed = coordinator.claim_task(
        task_ref="renewable",
        worker_id="worker-a",
        lease_seconds=5,
        as_of=started,
    )
    renewed = coordinator.heartbeat_task(
        task_ref="renewable",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        extend_seconds=5,
        as_of=started + timedelta(seconds=4),
    )
    assert renewed.lease_expires_at == started + timedelta(seconds=9)
    with pytest.raises(OrchestrationError, match="lease_id"):
        coordinator.release_task(
            task_ref="renewable",
            worker_id="worker-a",
            lease_ref="wrong-lease",
            as_of=started + timedelta(seconds=5),
        )
    released = coordinator.release_task(
        task_ref="renewable",
        worker_id="worker-a",
        lease_ref=claimed.lease_ref,
        as_of=started + timedelta(seconds=5),
    )
    assert released.state is TaskState.QUEUED
    reclaimed = coordinator.claim_task(
        task_ref="renewable",
        worker_id="worker-b",
        as_of=started + timedelta(seconds=5),
    )
    assert reclaimed.attempt_count == 2


def test_event_sequence_gap_is_conflict_and_does_not_partially_apply():
    sender = _coordinator()
    receiver = TeamAgentCoordinator()
    stream = list(sender.events(session_ref="session-1"))
    gap = receiver.merge_events(stream[1:], expected_scope=SCOPE)
    assert gap.status == "conflict"
    assert "event sequence gap" in gap.conflicts
    assert receiver.events() == ()
