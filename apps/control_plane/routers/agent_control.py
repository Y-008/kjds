from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException

from ..agent_harness import GRAPH_KINDS
from ..agent_runtime import AgentRunEvidenceRef, AgentRunScopeContext
from ..api_contracts import (
    OperatingSubjectEventInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..runtime import runtime
from ..security import Principal

router = APIRouter()

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
