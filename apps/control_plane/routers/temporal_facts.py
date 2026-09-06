from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..runtime import runtime
from ..security import Principal
from ..temporal_fact_store import LineageRef, QualityState, ScopeRef

router = APIRouter()


class RestateFactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_ref: str = Field(min_length=1, max_length=160)
    store_ref: str = Field(default="ozon-primary", min_length=1, max_length=160)
    payload: dict[str, Any]
    correction_reason: str = Field(min_length=1, max_length=2000)
    observed_time: datetime | None = None
    event_time: datetime | None = None
    effective_time: datetime | None = None
    settled_time: datetime | None = None
    fresh_until: datetime | None = None
    quality_state: QualityState | None = None
    lineage: list[LineageRef] | None = None
    source_version: str | None = Field(default=None, min_length=1, max_length=120)
    causation_id: str | None = Field(default=None, max_length=300)
    correlation_id: str | None = Field(default=None, max_length=300)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=300)
    metadata: dict[str, Any] | None = None
    created_by: str | None = Field(default=None, min_length=1, max_length=160)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(422, "as_of must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise HTTPException(422, "as_of must include timezone")
    return parsed.astimezone(UTC)


def _scope(principal: Principal, entity_ref: str, store_ref: str) -> ScopeRef:
    ensure_store_scope(principal, store_ref)
    if not entity_ref.strip():
        raise HTTPException(422, "entity_ref is required")
    return ScopeRef(tenant_id=principal.tenant_ref, entity_id=entity_ref, store_ids=(store_ref,))


@router.get("/v1/facts/as-of")
def facts_as_of(
    principal: Annotated[Principal, Depends(current_principal)],
    entity_ref: str,
    store_ref: str = "ozon-primary",
    fact_type: str | None = None,
    as_of: str | None = None,
    include_stale: bool = True,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    scope = _scope(principal, entity_ref, store_ref)
    cutoff = _timestamp(as_of)

    def query():
        result = runtime.temporal_fact_store.query_as_of(
            cutoff,
            scope=scope,
            fact_type=fact_type,
            include_stale=include_stale,
        )
        status_map = {
            QualityState.VALID: "ready",
            QualityState.PARTIAL: "partial",
            QualityState.STALE: "stale",
            QualityState.BLOCKED: "blocked",
            QualityState.NO_DATA: "no_data",
            QualityState.UNKNOWN_OUTCOME: "unknown_outcome",
        }
        envelope = result.to_data_envelope(
            dataset="temporal.facts.v1",
            scope=scope,
            authority_hash="temporal-fact-store",
        )
        return {
            "status": status_map[result.quality_state],
            "quality_state": result.quality_state.value,
            "as_of": cutoff.isoformat(),
            "facts": [item.model_dump(mode="json") for item in result.items],
            "quality": envelope.quality.model_dump(mode="json"),
            "data_envelope": envelope.model_dump(mode="json"),
        }

    return run(query)


@router.get("/v1/facts/{fact_id}/versions")
def fact_versions(
    fact_id: str,
    principal: Annotated[Principal, Depends(current_principal)],
    entity_ref: str,
    store_ref: str = "ozon-primary",
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    scope = _scope(principal, entity_ref, store_ref)
    def query():
        rows = runtime.temporal_fact_store.history(fact_id)
        if any(row.scope != scope for row in rows):
            raise PermissionError("fact is outside authorized scope")
        return {"fact_id": fact_id, "versions": [row.model_dump(mode="json") for row in rows]}
    return run(query)


@router.post("/v1/facts/{fact_id}/restate")
def restate_fact(
    fact_id: str,
    body: RestateFactInput,
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "admin")
    scope = _scope(principal, body.entity_ref, body.store_ref)
    def mutate():
        current = runtime.temporal_fact_store.get(fact_id)
        if current.scope != scope:
            raise PermissionError("fact is outside authorized scope")
        updated = runtime.temporal_fact_store.restate(
            fact_id,
            body.payload,
            correction_reason=body.correction_reason,
            observed_time=body.observed_time,
            event_time=body.event_time,
            effective_time=body.effective_time,
            settled_time=body.settled_time,
            fresh_until=body.fresh_until,
            quality_state=body.quality_state,
            lineage=body.lineage,
            source_version=body.source_version,
            causation_id=body.causation_id,
            correlation_id=body.correlation_id,
            idempotency_key=body.idempotency_key,
            metadata=body.metadata,
            created_by=body.created_by,
        )
        return updated.model_dump(mode="json")
    return run(mutate)
