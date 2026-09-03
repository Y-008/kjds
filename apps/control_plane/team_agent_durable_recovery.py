"""Fail-closed reconcile for 0099 tasks and 0100 session checkpoints.

The reconciler is also the admission primitive used by the PostgreSQL runtime
facade.  It verifies that a restored session sidecar is backed by durable
task/event truth before callers may use or mutate the Coordinator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .agent_team_orchestration import TeamAgentCoordinator
from .enterprise_control import EnterpriseControlError, ExactScope
from .team_agent_checkpoint_store import (
    DurableTeamAgentCheckpoint,
    TeamAgentCheckpointStore,
)
from .team_agent_persistence import CONTRACT_ID as TASK_PERSISTENCE_CONTRACT_ID
from .team_agent_persistence import TeamAgentPersistence

CONTRACT_ID = "kjds-team-agent-durable-recovery-v1"
TASK_PAYLOAD_CONTRACT_ID = "kjds-team-agent-durable-task-v1"


class TeamAgentDurableRecoveryError(EnterpriseControlError):
    """The durable session cannot be admitted for runtime use."""


@dataclass(frozen=True, slots=True)
class ReconciledTeamAgentSession:
    coordinator: TeamAgentCoordinator
    checkpoint: DurableTeamAgentCheckpoint
    task_checkpoint_sha256: str
    task_revisions: dict[str, int]
    reconciled_at: datetime


def _utc(value: datetime | None = None) -> datetime:
    parsed = value or datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _scope_payload(scope: ExactScope) -> dict[str, str]:
    return {
        "tenant_ref": scope.tenant_ref,
        "entity_ref": scope.entity_ref,
        "store_ref": scope.store_ref,
    }


def _task_projection(task: Any) -> dict[str, Any]:
    completed = task.state.value == "completed"
    return {
        "state": task.state.value,
        "claimed_by": task.claimed_by,
        "lease_ref": task.lease_ref,
        "lease_expires_at": (
            task.lease_expires_at.isoformat() if task.lease_expires_at else None
        ),
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
        "retry_wait_until": (
            task.retry_wait_until.isoformat() if task.retry_wait_until else None
        ),
        "retry_after_seconds": task.retry_after_seconds,
        "failure_code": task.failure_code,
        "failure_kind": task.failure_kind,
        "blocked_reason": task.blocked_reason,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "expired_at": task.expired_at.isoformat() if task.expired_at else None,
        "result": task.result if completed else None,
        "evidence_refs": list(task.evidence_refs) if completed else [],
        "reviewer_id": task.reviewer_id if completed else None,
    }


def team_agent_durable_task_payload(
    task: Any,
    *,
    submitted_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile the closed 0099 registration payload from a Coordinator task."""

    submitted = submitted_payload or {}
    return {
        "contract_id": TASK_PAYLOAD_CONTRACT_ID,
        "thread_ref": submitted.get("thread_ref", task.thread_ref),
        "agent_id": submitted.get("agent_id", task.agent_id),
        "role": submitted.get("role", task.role),
        "objective": submitted.get("objective", task.objective),
        "dependencies": list(submitted.get("dependencies", task.dependencies)),
        "provider_id": submitted.get("provider_id", task.provider_id),
        "trace_id": submitted.get("trace_id", task.trace_id),
        "parent_task_ref": submitted.get("parent_task_ref", task.parent_task_ref),
        "handoff_ref": submitted.get("handoff_ref", task.handoff_ref),
        "requires_evidence": submitted.get(
            "evidence_required", task.requires_evidence
        ),
        "evidence_refs": list(submitted.get("evidence_refs", task.evidence_refs)),
        "acceptance_contract": submitted.get(
            "acceptance_contract", task.acceptance_contract
        ),
        "reviewer_role": submitted.get("reviewer_role", task.reviewer_role),
        "cost_budget_units": submitted.get(
            "cost_budget_units", task.cost_budget_units
        ),
        "time_budget_seconds": submitted.get(
            "time_budget_seconds", task.time_budget_seconds
        ),
    }


def _durable_projection(task: Mapping[str, Any]) -> dict[str, Any]:
    paused = task.get("state") == "paused"
    projected = {
        key: task.get(key)
        for key in (
            "state",
            "claimed_by",
            "lease_ref",
            "lease_expires_at",
            "attempt_count",
            "max_attempts",
            "retry_wait_until",
            "retry_after_seconds",
            "failure_code",
            "failure_kind",
            "blocked_reason",
            "completed_at",
            "expired_at",
        )
    }
    if paused:
        projected.update(
            {
                "retry_wait_until": task.get("paused_retry_wait_until"),
                "retry_after_seconds": task.get("paused_retry_after_seconds"),
            }
        )
    completed = task.get("state") == "completed"
    projected.update(
        {
            "result": task.get("result") if completed else None,
            "evidence_refs": list(task.get("evidence_refs") or ()) if completed else [],
            "reviewer_id": task.get("reviewer_id") if completed else None,
        }
    )
    return projected


