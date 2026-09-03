from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.control_plane.agent_team_orchestration import (
    OrchestrationReplayConflict,
    TeamAgentCoordinator,
)
from apps.control_plane.enterprise_control import ExactScope
from apps.control_plane.routers import agent_control
from apps.control_plane.security import Principal
from apps.control_plane.team_agent_persistence import (
    TeamAgentPersistenceConflict,
    TeamAgentTransactionConflict,
)
from apps.control_plane.team_agent_reviewer_authority import (
    CONTRACT_ID as TEAM_AGENT_REVIEWER_CONTRACT_ID,
)
from apps.control_plane.team_agent_reviewer_authority import TeamAgentReviewerAttestation


class _CurrentAuthority:
    def __init__(self, authority_sha256: str) -> None:
        self.authority_sha256 = authority_sha256

    def current(self, **_: object) -> dict[str, str]:
        return {
            "status": "ready",
            "entity_ref": "entity-a",
            "authority_sha256": self.authority_sha256,
        }


def _principal() -> Principal:
    return Principal(
        actor_id="worker-a",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=frozenset({"ozon-primary"}),
    )


def test_worker_identity_is_bound_to_authenticated_actor():
    assert (
        agent_control._assert_worker_identity(
            worker_id="worker-a",
            principal=_principal(),
        )
        == "worker-a"
    )
    with pytest.raises(HTTPException) as raised:
        agent_control._assert_worker_identity(
            worker_id="worker-b",
            principal=_principal(),
        )
    assert raised.value.status_code == 403


def test_session_access_revalidates_current_authority(monkeypatch: pytest.MonkeyPatch):
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref="session-1",
        scope=ExactScope("tenant-a", "entity-a", "ozon-primary"),
        objective="read current facts",
        owner_id="worker-a",
        authority_sha256="a" * 64,
    )
    monkeypatch.setattr(agent_control.runtime, "agent_team", coordinator)
    monkeypatch.setattr(
        agent_control.runtime,
        "scope_grants",
        _CurrentAuthority("b" * 64),
    )

    with pytest.raises(HTTPException) as raised:
        agent_control._team_session_for_principal(
            "session-1",
            principal=_principal(),
            store_ref="ozon-primary",
        )
    assert raised.value.status_code == 409
    assert raised.value.detail == "TeamAgent session authority is stale"


class _LeaseCapturingCoordinator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def claim_task(self, **values: object) -> dict[str, object]:
        self.calls.append(("claim", values))
        return values

    def heartbeat_task(self, **values: object) -> dict[str, object]:
        self.calls.append(("heartbeat", values))
        return values

    def release_task(self, **values: object) -> dict[str, object]:
        self.calls.append(("release", values))
        return values

    def complete_task(self, **values: object) -> dict[str, object]:
        self.calls.append(("complete", values))
        return values

    def fail_task(self, **values: object) -> dict[str, object]:
        self.calls.append(("fail", values))
        return values


class _DurableSessionRuntime:
    requires_durable_scope = True

    def __init__(self, coordinator: TeamAgentCoordinator) -> None:
        self.coordinator = coordinator
        self.calls: list[dict[str, object]] = []
        self.recovery_calls: list[dict[str, object]] = []

    def restore_session(self, **values: object) -> TeamAgentCoordinator:
        self.calls.append(values)
        return self.coordinator

    def recover_session(self, **values: object) -> TeamAgentCoordinator:
        self.recovery_calls.append(values)
        return self.coordinator


def test_session_access_restores_durable_state_in_current_exact_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = TeamAgentCoordinator()
    coordinator.create_session(
        session_ref="session-durable",
        scope=ExactScope("tenant-a", "entity-a", "ozon-primary"),
        objective="read current facts",
        owner_id="worker-a",
        authority_sha256="a" * 64,
    )
    durable = _DurableSessionRuntime(coordinator)
    monkeypatch.setattr(agent_control.runtime, "agent_team", durable)
    monkeypatch.setattr(
        agent_control.runtime,
        "scope_grants",
        _CurrentAuthority("a" * 64),
    )

    session = agent_control._team_session_for_principal(
        "session-durable",
        principal=_principal(),
        store_ref="ozon-primary",
    )

    assert session.session_ref == "session-durable"
    assert durable.calls == [
        {
            "scope": ExactScope("tenant-a", "entity-a", "ozon-primary"),
            "session_ref": "session-durable",
            "authority_sha256": "a" * 64,
        }
    ]
    assert durable.recovery_calls == []


