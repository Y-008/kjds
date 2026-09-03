"""Transactional PostgreSQL facade for TeamAgent session mutations.

Each durable state transition locks the 0100 session sidecar, reconciles 0099
task/event truth, performs the Coordinator and durable task mutation on one
connection, binds the winning task revision, and saves the next sidecar
revision before commit. A write-authorized expired-lease recovery may commit
before the requested mutation so a stale request cannot roll back canonical
expiry; the recovery transition and the requested transition are each atomic.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from .agent_team_orchestration import (
    OrchestrationError,
    TaskState,
    TeamAgentCoordinator,
    TeamAgentTask,
)
from .enterprise_control import ExactScope
from .sql_repository import add_outbox_event
from .team_agent_checkpoint_store import (
    PostgresTeamAgentCheckpointStore,
)
from .team_agent_durable_recovery import (
    TeamAgentDurableRecovery,
    team_agent_durable_task_payload,
)
from .team_agent_persistence import (
    DurableTaskState,
    PostgresTeamAgentPersistence,
    TeamAgentTaskRegistration,
    TeamAgentTransactionConflict,
)


def _utc(value: datetime | None = None) -> datetime:
    parsed = value or datetime.now(UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class PostgresTeamAgentRuntime:
    """Single-session transactional facade; all authorities remain explicit."""

    def __init__(self, engine: Engine) -> None:
        if engine.dialect.name != "postgresql":
            raise ValueError("PostgresTeamAgentRuntime requires PostgreSQL")
        self.engine = engine
        # Router/bridge adapters use this marker to pass exact scope and
        # authority into every mutation.  The in-memory coordinator keeps its
        # original, intentionally smaller API.
        self.requires_durable_scope = True

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        """Use one repeatable-read transaction for sidecar and task reads/writes."""

        try:
            with self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection, connection.begin():
                yield connection
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(
                exc.orig,
                "pgcode",
                None,
            )
            if sqlstate in {"40001", "40P01"}:
                raise TeamAgentTransactionConflict(sqlstate=sqlstate) from exc
            raise

    def create_session(
        self,
        *,
        session_ref: str,
        scope: ExactScope,
        objective: str,
        owner_id: str,
        authority_sha256: str,
        max_parallel: int = 3,
        max_active_per_agent: int | None = None,
        cost_budget_units: int | None = None,
        time_budget_seconds: int | None = None,
        provider_buckets: Mapping[str, int] | None = None,
        as_of: datetime | None = None,
    ):
        now = _utc(as_of)
        coordinator = TeamAgentCoordinator()
        created = coordinator.create_session(
            session_ref=session_ref,
            scope=scope,
            objective=objective,
            owner_id=owner_id,
            authority_sha256=authority_sha256,
            max_parallel=max_parallel,
            max_active_per_agent=max_active_per_agent,
            cost_budget_units=cost_budget_units,
            time_budget_seconds=time_budget_seconds,
            provider_buckets=provider_buckets,
            created_at=now,
        )
        with self._transaction() as connection:
            PostgresTeamAgentCheckpointStore(
                self.engine,
                connection=connection,
            ).save(
                coordinator=coordinator,
                session_ref=session_ref,
                expected_revision=None,
                as_of=now,
            )
        return created

    def submit_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        task_ref: str,
        thread_ref: str,
        agent_id: str,
        role: str,
        objective: str,
        idempotency_key: str,
        dependencies: Sequence[str] = (),
        provider_id: str | None = None,
        trace_id: str | None = None,
        evidence_required: bool = False,
        evidence_refs: Sequence[str] = (),
        acceptance_contract: Mapping[str, Any] | None = None,
        reviewer_role: str | None = None,
        reviewer_agent_id: str | None = None,
        max_attempts: int = 3,
        cost_budget_units: int | None = None,
        time_budget_seconds: int | None = None,
        as_of: datetime | None = None,
    ) -> TeamAgentTask:
        now = _utc(as_of)
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        with self._transaction() as connection:
            coordinator, checkpoint_revision, tasks, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            submitted = coordinator.submit_task(
                session_ref=session_ref,
                task_ref=task_ref,
                thread_ref=thread_ref,
                agent_id=agent_id,
                role=role,
                objective=objective,
                idempotency_key=idempotency_key,
                dependencies=tuple(dependencies),
                provider_id=provider_id,
                trace_id=trace_id,
                evidence_required=evidence_required,
                evidence_refs=tuple(evidence_refs),
                acceptance_contract=acceptance_contract,
                reviewer_role=reviewer_role,
                reviewer_agent_id=reviewer_agent_id,
                max_attempts=max_attempts,
                cost_budget_units=cost_budget_units,
                time_budget_seconds=time_budget_seconds,
                created_at=now,
            )
            persisted = tasks.register_task(
                scope=scope,
                task=TeamAgentTaskRegistration(
                    session_ref=session_ref,
                    task_ref=task_ref,
                    idempotency_key=idempotency_key,
                    payload=team_agent_durable_task_payload(submitted),
                    max_attempts=max_attempts,
                ),
                as_of=now,
            )
            self._bind_and_save(
                coordinator=coordinator,
                task=persisted,
                checkpoints=checkpoints,
                session_ref=session_ref,
                checkpoint_revision=checkpoint_revision,
                as_of=now,
            )
            return coordinator.task(task_ref)

    def claim_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        task_ref: str,
        worker_id: str,
        lease_seconds: int = 120,
        lease_id: str | None = None,
        as_of: datetime | None = None,
    ) -> TeamAgentTask:
        now = _utc(as_of)
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        claim_error: OrchestrationError | None = None
        claimed_result: TeamAgentTask | None = None
        with self._transaction() as connection:
            coordinator, checkpoint_revision, tasks, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            before = coordinator.task(task_ref)
            try:
                projected = coordinator.claim_task(
                    task_ref=task_ref,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    lease_id=lease_id,
                    as_of=now,
                )
            except OrchestrationError as exc:
                projected = coordinator.task(task_ref)
                if projected == before:
                    raise
                if projected.state is not TaskState.BLOCKED:
                    raise RuntimeError(
                        "claim failure produced an unsupported durable transition"
                    ) from exc
                persisted = tasks.block_task(
                    scope=scope,
                    session_ref=session_ref,
                    task_ref=task_ref,
                    reason=projected.blocked_reason or "retry_budget_exhausted",
                    as_of=now,
                )
                claim_error = exc
            else:
                if projected.lease_ref is None or projected.lease_expires_at is None:
                    raise RuntimeError("Coordinator claim lost its lease projection")
                persisted = tasks.claim_task(
                    scope=scope,
                    session_ref=session_ref,
                    task_ref=task_ref,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    lease_ref=projected.lease_ref,
                    lease_expires_at=projected.lease_expires_at,
                    as_of=now,
                )
                if projected == before and persisted.revision == coordinator.durable_task_revisions(
                    session_ref=session_ref
                ).get(task_ref):
                    # Active same-worker claim replay is a durable no-op.
                    return before
            self._bind_and_save(
                coordinator=coordinator,
                task=persisted,
                checkpoints=checkpoints,
                session_ref=session_ref,
                checkpoint_revision=checkpoint_revision,
                as_of=now,
            )
            claimed_result = coordinator.task(task_ref)
        if claim_error is not None:
            raise claim_error
        if claimed_result is None:
            raise RuntimeError("TeamAgent claim completed without a result")
        return claimed_result

    def heartbeat_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        extend_seconds: int | None = None,
        lease_seconds: int | None = None,
        as_of: datetime | None = None,
    ) -> TeamAgentTask:
        now = _utc(as_of)
        extension = extend_seconds if extend_seconds is not None else lease_seconds
        if extension is None:
            extension = 120
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        with self._transaction() as connection:
            coordinator, checkpoint_revision, tasks, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            projected = coordinator.heartbeat_task(
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                extend_seconds=extension,
                as_of=now,
            )
            if projected.lease_expires_at is None:
                raise RuntimeError("Coordinator heartbeat lost its lease expiry")
            persisted = tasks.heartbeat_task(
                scope=scope,
                session_ref=session_ref,
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                extend_seconds=extension,
                lease_expires_at=projected.lease_expires_at,
                as_of=now,
            )
            self._bind_and_save(
                coordinator=coordinator,
                task=persisted,
                checkpoints=checkpoints,
                session_ref=session_ref,
                checkpoint_revision=checkpoint_revision,
                as_of=now,
            )
            return coordinator.task(task_ref)

    def release_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        as_of: datetime | None = None,
    ) -> TeamAgentTask:
        """Return an active lease to the queued state on one commit boundary."""

        now = _utc(as_of)
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        with self._transaction() as connection:
            coordinator, checkpoint_revision, tasks, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            released = coordinator.release_task(
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                as_of=now,
            )
            persisted = tasks.release_task(
                scope=scope,
                session_ref=session_ref,
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                as_of=now,
            )
            self._bind_and_save(
                coordinator=coordinator,
                task=persisted,
                checkpoints=checkpoints,
                session_ref=session_ref,
                checkpoint_revision=checkpoint_revision,
                as_of=now,
            )
            return released

    def complete_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        result: Mapping[str, Any],
        evidence_refs: Sequence[str] = (),
        reviewer_id: str | None = None,
        cost_units: int = 0,
        as_of: datetime | None = None,
    ) -> TeamAgentTask:
        now = _utc(as_of)
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        with self._transaction() as connection:
            coordinator, checkpoint_revision, tasks, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            before = coordinator.task(task_ref)
            durable_revision = coordinator.durable_task_revisions(
                session_ref=session_ref
            ).get(task_ref)
            completed = coordinator.complete_task(
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                result=result,
                evidence_refs=tuple(evidence_refs),
                reviewer_id=reviewer_id,
                cost_units=cost_units,
                as_of=now,
            )
            persisted = tasks.complete_task(
                scope=scope,
                session_ref=session_ref,
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                result=result,
                evidence_refs=evidence_refs,
                reviewer_id=reviewer_id,
                as_of=now,
            )
            if completed == before and persisted.revision == durable_revision:
                return completed
            self._bind_and_save(
                coordinator=coordinator,
                task=persisted,
                checkpoints=checkpoints,
                session_ref=session_ref,
                checkpoint_revision=checkpoint_revision,
                as_of=now,
            )
            self._stage_terminal_publish_outbox(
                connection=connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                task=completed,
                state="passed",
                worker_id=worker_id,
            )
            return completed

    def fail_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        task_ref: str,
        worker_id: str,
        lease_ref: str,
        failure_code: str,
        status_code: int | None = None,
        timeout: bool = False,
        retry_after_seconds: float | None = None,
        as_of: datetime | None = None,
    ) -> TeamAgentTask:
        now = _utc(as_of)
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        with self._transaction() as connection:
            coordinator, checkpoint_revision, tasks, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            before = coordinator.task(task_ref)
            durable_revision = coordinator.durable_task_revisions(
                session_ref=session_ref
            ).get(task_ref)
            failed = coordinator.fail_task(
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                failure_code=failure_code,
                status_code=status_code,
                timeout=timeout,
                retry_after_seconds=retry_after_seconds,
                as_of=now,
            )
            durable_state = DurableTaskState(failed.state.value)
            persisted = tasks.fail_task(
                scope=scope,
                session_ref=session_ref,
                task_ref=task_ref,
                worker_id=worker_id,
                lease_ref=lease_ref,
                failure_code=failure_code,
                failure_kind=failed.failure_kind or "business",
                next_state=durable_state,
                retry_wait_until=failed.retry_wait_until,
                retry_after_seconds=failed.retry_after_seconds,
                blocked_reason=failed.blocked_reason,
                as_of=now,
            )
            if failed == before and persisted.revision == durable_revision:
                return failed
            self._bind_and_save(
                coordinator=coordinator,
                task=persisted,
                checkpoints=checkpoints,
                session_ref=session_ref,
                checkpoint_revision=checkpoint_revision,
                as_of=now,
            )
            if failed.state in {TaskState.FAILED, TaskState.BLOCKED}:
                self._stage_terminal_publish_outbox(
                    connection=connection,
                    scope=scope,
                    session_ref=session_ref,
                    authority_sha256=authority_sha256,
                    task=failed,
                    state=("blocked" if failed.state is TaskState.BLOCKED else "failed"),
                    worker_id=worker_id,
                )
            return failed

    def pause(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        reason: str,
        actor_id: str,
        as_of: datetime | None = None,
    ):
        return self._control_mutation(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=as_of,
            mutate=lambda coordinator, now: coordinator.pause(
                session_ref=session_ref,
                reason=reason,
                actor_id=actor_id,
                as_of=now,
            ),
        )

    def resume(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        actor_id: str,
        reason: str = "manual resume",
        as_of: datetime | None = None,
    ):
        return self._control_mutation(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=as_of,
            mutate=lambda coordinator, now: coordinator.resume(
                session_ref=session_ref,
                actor_id=actor_id,
                reason=reason,
                as_of=now,
            ),
        )

    def engage_kill_switch(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        reason: str,
        actor_id: str,
        as_of: datetime | None = None,
    ):
        return self._control_mutation(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=as_of,
            mutate=lambda coordinator, now: coordinator.engage_kill_switch(
                session_ref=session_ref,
                reason=reason,
                actor_id=actor_id,
                as_of=now,
            ),
        )

    kill_switch = engage_kill_switch

    def release_kill_switch(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        reason: str,
        actor_id: str,
        as_of: datetime | None = None,
    ):
        return self._control_mutation(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=as_of,
            mutate=lambda coordinator, now: coordinator.release_kill_switch(
                session_ref=session_ref,
                reason=reason,
                actor_id=actor_id,
                as_of=now,
            ),
        )

    clear_kill_switch = release_kill_switch

    def fork_thread(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        thread_ref: str,
        title: str,
        parent_thread_ref: str | None = None,
        parent_task_ref: str | None = None,
        handoff_ref: str | None = None,
        target_role: str | None = None,
        as_of: datetime | None = None,
    ):
        now = _utc(as_of)
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        with self._transaction() as connection:
            coordinator, checkpoint_revision, _, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            created = coordinator.fork_thread(
                session_ref=session_ref,
                thread_ref=thread_ref,
                title=title,
                parent_thread_ref=parent_thread_ref,
                parent_task_ref=parent_task_ref,
                handoff_ref=handoff_ref,
                target_role=target_role,
                created_at=now,
            )
            checkpoints.save(
                coordinator=coordinator,
                session_ref=session_ref,
                expected_revision=checkpoint_revision,
                as_of=now,
            )
            return created

    def handoff_task(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        source_task_ref: str,
        source_thread_ref: str,
        target_thread_ref: str,
        target_role: str,
        input_evidence_refs: Sequence[str],
        acceptance_contract: Mapping[str, Any],
        trace_id: str,
        as_of: datetime | None = None,
    ):
        """Persist handoff lineage in the authority-bound session sidecar."""

        now = _utc(as_of)
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        with self._transaction() as connection:
            coordinator, checkpoint_revision, _, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            previous_handoff_ref = coordinator.task(source_task_ref).handoff_ref
            handoff = coordinator.handoff_task(
                session_ref=session_ref,
                source_task_ref=source_task_ref,
                source_thread_ref=source_thread_ref,
                target_thread_ref=target_thread_ref,
                target_role=target_role,
                input_evidence_refs=input_evidence_refs,
                acceptance_contract=acceptance_contract,
                trace_id=trace_id,
                scope=scope,
                created_at=now,
            )
            if previous_handoff_ref == handoff.handoff_ref:
                return handoff
            checkpoints.save(
                coordinator=coordinator,
                session_ref=session_ref,
                expected_revision=checkpoint_revision,
                as_of=now,
            )
            return handoff

    create_handoff = handoff_task
    submit_handoff = handoff_task

    def restore_session(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        as_of: datetime | None = None,
        for_update: bool = False,
    ) -> TeamAgentCoordinator:
        now = _utc(as_of)
        with self._transaction() as connection:
            coordinator, _, _, _ = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
                for_update=for_update,
            )
            return coordinator

    def recover_session(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        as_of: datetime | None = None,
    ) -> TeamAgentCoordinator:
        """Run the explicit, write-authorized expired-lease recovery path."""

        return self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=_utc(as_of),
        )

    def session(
        self,
        session_ref: str,
        *,
        scope: ExactScope | None = None,
        authority_sha256: str | None = None,
    ):
        """Read one authority-bound session; bare global IDs are not admitted."""

        return self.session_coordinator(
            session_ref,
            scope=scope,
            authority_sha256=authority_sha256,
        ).session(session_ref)

    def task(
        self,
        task_ref: str,
        *,
        session_ref: str | None = None,
        scope: ExactScope | None = None,
        authority_sha256: str | None = None,
    ):
        """Read one authority-bound task; bare global IDs are not admitted."""

        if session_ref is None:
            raise ValueError(
                "durable task lookup requires session_ref, exact scope, and authority"
            )
        return self.session_coordinator(
            session_ref,
            scope=scope,
            authority_sha256=authority_sha256,
        ).task(task_ref)

    def task_for_session(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        task_ref: str,
    ):
        return self.restore_session(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            for_update=False,
        ).task(task_ref)

    def snapshot(
        self,
        *,
        session_ref: str,
        scope: ExactScope | None = None,
        authority_sha256: str | None = None,
    ) -> dict[str, Any]:
        coordinator = self.session_coordinator(
            session_ref,
            scope=scope,
            authority_sha256=authority_sha256,
        )
        return coordinator.snapshot(session_ref=session_ref)

    def observations(
        self,
        *,
        session_ref: str,
        scope: ExactScope | None = None,
        authority_sha256: str | None = None,
    ):
        return self.session_coordinator(
            session_ref,
            scope=scope,
            authority_sha256=authority_sha256,
        ).observations(session_ref=session_ref)

    def session_coordinator(
        self,
        session_ref: str,
        *,
        scope: ExactScope | None = None,
        authority_sha256: str | None = None,
    ) -> TeamAgentCoordinator:
        if scope is None or authority_sha256 is None:
            raise ValueError(
                "durable session lookup requires exact scope and authority"
            )
        return self.restore_session(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            for_update=False,
        )

    def _control_mutation(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        as_of: datetime | None,
        mutate: Any,
    ):
        now = _utc(as_of)
        self._recover_expired_leases(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=now,
        )
        with self._transaction() as connection:
            coordinator, checkpoint_revision, tasks, checkpoints = self._restore_locked(
                connection,
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=now,
            )
            before = self._task_map(coordinator, session_ref)
            result = mutate(coordinator, now)
            after = self._task_map(coordinator, session_ref)
            for task_ref, projected in after.items():
                previous = before.get(task_ref)
                if previous is None or previous == projected:
                    continue
                persisted = self._persist_control_task(
                    tasks=tasks,
                    scope=scope,
                    session_ref=session_ref,
                    previous=previous,
                    projected=projected,
                    as_of=now,
                )
                coordinator.bind_durable_task_revision(
                    task_ref=task_ref,
                    revision=persisted.revision,
                    request_sha256=persisted.request_sha256,
                )
            checkpoints.save(
                coordinator=coordinator,
                session_ref=session_ref,
                expected_revision=checkpoint_revision,
                as_of=now,
            )
            return result

    @staticmethod
    def _task_map(
        coordinator: TeamAgentCoordinator,
        session_ref: str,
    ) -> dict[str, TeamAgentTask]:
        return {
            str(item["task_ref"]): coordinator.task(str(item["task_ref"]))
            for item in coordinator.checkpoint(session_ref=session_ref).get("tasks", ())
        }

    @staticmethod
    def _persist_control_task(
        *,
        tasks: PostgresTeamAgentPersistence,
        scope: ExactScope,
        session_ref: str,
        previous: TeamAgentTask,
        projected: TeamAgentTask,
        as_of: datetime,
    ):
        reason = projected.blocked_reason or "session control"
        if projected.state is TaskState.PAUSED and previous.state is not TaskState.PAUSED:
            return tasks.pause_task(
                scope=scope,
                session_ref=session_ref,
                task_ref=projected.task_ref,
                reason=reason,
                worker_id=previous.claimed_by,
                lease_ref=previous.lease_ref,
                as_of=as_of,
            )
        if previous.state is TaskState.PAUSED and projected.state in {
            TaskState.QUEUED,
            TaskState.RETRY_WAIT,
        }:
            return tasks.resume_task(
                scope=scope,
                session_ref=session_ref,
                task_ref=projected.task_ref,
                as_of=as_of,
            )
        if projected.state is TaskState.EXPIRED and previous.state is TaskState.RUNNING:
            return tasks.revoke_task(
                scope=scope,
                session_ref=session_ref,
                task_ref=projected.task_ref,
                reason=reason,
                as_of=as_of,
            )
        raise RuntimeError(
            "unsupported durable session-control task transition: "
            f"{previous.state.value}->{projected.state.value}"
        )

    def _recover_expired_leases(
        self,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        as_of: datetime,
    ) -> TeamAgentCoordinator:
        """Atomically reconcile due leases before admitting a runtime action."""

        with self._transaction() as connection:
            tasks = PostgresTeamAgentPersistence(self.engine, connection=connection)
            checkpoints = PostgresTeamAgentCheckpointStore(
                self.engine,
                connection=connection,
            )
            recovered = TeamAgentDurableRecovery(
                checkpoints=checkpoints,
                tasks=tasks,
            ).restore(
                scope=scope,
                session_ref=session_ref,
                authority_sha256=authority_sha256,
                as_of=as_of,
                for_update=True,
                allow_expired_leases=True,
            )
            coordinator = recovered.coordinator
            expired_refs = sorted(
                task_ref
                for task_ref in recovered.task_revisions
                if (
                    (task := coordinator.task(task_ref)).state
                    is TaskState.RUNNING
                    and task.lease_expires_at is not None
                    and task.lease_expires_at <= as_of
                )
            )
            if not expired_refs:
                return coordinator
            for task_ref in expired_refs:
                projected = coordinator.expire_task(
                    task_ref=task_ref,
                    as_of=as_of,
                )
                persisted = tasks.expire_task(
                    scope=scope,
                    session_ref=session_ref,
                    task_ref=task_ref,
                    next_state=DurableTaskState(projected.state.value),
                    blocked_reason=projected.blocked_reason,
                    as_of=as_of,
                )
                coordinator.bind_durable_task_revision(
                    task_ref=task_ref,
                    revision=persisted.revision,
                    request_sha256=persisted.request_sha256,
                )
            checkpoints.save(
                coordinator=coordinator,
                session_ref=session_ref,
                expected_revision=recovered.checkpoint.revision,
                as_of=as_of,
            )
            return coordinator

    def _restore_locked(
        self,
        connection: Any,
        *,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        as_of: datetime,
        for_update: bool = True,
    ) -> tuple[
        TeamAgentCoordinator,
        int,
        PostgresTeamAgentPersistence,
        PostgresTeamAgentCheckpointStore,
    ]:
        tasks = PostgresTeamAgentPersistence(self.engine, connection=connection)
        checkpoints = PostgresTeamAgentCheckpointStore(
            self.engine,
            connection=connection,
        )
        recovered = TeamAgentDurableRecovery(
            checkpoints=checkpoints,
            tasks=tasks,
        ).restore(
            scope=scope,
            session_ref=session_ref,
            authority_sha256=authority_sha256,
            as_of=as_of,
            for_update=for_update,
        )
        return recovered.coordinator, recovered.checkpoint.revision, tasks, checkpoints

    @staticmethod
    def _bind_and_save(
        *,
        coordinator: TeamAgentCoordinator,
        task: Any,
        checkpoints: PostgresTeamAgentCheckpointStore,
        session_ref: str,
        checkpoint_revision: int,
        as_of: datetime,
    ) -> None:
        coordinator.bind_durable_task_revision(
            task_ref=task.task_ref,
            revision=task.revision,
            request_sha256=task.request_sha256,
        )
        checkpoints.save(
            coordinator=coordinator,
            session_ref=session_ref,
            expected_revision=checkpoint_revision,
            as_of=as_of,
        )

    @staticmethod
    def _stage_terminal_publish_outbox(
        *,
        connection: Connection,
        scope: ExactScope,
        session_ref: str,
        authority_sha256: str,
        task: TeamAgentTask,
        state: str,
        worker_id: str,
    ) -> None:
        """Atomically enqueue an observation-only terminal publication.

        The outbox payload intentionally contains only the authority-bound
        locator. The publisher restores the canonical terminal observation and
        lets the Harness sink perform its own authorization/idempotency check;
        task results never enter the delivery envelope.
        """

        # The coordinator observation is resolved by the publisher from the
        # durable checkpoint. The task reference is the stable outbox key.
        payload = {
            "contract_id": "team-agent-terminal-observation-outbox@1",
            "session_ref": session_ref,
            "task_ref": task.task_ref,
            "state": state,
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "authority_sha256": authority_sha256,
        }
        with Session(bind=connection, expire_on_commit=False) as session:
            add_outbox_event(
                session,
                "team_agent.terminal_observation.ready",
                f"team-agent:{session_ref}:{task.task_ref}",
                payload,
                actor_id=worker_id,
            )
            session.flush()


__all__ = ["PostgresTeamAgentRuntime"]
