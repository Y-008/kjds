from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..api_contracts import (
    AgentArtifactFeedbackInput,
    AiListingRunCancelInput,
    AiListingRunCreateInput,
    AiListingRunPreflightInput,
    AiListingRunResumeInput,
    current_principal,
    ensure_role,
    ensure_store_scope,
    run,
)
from ..runtime import runtime
from ..security import Principal

router = APIRouter()


def _cutoff(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="as_of must be an ISO-8601 timestamp") from exc
    if result.tzinfo is None:
        raise HTTPException(status_code=422, detail="as_of must include a timezone")
    result = result.astimezone(UTC)
    if result > datetime.now(UTC):
        raise HTTPException(status_code=422, detail="as_of cannot be in the future")
    return result


def _scope(principal: Principal, *, store_ref: str, as_of: datetime) -> dict:
    ensure_store_scope(principal, store_ref)
    return runtime.scope_grants.current(
        principal=principal,
        store_ref=store_ref,
        as_of=as_of,
    )


@router.post("/v1/ai-listing/runs/preflight")
def preflight_ai_listing(
    body: AiListingRunPreflightInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    cutoff = _cutoff(body.as_of)
    entity_scope = _scope(principal, store_ref=body.store_ref, as_of=cutoff)
    return run(
        lambda: runtime.ai_listing.preflight(
            **body.model_dump(exclude={"as_of"}),
            as_of=cutoff,
            principal=principal,
            entity_scope=entity_scope,
        )
    )


@router.post("/v1/ai-listing/runs", status_code=202)
def create_ai_listing_run(
    body: AiListingRunCreateInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff = _cutoff(body.as_of)
    entity_scope = _scope(principal, store_ref=body.store_ref, as_of=cutoff)
    return run(
        lambda: runtime.ai_listing.create(
            **body.model_dump(exclude={"as_of"}),
            as_of=cutoff,
            principal=principal,
            entity_scope=entity_scope,
        )
    )


@router.get("/v1/ai-listing/runs")
def list_ai_listing_runs(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff = _cutoff(None)
    entity_scope = _scope(principal, store_ref=store_ref, as_of=cutoff)
    return run(
        lambda: runtime.ai_listing.list(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            limit=limit,
        )
    )


@router.get("/v1/ai-listing/runs/{run_id}")
def get_ai_listing_run(
    run_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str = "ozon-primary",
):
    ensure_role(
        principal,
        "operator",
        "reviewer",
        "compliance",
        "approver",
        "risk",
        "monitor",
        "admin",
    )
    cutoff = _cutoff(None)
    entity_scope = _scope(principal, store_ref=store_ref, as_of=cutoff)
    return run(
        lambda: runtime.ai_listing.get(
            run_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
    )


@router.post("/v1/ai-listing/runs/{run_id}/resume", status_code=202)
def resume_ai_listing_run(
    run_id: str,
    body: AiListingRunResumeInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff = _cutoff(None)
    entity_scope = _scope(principal, store_ref=body.store_ref, as_of=cutoff)
    return run(
        lambda: runtime.ai_listing.resume(
            run_id,
            bindings=body.bindings,
            idempotency_key=body.idempotency_key,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
        )
    )


@router.post("/v1/ai-listing/runs/{run_id}/cancel")
def cancel_ai_listing_run(
    run_id: str,
    body: AiListingRunCancelInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    cutoff = _cutoff(None)
    entity_scope = _scope(principal, store_ref=body.store_ref, as_of=cutoff)
    return run(
        lambda: runtime.ai_listing.cancel(
            run_id,
            reason=body.reason,
            idempotency_key=body.idempotency_key,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
        )
    )


@router.post("/v1/ai-listing/artifacts/{artifact_id}/feedback", status_code=201)
def record_ai_listing_artifact_feedback(
    artifact_id: str,
    body: AgentArtifactFeedbackInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    cutoff = _cutoff(None)
    entity_scope = _scope(principal, store_ref=body.store_ref, as_of=cutoff)

    def feedback():
        artifact = runtime.agent_inference.get_artifact(artifact_id)
        if not artifact.ai_listing_run_id:
            raise ValueError("Artifact is not associated with an AI Listing run")
        runtime.ai_listing.get(
            artifact.ai_listing_run_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=body.store_ref,
        )
        updated = runtime.agent_inference.feedback(
            artifact_id=artifact_id,
            verdict=body.verdict,
            notes=body.notes,
            actor_id=principal.actor_id,
            edited_output=body.edited_output,
            idempotency_key=body.idempotency_key,
        )
        return updated.to_dict()

    return run(feedback)