def test_mutation_admission_explicitly_uses_write_authorized_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = TeamAgentCoordinator()
    scope = ExactScope("tenant-a", "entity-a", "ozon-primary")
    coordinator.create_session(
        session_ref="session-durable",
        scope=scope,
        objective="recover before mutation",
        owner_id="worker-a",
        authority_sha256="a" * 64,
    )
    durable = _DurableSessionRuntime(coordinator)
    monkeypatch.setattr(agent_control.runtime, "agent_team", durable)
    monkeypatch.setattr(
        agent_control.runtime,
        "scope_grants",
        _CurrentAuthority("a" * 64),
    )

    agent_control._team_session_for_principal(
        "session-durable",
        principal=_principal(),
        store_ref="ozon-primary",
        recover_expired_leases=True,
    )

    assert durable.calls == []
    assert durable.recovery_calls == [
        {
            "scope": scope,
            "session_ref": "session-durable",
            "authority_sha256": "a" * 64,
        }
    ]


def test_router_mutations_forward_the_exact_lease_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = _LeaseCapturingCoordinator()
    monkeypatch.setattr(agent_control.runtime, "agent_team", coordinator)
    monkeypatch.setattr(
        agent_control,
        "_team_session_for_principal",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        agent_control,
        "_team_task_for_session",
        lambda *_args, **_kwargs: object(),
    )
    principal = _principal()

    agent_control.claim_team_agent_task(
        "session-1",
        "task-1",
        agent_control.TeamTaskClaimInput(
            worker_id="worker-a",
            lease_seconds=30,
            lease_ref="lease-claim",
        ),
        principal,
    )
    agent_control.heartbeat_team_agent_task(
        "session-1",
        "task-1",
        agent_control.TeamTaskHeartbeatInput(
            worker_id="worker-a",
            lease_seconds=30,
            lease_ref="lease-active",
        ),
        principal,
    )
    agent_control.release_team_agent_task(
        "session-1",
        "task-1",
        agent_control.TeamTaskReleaseInput(
            worker_id="worker-a",
            lease_ref="lease-active",
        ),
        principal,
    )
    agent_control.complete_team_agent_task(
        "session-1",
        "task-1",
        agent_control.TeamTaskCompleteInput(
            worker_id="worker-a",
            lease_ref="lease-active",
            result={"status": "done"},
        ),
        principal,
    )
    agent_control.fail_team_agent_task(
        "session-1",
        "task-1",
        agent_control.TeamTaskFailInput(
            worker_id="worker-a",
            lease_ref="lease-active",
            failure_code="timeout",
        ),
        principal,
    )

    assert coordinator.calls == [
        (
            "claim",
            {
                "task_ref": "task-1",
                "worker_id": "worker-a",
                "lease_seconds": 30,
                "lease_id": "lease-claim",
            },
        ),
        (
            "heartbeat",
            {
                "task_ref": "task-1",
                "worker_id": "worker-a",
                "lease_seconds": 30,
                "lease_ref": "lease-active",
            },
        ),
        (
            "release",
            {
                "task_ref": "task-1",
                "worker_id": "worker-a",
                "lease_ref": "lease-active",
            },
        ),
        (
            "complete",
            {
                "task_ref": "task-1",
                "worker_id": "worker-a",
                "lease_ref": "lease-active",
                "result": {"status": "done"},
                "evidence_refs": (),
                "reviewer_id": None,
                "cost_units": 0,
            },
        ),
        (
            "fail",
            {
                "task_ref": "task-1",
                "worker_id": "worker-a",
                "lease_ref": "lease-active",
                "failure_code": "timeout",
                "status_code": None,
                "timeout": False,
                "retry_after_seconds": None,
            },
        ),
    ]


