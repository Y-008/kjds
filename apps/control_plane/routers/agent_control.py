from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..agent_harness import GRAPH_KINDS
from ..agent_runtime import AgentRunEvidenceRef, AgentRunScopeContext
from ..api_contracts import (
    OperatingSubjectEventInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..enterprise_control import ExactScope
from ..runtime import runtime
from ..security import Principal
from ..team_agent_checkpoint_store import (
    TeamAgentCheckpointError,
    TeamAgentCheckpointIntegrityError,
    TeamAgentCheckpointNotFound,
)
from ..team_agent_durable_recovery import TeamAgentDurableRecoveryError
from ..team_agent_persistence import TeamAgentPersistenceError
from ..team_agent_reviewer_authority import (
    CONTRACT_ID as TEAM_AGENT_REVIEWER_CONTRACT_ID,
)
from ..team_agent_reviewer_authority import TeamAgentReviewerAuthorityUnavailable

router = APIRouter()


class TeamSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_ref: str = Field(min_length=1, max_length=160)
    entity_ref: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=2000)
    max_parallel: int = Field(default=3, ge=1, le=32)
    max_active_per_agent: int | None = Field(default=None, ge=1, le=32)
    cost_budget_units: int | None = Field(default=None, ge=0)
    time_budget_seconds: int | None = Field(default=None, ge=1)
    provider_buckets: dict[str, Annotated[int, Field(ge=1)]] | None = None


class TeamThreadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_ref: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    parent_thread_ref: str | None = Field(default=None, max_length=160)


class TeamHandoffInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_task_ref: str = Field(min_length=1, max_length=160)
    source_thread_ref: str = Field(min_length=1, max_length=160)
    target_thread_ref: str = Field(min_length=1, max_length=160)
    target_role: str = Field(min_length=1, max_length=160)
    input_evidence_refs: tuple[str, ...] = Field(min_length=1, max_length=20)
    acceptance_contract: dict[str, object]
    trace_id: str = Field(min_length=1, max_length=160)


class TeamTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_ref: str = Field(min_length=1, max_length=160)
    thread_ref: str = Field(min_length=1, max_length=160)
    agent_id: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=2000)
    idempotency_key: str = Field(min_length=1, max_length=300)
    dependencies: tuple[str, ...] = ()
    provider_id: str | None = Field(default=None, min_length=1, max_length=240)
    trace_id: str | None = Field(default=None, min_length=1, max_length=240)
    evidence_required: bool = False
    evidence_refs: tuple[str, ...] = ()
    acceptance_contract: dict[str, object] | None = None
    reviewer_role: str | None = Field(default=None, min_length=1, max_length=160)
    reviewer_agent_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=240,
    )
    max_attempts: int = Field(default=3, ge=1, le=3)
    cost_budget_units: int | None = Field(default=None, ge=0)
    time_budget_seconds: int | None = Field(default=None, ge=1)


class TeamTaskClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=240)
    lease_seconds: int = Field(default=120, ge=1, le=3600)
    lease_ref: str | None = Field(default=None, min_length=1, max_length=80)


class TeamTaskHeartbeatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=240)
    lease_seconds: int = Field(default=120, ge=1, le=3600)
    lease_ref: str = Field(min_length=1, max_length=80)


class TeamTaskReleaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=240)
    lease_ref: str = Field(min_length=1, max_length=80)


class TeamTaskCompleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=240)
    lease_ref: str = Field(min_length=1, max_length=80)
    result: dict[str, object]
    evidence_refs: tuple[str, ...] = ()
    reviewer_id: str | None = Field(default=None, min_length=1, max_length=240)
    cost_units: int = Field(default=0, ge=0)


class TeamTaskFailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=240)
    lease_ref: str = Field(min_length=1, max_length=80)
    failure_code: str = Field(min_length=1, max_length=120)
    status_code: int | None = Field(default=None, ge=100, le=599)
    timeout: bool = False
    retry_after_seconds: float | None = Field(default=None, ge=0)


class TeamPublishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=180)
    verifier_id: str = Field(min_length=1, max_length=180)
    verifier_version: str = Field(min_length=1, max_length=80)


class TeamControlInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=500)

RUN_STATUSES = Literal[
    "started",
    "route_selected",
    "attempt_started",
    "attempt_completed",
    "attempt_denied",
    "attempt_failed",
    "eval_completed",
    "succeeded",
    "failed",
    "denied",
    "unknown_outcome",
]