class TeamAgentDurableRecovery:
    """Restore a sidecar only when its 0099 task projection is exact."""

    def __init__(
        self,
        *,
        checkpoints: TeamAgentCheckpointStore,
        tasks: TeamAgentPersistence,
    ) -> None:
        checkpoint_connection = getattr(checkpoints, "_connection", None)
        task_connection = getattr(tasks, "_connection", None)
        # PostgreSQL adapters must be backed by the same caller-owned
        # connection.  Opening one connection per adapter would make the
        # checkpoint/task reads a split snapshot and permit TOCTOU drift
        # between reconcile and mutation.  In-memory stores intentionally do
        # not expose _connection and remain valid for deterministic recovery
        # rehearsals.
        if (
            (hasattr(checkpoints, "_connection") or hasattr(tasks, "_connection"))
            and (
                checkpoint_connection is None
                or task_connection is None
                or checkpoint_connection is not task_connection
            )
        ):
            raise TeamAgentDurableRecoveryError(
                "PostgreSQL durable recovery requires one caller-owned "
                "shared connection"
            )
        self._checkpoints = checkpoints
        self._tasks = tasks

    def restore(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        as_of: datetime | None = None,
        for_update: bool = False,
        allow_expired_leases: bool = False,
    ) -> ReconciledTeamAgentSession:
        if allow_expired_leases and not for_update:
            raise ValueError(
                "allow_expired_leases requires a caller-owned locked recovery"
            )
        now = _utc(as_of)
        hydrated = self._checkpoints.restore(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            for_update=for_update,
        )
        durable = self._tasks.checkpoint(scope=scope, session_ref=session_ref)
        if durable.get("contract_id") != TASK_PERSISTENCE_CONTRACT_ID:
            raise TeamAgentDurableRecoveryError("durable task contract drift")
        if durable.get("scope") != _scope_payload(scope):
            raise TeamAgentDurableRecoveryError("durable task scope conflict")
        if durable.get("session_ref") != session_ref:
            raise TeamAgentDurableRecoveryError("durable task session conflict")
        task_sha256 = str(durable.get("checkpoint_sha256") or "")
        if len(task_sha256) != 64:
            raise TeamAgentDurableRecoveryError("durable task checkpoint hash is invalid")

        coordinator = hydrated.coordinator
        sidecar_tasks = {
            task.task_ref: task
            for task in (
                coordinator.task(item["task_ref"])
                for item in coordinator.checkpoint(session_ref=session_ref)["tasks"]
            )
        }
        durable_tasks = {
            str(item["task_ref"]): item for item in durable.get("tasks", ())
        }
        submitted_payloads = {
            str(event["payload"]["task_ref"]): event["payload"]
            for event in coordinator.events(session_ref=session_ref)
            if event.get("event_type") == "task.submitted"
            and isinstance(event.get("payload"), Mapping)
            and event["payload"].get("task_ref") is not None
        }
        if set(sidecar_tasks) != set(durable_tasks):
            raise TeamAgentDurableRecoveryError(
                "sidecar and durable task sets are not conserved"
            )

        revisions = coordinator.durable_task_revisions(session_ref=session_ref)
        requests = coordinator.durable_task_requests(session_ref=session_ref)
        if set(revisions) != set(sidecar_tasks):
            raise TeamAgentDurableRecoveryError(
                "sidecar durable task revisions are incomplete"
            )
        if set(requests) != set(sidecar_tasks):
            raise TeamAgentDurableRecoveryError(
                "sidecar durable task request hashes are incomplete"
            )
        for task_ref, sidecar_task in sidecar_tasks.items():
            durable_task = durable_tasks[task_ref]
            durable_revision = durable_task.get("revision")
            if revisions[task_ref] != durable_revision:
                raise TeamAgentDurableRecoveryError(
                    f"durable task revision conflict: {task_ref}"
                )
            if requests[task_ref] != durable_task.get("request_sha256"):
                raise TeamAgentDurableRecoveryError(
                    f"durable task request identity conflict: {task_ref}"
                )
            if durable_task.get("idempotency_key") != sidecar_task.idempotency_key:
                raise TeamAgentDurableRecoveryError(
                    f"durable task idempotency conflict: {task_ref}"
                )
            if durable_task.get("payload") != team_agent_durable_task_payload(
                sidecar_task,
                submitted_payload=submitted_payloads.get(task_ref),
            ):
                raise TeamAgentDurableRecoveryError(
                    f"durable task request projection conflict: {task_ref}"
                )
            if _task_projection(sidecar_task) != _durable_projection(durable_task):
                raise TeamAgentDurableRecoveryError(
                    f"durable task projection conflict: {task_ref}"
                )
            lease_expires_at = durable_task.get("lease_expires_at")
            if (
                durable_task.get("state") == "running"
                and lease_expires_at is not None
                and _utc(datetime.fromisoformat(str(lease_expires_at))) <= now
                and not allow_expired_leases
            ):
                raise TeamAgentDurableRecoveryError(
                    f"expired durable lease requires controlled recovery: {task_ref}"
                )

        return ReconciledTeamAgentSession(
            coordinator=coordinator,
            checkpoint=hydrated.durable,
            task_checkpoint_sha256=task_sha256,
            task_revisions=dict(sorted(revisions.items())),
            reconciled_at=now,
        )


__all__ = [
    "CONTRACT_ID",
    "ReconciledTeamAgentSession",
    "TeamAgentDurableRecovery",
    "TeamAgentDurableRecoveryError",
    "TASK_PAYLOAD_CONTRACT_ID",
    "team_agent_durable_task_payload",
]