@pytest.mark.parametrize(
    ("task_reviewer_id", "task_reviewer_role", "requested_reviewer_id"),
    [
        (None, "independent_reviewer", "reviewer-a"),
        ("reviewer-a", None, None),
        (None, None, "reviewer-a"),
    ],
)
def test_completion_rejects_unverified_reviewer_identity_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
    task_reviewer_id: str | None,
    task_reviewer_role: str | None,
    requested_reviewer_id: str | None,
) -> None:
    coordinator = _LeaseCapturingCoordinator()
    monkeypatch.setattr(agent_control.runtime, "agent_team", coordinator)
    monkeypatch.setattr(
        agent_control,
        "_team_session_for_principal",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        agent_control,
        "_team_task_for_session",
        lambda *_args, **_kwargs: SimpleNamespace(
            reviewer_id=task_reviewer_id,
            reviewer_role=task_reviewer_role,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        agent_control.complete_team_agent_task(
            "session-1",
            "task-1",
            agent_control.TeamTaskCompleteInput(
                worker_id="worker-a",
                lease_ref="lease-active",
                result={"status": "done"},
                reviewer_id=requested_reviewer_id,
            ),
            _principal(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "team_agent_reviewer_authority_unavailable",
        "message": (
            "independent reviewer completion requires a server-verified "
            "reviewer appointment"
        ),
        "retryable": False,
    }
    assert coordinator.calls == []


def test_completion_admits_exact_scoped_server_verified_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = ExactScope("tenant-a", "entity-a", "ozon-primary")
    session = SimpleNamespace(
        scope=scope,
        authority_sha256="a" * 64,
        session_ref="session-1",
    )
    task = SimpleNamespace(
        task_ref="task-1",
        session_ref="session-1",
        agent_id="author-agent",
        reviewer_id=None,
        reviewer_role="independent_reviewer",
    )
    coordinator = _LeaseCapturingCoordinator()
    authority_calls: list[dict[str, object]] = []

    class _ReviewerAuthority:
        def admit(self, **values: object) -> TeamAgentReviewerAttestation:
            authority_calls.append(values)
            return TeamAgentReviewerAttestation(
                contract_id=TEAM_AGENT_REVIEWER_CONTRACT_ID,
                scope=scope,
                session_ref="session-1",
                task_ref="task-1",
                reviewer_id="reviewer-a",
                reviewer_role="independent_reviewer",
                appointment_evidence_ref="evidence-reviewer-appointment-a",
                authority_sha256="a" * 64,
            )

    monkeypatch.setattr(agent_control.runtime, "agent_team", coordinator)
    monkeypatch.setattr(
        agent_control.runtime,
        "agent_team_reviewer_authority",
        _ReviewerAuthority(),
    )
    monkeypatch.setattr(
        agent_control,
        "_team_session_for_principal",
        lambda *_args, **_kwargs: session,
    )
    monkeypatch.setattr(
        agent_control,
        "_team_task_for_session",
        lambda *_args, **_kwargs: task,
    )

    result = agent_control.complete_team_agent_task(
        "session-1",
        "task-1",
        agent_control.TeamTaskCompleteInput(
            worker_id="worker-a",
            lease_ref="lease-active",
            result={"status": "done"},
            evidence_refs=("evidence-result-a",),
            reviewer_id="reviewer-a",
        ),
        _principal(),
    )

    assert result["reviewer_id"] == "reviewer-a"
    assert authority_calls == [
        {
            "scope": scope,
            "authority_sha256": "a" * 64,
            "session_ref": "session-1",
            "task_ref": "task-1",
            "reviewer_role": "independent_reviewer",
            "requested_reviewer_id": "reviewer-a",
            "principal": _principal(),
        }
    ]
    assert coordinator.calls == [
        (
            "complete",
            {
                "task_ref": "task-1",
                "worker_id": "worker-a",
                "lease_ref": "lease-active",
                "result": {"status": "done"},
                "evidence_refs": (
                    "evidence-result-a",
                    "evidence-reviewer-appointment-a",
                ),
                "reviewer_id": "reviewer-a",
                "cost_units": 0,
            },
        )
    ]


class _DurableFacade:
    requires_durable_scope = True

    def __init__(self, coordinator: TeamAgentCoordinator) -> None:
        self.coordinator = coordinator
        self.calls: list[tuple[str, dict[str, object]]] = []

    def restore_session(self, **values: object) -> TeamAgentCoordinator:
        self.calls.append(("restore", values))
        return self.coordinator

    def task_for_session(self, **values: object):
        self.calls.append(("task", values))
        return self.coordinator.task(str(values["task_ref"]))

    def snapshot(self, **values: object) -> dict[str, object]:
        self.calls.append(("snapshot", values))
        return {"status": "ready"}

    def handoff_task(self, **values: object) -> dict[str, object]:
        self.calls.append(("handoff", values))
        return values


def test_durable_router_reads_use_current_exact_scope_and_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = TeamAgentCoordinator()
    scope = ExactScope("tenant-a", "entity-a", "ozon-primary")
    coordinator.create_session(
        session_ref="session-1",
        scope=scope,
        objective="durable exact scope",
        owner_id="worker-a",
        authority_sha256="a" * 64,
    )
    coordinator.submit_task(
        session_ref="session-1",
        task_ref="task-1",
        thread_ref="session-1:root",
        agent_id="agent-a",
        role="reader",
        objective="read",
        idempotency_key="task-1-v1",
    )
    durable = _DurableFacade(coordinator)
    monkeypatch.setattr(agent_control.runtime, "agent_team", durable)
    monkeypatch.setattr(
        agent_control.runtime,
        "scope_grants",
        _CurrentAuthority("a" * 64),
    )

    session = agent_control._team_session_for_principal(
        "session-1",
        principal=_principal(),
        store_ref="ozon-primary",
    )
    task = agent_control._team_task_for_session(
        "task-1",
        "session-1",
        session=session,
    )
    snapshot = agent_control.team_agent_session_snapshot(
        "session-1",
        _principal(),
    )

    assert task.task_ref == "task-1"
    assert snapshot == {"status": "ready"}
    assert durable.calls == [
        (
            "restore",
            {
                "scope": scope,
                "session_ref": "session-1",
                "authority_sha256": "a" * 64,
            },
        ),
        (
            "task",
            {
                "scope": scope,
                "session_ref": "session-1",
                "authority_sha256": "a" * 64,
                "task_ref": "task-1",
            },
        ),
        (
            "restore",
            {
                "scope": scope,
                "session_ref": "session-1",
                "authority_sha256": "a" * 64,
            },
        ),
        (
            "snapshot",
            {
                "session_ref": "session-1",
                "scope": scope,
                "authority_sha256": "a" * 64,
            },
        ),
    ]


def test_durable_handoff_route_forwards_admitted_scope_and_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = TeamAgentCoordinator()
    scope = ExactScope("tenant-a", "entity-a", "ozon-primary")
    coordinator.create_session(
        session_ref="session-1",
        scope=scope,
        objective="durable handoff",
        owner_id="worker-a",
        authority_sha256="a" * 64,
    )
    session = coordinator.session("session-1")
    durable = _DurableFacade(coordinator)
    monkeypatch.setattr(agent_control.runtime, "agent_team", durable)
    monkeypatch.setattr(
        agent_control,
        "_team_session_for_principal",
        lambda *_args, **_kwargs: session,
    )
    monkeypatch.setattr(
        agent_control,
        "_team_task_for_session",
        lambda *_args, **_kwargs: object(),
    )

    result = agent_control.create_team_agent_handoff(
        "session-1",
        agent_control.TeamHandoffInput(
            source_task_ref="source-task",
            source_thread_ref="session-1:root",
            target_thread_ref="session-1:review",
            target_role="independent_reviewer",
            input_evidence_refs=("evidence-source",),
            acceptance_contract={"decision": "accept_or_reject"},
            trace_id="trace-source",
        ),
        _principal(),
    )

    assert result["source_task_ref"] == "source-task"
    assert durable.calls == [
        (
            "handoff",
            {
                "session_ref": "session-1",
                "source_task_ref": "source-task",
                "source_thread_ref": "session-1:root",
                "target_thread_ref": "session-1:review",
                "target_role": "independent_reviewer",
                "input_evidence_refs": ("evidence-source",),
                "acceptance_contract": {"decision": "accept_or_reject"},
                "trace_id": "trace-source",
                "scope": scope,
                "authority_sha256": "a" * 64,
            },
        )
    ]


def test_durable_mutation_conflict_is_a_stable_client_error() -> None:
    def conflict() -> None:
        raise TeamAgentPersistenceConflict("durable revision conflict")

    with pytest.raises(HTTPException) as exc_info:
        agent_control.run(conflict)

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "durable revision conflict"


def test_aborted_database_transaction_is_a_structured_retryable_conflict() -> None:
    def conflict() -> None:
        raise TeamAgentTransactionConflict(sqlstate="40P01")

    with pytest.raises(HTTPException) as exc_info:
        agent_control.run(conflict)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "team_agent_transaction_conflict",
        "message": "TeamAgent session transaction must be retried after restore",
        "sqlstate": "40P01",
        "retryable": True,
        "transaction_outcome": "rolled_back",
        "retry_requires_fresh_restore": True,
    }


def test_terminal_replay_drift_is_a_structured_idempotency_conflict() -> None:
    def conflict() -> None:
        raise OrchestrationReplayConflict("completion replay conflict")

    with pytest.raises(HTTPException) as exc_info:
        agent_control.run(conflict)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {
        "code": "idempotency_conflict",
        "message": "completion replay conflict",
    }