@router.get("/v1/agent-control/runtime")
def governed_agent_runtime_descriptor(
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    governed = runtime.governed_agent_runtime
    adapters = [
        {
            "name": adapter.profile.name,
            "provider": adapter.profile.provider,
            "model": adapter.profile.model,
            "capabilities": sorted(adapter.profile.capabilities),
            "estimated_accuracy": str(adapter.profile.estimated_accuracy),
            "p95_latency_ms": adapter.profile.p95_latency_ms,
            "estimated_cost_usd": str(adapter.profile.estimated_cost_usd),
            "config_sha256": adapter.profile.config_sha256,
        }
        for adapter in (governed.adapters if governed is not None else ())
    ]
    payload = {
        "contract_id": "kjds-governed-agent-runtime-descriptor-v1",
        "status": "ready" if adapters else "no_data",
        "adapters": adapters,
        "routing_dimensions": [
            "capability",
            "estimated_accuracy",
            "p95_latency_ms",
            "estimated_cost_usd",
            "expected_profit_value_usd",
        ],
        "telemetry": {
            "semantic_convention": "opentelemetry-genai",
            "sanitized": True,
            "trace_eval_linkage": True,
        },
        "control_envelope": {
            "proposal_only": True,
            "formal_fact": False,
            "self_approval_allowed": False,
            "permit_issue_allowed": False,
            "tool_execution_allowed": False,
            "external_write_allowed": False,
        },
    }
    payload["snapshot_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return payload


def _team_session_for_principal(
    session_ref: str,
    *,
    principal: Principal,
    store_ref: str,
    recover_expired_leases: bool = False,
):
    ensure_store_scope(principal, store_ref)
    current_entity_ref, current_authority_sha256 = _current_team_authority(
        principal=principal,
        store_ref=store_ref,
    )
    expected_scope = ExactScope(
        principal.tenant_ref,
        current_entity_ref,
        store_ref,
    )
    try:
        if getattr(runtime.agent_team, "requires_durable_scope", False):
            admission = (
                runtime.agent_team.recover_session
                if recover_expired_leases
                else runtime.agent_team.restore_session
            )
            coordinator = admission(
                scope=expected_scope,
                session_ref=session_ref,
                authority_sha256=current_authority_sha256,
            )
            session = coordinator.session(session_ref)
        else:
            session = runtime.agent_team.session(session_ref)
    except (KeyError, TeamAgentCheckpointNotFound) as exc:
        raise HTTPException(404, "TeamAgent session not found") from exc
    except TeamAgentCheckpointIntegrityError as exc:
        raise HTTPException(409, "TeamAgent session authority is stale") from exc
    except (
        TeamAgentCheckpointError,
        TeamAgentDurableRecoveryError,
        TeamAgentPersistenceError,
    ) as exc:
        raise HTTPException(
            409,
            "TeamAgent durable session failed reconcile validation",
        ) from exc
    if (
        session.scope.tenant_ref != principal.tenant_ref
        or session.scope.store_ref != store_ref
    ):
        raise HTTPException(404, "TeamAgent session not found")
    if (
        session.scope.entity_ref != current_entity_ref
        or session.authority_sha256 != current_authority_sha256
    ):
        raise HTTPException(409, "TeamAgent session authority is stale")
    return session


def _team_task_for_session(task_ref: str, session_ref: str, *, session: Any = None):
    try:
        if getattr(runtime.agent_team, "requires_durable_scope", False):
            if session is None:
                raise RuntimeError(
                    "durable TeamAgent task lookup requires the admitted session"
                )
            task = runtime.agent_team.task_for_session(
                scope=session.scope,
                session_ref=session_ref,
                authority_sha256=session.authority_sha256,
                task_ref=task_ref,
            )
        else:
            task = runtime.agent_team.task(task_ref)
    except KeyError as exc:
        raise HTTPException(404, "TeamAgent task not found") from exc
    except (
        TeamAgentCheckpointError,
        TeamAgentDurableRecoveryError,
        TeamAgentPersistenceError,
    ) as exc:
        raise HTTPException(
            409,
            "TeamAgent durable task failed reconcile validation",
        ) from exc
    if task.session_ref != session_ref:
        raise HTTPException(404, "TeamAgent task not found")
    return task


def _team_durable_scope_kwargs(session: Any) -> dict[str, Any]:
    """Pass exact scope only to the PostgreSQL durable facade.

    The in-memory coordinator remains the lightweight test/local adapter and
    deliberately keeps its original method signatures.
    """
    if not getattr(runtime.agent_team, "requires_durable_scope", False):
        return {}
    return {
        "scope": session.scope,
        "authority_sha256": session.authority_sha256,
    }


def _team_durable_task_kwargs(session: Any) -> dict[str, Any]:
    values = _team_durable_scope_kwargs(session)
    if values:
        values["session_ref"] = session.session_ref
    return values


def _assert_worker_identity(*, worker_id: str, principal: Principal) -> str:
    if worker_id != principal.actor_id:
        raise HTTPException(403, "worker identity must match the authenticated actor")
    return principal.actor_id


def _reviewer_authority_error() -> HTTPException:
    return HTTPException(
        409,
        {
            "code": "team_agent_reviewer_authority_unavailable",
            "message": (
                "independent reviewer completion requires a server-verified "
                "reviewer appointment"
            ),
            "retryable": False,
        },
    )


def _admit_team_reviewer(
    *,
    task: Any,
    session: Any,
    requested_reviewer_id: str | None,
    principal: Principal,
    evidence_refs: tuple[str, ...],
) -> tuple[str | None, tuple[str, ...]]:
    """Resolve reviewer identity only through a server-owned appointment seam.

    The coordinator keeps reviewer fields for deterministic pilot/replay
    contracts, but a production API caller cannot prove another principal's
    appointment merely by naming that principal in the completion payload.
    """

    task_reviewer_id = getattr(task, "reviewer_id", None)
    reviewer_role = getattr(task, "reviewer_role", None)
    if requested_reviewer_id is None and task_reviewer_id is None and reviewer_role is None:
        return None, evidence_refs
    if (
        requested_reviewer_id is not None
        and task_reviewer_id is not None
        and requested_reviewer_id != task_reviewer_id
    ):
        raise _reviewer_authority_error()
    try:
        attestation = runtime.agent_team_reviewer_authority.admit(
            scope=session.scope,
            authority_sha256=session.authority_sha256,
            session_ref=session.session_ref,
            task_ref=task.task_ref,
            reviewer_role=reviewer_role,
            requested_reviewer_id=requested_reviewer_id or task_reviewer_id,
            principal=principal,
        )
    except (AttributeError, TeamAgentReviewerAuthorityUnavailable) as exc:
        raise _reviewer_authority_error() from exc
    reviewer_id = getattr(attestation, "reviewer_id", None)
    appointment_evidence_ref = getattr(
        attestation,
        "appointment_evidence_ref",
        None,
    )
    authority_sha256 = getattr(attestation, "authority_sha256", None)
    if (
        getattr(attestation, "contract_id", None) != TEAM_AGENT_REVIEWER_CONTRACT_ID
        or getattr(attestation, "scope", None) != session.scope
        or getattr(attestation, "session_ref", None) != session.session_ref
        or getattr(attestation, "task_ref", None) != task.task_ref
        or not isinstance(reviewer_id, str)
        or not reviewer_id.strip()
        or reviewer_id in {principal.actor_id, task.agent_id}
        or (
            requested_reviewer_id is not None
            and reviewer_id != requested_reviewer_id
        )
        or (task_reviewer_id is not None and reviewer_id != task_reviewer_id)
        or not isinstance(getattr(attestation, "reviewer_role", None), str)
        or (
            reviewer_role is not None
            and getattr(attestation, "reviewer_role", None) != reviewer_role
        )
        or not isinstance(appointment_evidence_ref, str)
        or not appointment_evidence_ref.strip()
        or authority_sha256 != session.authority_sha256
    ):
        raise _reviewer_authority_error()
    combined_evidence = tuple(
        dict.fromkeys((*evidence_refs, appointment_evidence_ref))
    )
    return reviewer_id, combined_evidence


def _current_team_authority(
    *, principal: Principal, store_ref: str
) -> tuple[str, str]:
    """Resolve the existing scope-grant authority before opening a session."""

    try:
        current = runtime.scope_grants.current(
            principal=principal,
            store_ref=store_ref,
            as_of=datetime.now(UTC),
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    if (
        current.get("status") != "ready"
        or not current.get("entity_ref")
        or not current.get("authority_sha256")
    ):
        raise HTTPException(409, "current scope authority is not ready")
    return str(current["entity_ref"]), str(current["authority_sha256"])


@router.post("/v1/agent-control/team/sessions")
def create_team_agent_session(
    body: TeamSessionInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    ensure_store_scope(principal, store_ref)
    current_entity_ref, authority_sha256 = _current_team_authority(
        principal=principal,
        store_ref=store_ref,
    )
    if body.entity_ref != current_entity_ref:
        raise HTTPException(404, "requested entity is outside the current scope")
    return run(
        lambda: runtime.agent_team.create_session(
            session_ref=body.session_ref,
            scope=ExactScope(principal.tenant_ref, body.entity_ref, store_ref),
            objective=body.objective,
            owner_id=principal.actor_id,
            max_parallel=body.max_parallel,
            max_active_per_agent=body.max_active_per_agent,
            cost_budget_units=body.cost_budget_units,
            time_budget_seconds=body.time_budget_seconds,
            provider_buckets=body.provider_buckets,
            authority_sha256=authority_sha256,
        )
    )


@router.get("/v1/agent-control/team/sessions/{session_ref}")
def team_agent_session_snapshot(
    session_ref: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
    )
    return run(
        lambda: runtime.agent_team.snapshot(
            session_ref=session_ref,
            **_team_durable_scope_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/pause")
def pause_team_agent_session(
    session_ref: str,
    body: TeamControlInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    return run(
        lambda: runtime.agent_team.pause(
            session_ref=session_ref,
            reason=body.reason,
            actor_id=principal.actor_id,
            **_team_durable_scope_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/resume")
def resume_team_agent_session(
    session_ref: str,
    body: TeamControlInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    return run(
        lambda: runtime.agent_team.resume(
            session_ref=session_ref,
            actor_id=principal.actor_id,
            reason=body.reason,
            **_team_durable_scope_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/kill-switch")
def engage_team_agent_kill_switch(
    session_ref: str,
    body: TeamControlInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    return run(
        lambda: runtime.agent_team.engage_kill_switch(
            session_ref=session_ref,
            reason=body.reason,
            actor_id=principal.actor_id,
            **_team_durable_scope_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/kill-switch/release")
def release_team_agent_kill_switch(
    session_ref: str,
    body: TeamControlInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    return run(
        lambda: runtime.agent_team.release_kill_switch(
            session_ref=session_ref,
            reason=body.reason,
            actor_id=principal.actor_id,
            **_team_durable_scope_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/threads")
def create_team_agent_thread(
    session_ref: str,
    body: TeamThreadInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    return run(
        lambda: runtime.agent_team.fork_thread(
            session_ref=session_ref,
            thread_ref=body.thread_ref,
            title=body.title,
            parent_thread_ref=body.parent_thread_ref,
            **_team_durable_scope_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/handoffs")
def create_team_agent_handoff(
    session_ref: str,
    body: TeamHandoffInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    _team_task_for_session(
        body.source_task_ref,
        session_ref,
        session=session,
    )
    return run(
        lambda: runtime.agent_team.handoff_task(
            session_ref=session_ref,
            source_task_ref=body.source_task_ref,
            source_thread_ref=body.source_thread_ref,
            target_thread_ref=body.target_thread_ref,
            target_role=body.target_role,
            input_evidence_refs=body.input_evidence_refs,
            acceptance_contract=body.acceptance_contract,
            trace_id=body.trace_id,
            **_team_durable_scope_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/tasks")
def submit_team_agent_task(
    session_ref: str,
    body: TeamTaskInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    return run(
        lambda: runtime.agent_team.submit_task(
            session_ref=session_ref,
            task_ref=body.task_ref,
            thread_ref=body.thread_ref,
            agent_id=body.agent_id,
            role=body.role,
            objective=body.objective,
            idempotency_key=body.idempotency_key,
            dependencies=body.dependencies,
            provider_id=body.provider_id,
            trace_id=body.trace_id,
            evidence_required=body.evidence_required,
            evidence_refs=body.evidence_refs,
            acceptance_contract=body.acceptance_contract,
            reviewer_role=body.reviewer_role,
            reviewer_agent_id=body.reviewer_agent_id,
            max_attempts=body.max_attempts,
            cost_budget_units=body.cost_budget_units,
            time_budget_seconds=body.time_budget_seconds,
            **_team_durable_scope_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/tasks/{task_ref}/claim")
def claim_team_agent_task(
    session_ref: str,
    task_ref: str,
    body: TeamTaskClaimInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    _team_task_for_session(task_ref, session_ref, session=session)
    worker_id = _assert_worker_identity(worker_id=body.worker_id, principal=principal)
    return run(
        lambda: runtime.agent_team.claim_task(
            task_ref=task_ref,
            worker_id=worker_id,
            lease_seconds=body.lease_seconds,
            lease_id=body.lease_ref,
            **_team_durable_task_kwargs(session),
        )
    )


@router.post(
    "/v1/agent-control/team/sessions/{session_ref}/tasks/{task_ref}/heartbeat"
)
def heartbeat_team_agent_task(
    session_ref: str,
    task_ref: str,
    body: TeamTaskHeartbeatInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    _team_task_for_session(task_ref, session_ref, session=session)
    worker_id = _assert_worker_identity(worker_id=body.worker_id, principal=principal)
    return run(
        lambda: runtime.agent_team.heartbeat_task(
            task_ref=task_ref,
            worker_id=worker_id,
            lease_seconds=body.lease_seconds,
            lease_ref=body.lease_ref,
            **_team_durable_task_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/tasks/{task_ref}/release")
def release_team_agent_task(
    session_ref: str,
    task_ref: str,
    body: TeamTaskReleaseInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    _team_task_for_session(task_ref, session_ref, session=session)
    worker_id = _assert_worker_identity(worker_id=body.worker_id, principal=principal)
    return run(
        lambda: runtime.agent_team.release_task(
            task_ref=task_ref,
            worker_id=worker_id,
            lease_ref=body.lease_ref,
            **_team_durable_task_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/tasks/{task_ref}/complete")
def complete_team_agent_task(
    session_ref: str,
    task_ref: str,
    body: TeamTaskCompleteInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    task = _team_task_for_session(task_ref, session_ref, session=session)
    worker_id = _assert_worker_identity(worker_id=body.worker_id, principal=principal)
    reviewer_id, evidence_refs = _admit_team_reviewer(
        task=task,
        session=session,
        requested_reviewer_id=body.reviewer_id,
        principal=principal,
        evidence_refs=body.evidence_refs,
    )
    return run(
        lambda: runtime.agent_team.complete_task(
            task_ref=task_ref,
            worker_id=worker_id,
            lease_ref=body.lease_ref,
            result=body.result,
            evidence_refs=evidence_refs,
            reviewer_id=reviewer_id,
            cost_units=body.cost_units,
            **_team_durable_task_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/tasks/{task_ref}/fail")
def fail_team_agent_task(
    session_ref: str,
    task_ref: str,
    body: TeamTaskFailInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "admin")
    session = _team_session_for_principal(
        session_ref,
        principal=principal,
        store_ref=store_ref,
        recover_expired_leases=True,
    )
    _team_task_for_session(task_ref, session_ref, session=session)
    worker_id = _assert_worker_identity(worker_id=body.worker_id, principal=principal)
    return run(
        lambda: runtime.agent_team.fail_task(
            task_ref=task_ref,
            worker_id=worker_id,
            lease_ref=body.lease_ref,
            failure_code=body.failure_code,
            status_code=body.status_code,
            timeout=body.timeout,
            retry_after_seconds=body.retry_after_seconds,
            **_team_durable_task_kwargs(session),
        )
    )


@router.post("/v1/agent-control/team/sessions/{session_ref}/publish")
def publish_team_agent_observations(
    session_ref: str,
    body: TeamPublishInput,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "monitor", "admin")
    session = _team_session_for_principal(
        session_ref, principal=principal, store_ref=store_ref
    )
    return run(
        lambda: runtime.agent_team_harness.publish_completed(
            session_ref=session_ref,
            project_id=body.project_id,
            verifier_id=body.verifier_id,
            verifier_version=body.verifier_version,
            principal=principal,
            **_team_durable_scope_kwargs(session),
        )
    )


def _run_query_scope(
    *,
    principal: Principal,
    store_ref: str,
    as_of: str | None,
) -> AgentRunScopeContext:
    if not principal.can_access_store(store_ref):
        raise HTTPException(404, "Governed Agent run scope not found")
    cutoff = _as_of(as_of)
    entity_scope = runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=cutoff,
    )
    if (
        entity_scope.get("status") != "ready"
        or not entity_scope.get("entity_ref")
        or not entity_scope.get("authority_sha256")
    ):
        raise HTTPException(404, "Governed Agent run scope not found")
    evidence_id = str(entity_scope.get("evidence_id") or "").strip()
    evidence_sha256 = str(entity_scope.get("evidence_sha256") or "").strip()
    evidence_refs = (
        (
            AgentRunEvidenceRef(
                evidence_id=evidence_id,
                evidence_sha256=evidence_sha256,
            ),
        )
        if evidence_id and evidence_sha256
        else ()
    )
    return AgentRunScopeContext(
        tenant_ref=principal.tenant_ref,
        entity_ref=str(entity_scope["entity_ref"]),
        store_ref=store_ref,
        authority_sha256=str(entity_scope["authority_sha256"]),
        actor_id=principal.actor_id,
        scope_as_of=cutoff,
        evidence_refs=evidence_refs,
    )


@router.get("/v1/agent-control/runs")
def governed_agent_runs(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
    status: RUN_STATUSES | None = None,
    task_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    context = _run_query_scope(
        principal=principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.governed_agent_runtime.list_runs(
            context=context,
            status=status,
            task_type=task_type,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/v1/agent-control/runs/{run_id}")
def governed_agent_run(
    run_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    context = _run_query_scope(
        principal=principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.governed_agent_runtime.get_run(
            context=context,
            run_id=run_id,
        )
    )


@router.get("/v1/agent-control/runs/{run_id}/replay")
def replay_governed_agent_run(
    run_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    context = _run_query_scope(
        principal=principal,
        store_ref=store_ref,
        as_of=as_of,
    )
    return run(
        lambda: runtime.governed_agent_runtime.replay(
            context=context,
            run_id=run_id,
        )
    )


def _as_of(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "as_of must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise HTTPException(422, "as_of must include timezone")
    return parsed.astimezone(UTC)


@router.get("/v1/agent-control/projects/{project_id}")
def agent_control_workspace(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    if store_ref:
        ensure_store_scope(principal, store_ref)
    return run(
        lambda: runtime.agent_harness.workspace(
            project_id,
            principal=principal,
            store_ref=store_ref,
            as_of=_as_of(as_of),
        )
    )


@router.get(
    "/v1/agent-control/projects/{project_id}/operating-subject"
)
def project_operating_subject(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    as_of: str | None = None,
):
    ensure_role(principal, "monitor", "admin")
    return run(
        lambda: runtime.agent_harness.operating_subject(
            project_id=project_id,
            principal=principal,
            as_of=_as_of(as_of),
        )
    )


@router.post(
    "/v1/agent-control/projects/{project_id}/operating-subject/events"
)
def record_project_operating_subject(
    project_id: str,
    body: OperatingSubjectEventInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "admin")
    return run(
        lambda: runtime.agent_harness.record_operating_subject_event(
            project_id=project_id,
            principal=principal,
            subject=runtime.authenticator.resolve_actor(
                body.subject_actor_id
            ),
            event_type=body.event_type,
            effective_at=body.effective_at,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
        )
    )


@router.get("/v1/agent-control/projects/{project_id}/graphs/{graph_kind}")
def graph_workspace(
    project_id: str,
    graph_kind: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    as_of: str | None = None,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    if graph_kind not in GRAPH_KINDS:
        raise HTTPException(404, "graph projection not found")
    if store_ref:
        ensure_store_scope(principal, store_ref)
    return run(
        lambda: runtime.agent_harness.workspace(
            project_id,
            principal=principal,
            store_ref=store_ref,
            as_of=_as_of(as_of),
            graph_kind=graph_kind,
        )
    )


@router.post("/v1/agent-control/projects/{project_id}/observe")
def observe_operating_gates(
    project_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "monitor", "admin")
    ensure_store_scope(principal, store_ref)
    return run(
        lambda: runtime.operating_gate_observer.observe(
            project_id=project_id,
            principal=principal,
            store_ref=store_ref,
        )
    )
