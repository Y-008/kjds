"""Read-only operating control-loop projections and the decision ledger API.

The router is deliberately thin: :mod:`objective_control_loop` and
:mod:`metric_recipe_compiler` own domain validation, while the existing
``ScopeRef``, repository outbox and security middleware remain the authorities
for scope and persistence.  No endpoint in this module invokes a provider or
grants a Permit.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..api_contracts import current_principal, ensure_role, ensure_store_scope, run
from ..data_fabric_contracts import QualityStateValue, ScopeRef
from ..decision_ledger import DecisionEvent, DecisionLedger, DecisionLedgerError
from ..metric_recipe_compiler import (
    MetricFilter,
    MetricRecipe,
    MetricRecipeCompiler,
    MetricRecipeError,
)
from ..objective_control_loop import (
    MetricObservation,
    ObjectiveControlLoopError,
    ObjectiveDefinition,
    evaluate_objective,
)
from ..runtime import runtime
from ..security import Principal

router = APIRouter()

_compiler = MetricRecipeCompiler()
_ledger = DecisionLedger()
_ledger_hydration_lock = threading.RLock()
_EVENT_TYPE = "control_loop.decision"
_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "external_write",
        "finance_entry",
        "password",
        "permit",
        "private_key",
        "refresh_token",
        "secret",
    }
)


def _utc(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    try:
        normalized = value.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError(f"{field_name} is outside the supported range") from exc
    if normalized > datetime.now(UTC):
        raise ValueError(f"{field_name} cannot be in the future")
    return normalized


def _bounded_payload(value: Any, *, path: str = "$", depth: int = 0) -> Any:
    """Return a JSON-safe payload while rejecting authority and secret fields."""

    if depth > 6:
        raise ValueError("decision payload nesting is too deep")
    if isinstance(value, Mapping):
        if len(value) > 64:
            raise ValueError("decision payload has too many fields")
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip() or len(key) > 120:
                raise ValueError(f"{path} contains an invalid key")
            normalized_key = key.strip().lower().replace("-", "_")
            if normalized_key in _FORBIDDEN_PAYLOAD_KEYS:
                raise ValueError(f"{path}.{key} is not allowed")
            result[key.strip()] = _bounded_payload(item, path=f"{path}.{key}", depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 200:
            raise ValueError(f"{path} has too many items")
        return [_bounded_payload(item, path=f"{path}[]", depth=depth + 1) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        if isinstance(value, str) and len(value) > 4000:
            raise ValueError(f"{path} contains an oversized string")
        return value
    # Decimal and finite floats are serialized explicitly; NaN/Infinity are
    # rejected by the canonical JSON encoder below.
    if hasattr(value, "is_finite") and callable(value.is_finite):
        if not value.is_finite():
            raise ValueError(f"{path} must be finite")
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError(f"{path} must be finite")
        return value
    raise ValueError(f"{path} has an unsupported value type")


class ObjectiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1", min_length=1, max_length=80)
    scope: ScopeRef
    metric_id: str = Field(min_length=1, max_length=200)
    direction: Literal["maximize", "minimize"]
    target: str
    cadence: Literal["fast", "medium", "slow"]
    cooldown_seconds: int | None = Field(default=None, ge=0, le=31_536_000)
    max_change: str = "0"
    hysteresis: str = "0"
    stop_rule: Literal["never", "target_reached", "quality_invalid"] = "target_reached"
    owner: str = Field(min_length=1, max_length=200)
    rollback_rule: str = Field(min_length=1, max_length=400)

    @field_validator("objective_id", "version", "metric_id", "owner", "rollback_rule", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        return str(value).strip()


class ObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_id: str = Field(min_length=1, max_length=200)
    scope: ScopeRef
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_value: str
    quality_state: QualityStateValue
    observed_at: datetime
    evidence_refs: tuple[str, ...] = ()
    safety_event: bool = False

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        normalized = _utc(value, "observed_at")
        assert normalized is not None
        return normalized


class EvaluateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: ObjectiveRequest
    observation: ObservationRequest


class MetricRecipeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1", min_length=1, max_length=80)
    scope: ScopeRef
    metric_id: str = Field(min_length=1, max_length=200)
    metric_version: str | None = Field(default=None, max_length=80)
    dimensions: tuple[str, ...] = ()
    filters: tuple[MetricFilter, ...] = ()
    period_ref: str | None = Field(default=None, max_length=200)
    quality_states: tuple[QualityStateValue, ...] = ("VALID",)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    quality_threshold: str | None = None


class DecisionAppendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(min_length=1, max_length=120)
    decision_id: str = Field(min_length=1, max_length=200)
    scope: ScopeRef
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(min_length=1, max_length=240)
    occurred_at: datetime | None = None

    @field_validator("event_type", "decision_id", "idempotency_key", mode="before")
    @classmethod
    def normalize_identifiers(cls, value: Any) -> str:
        return str(value).strip()

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime | None) -> datetime | None:
        return _utc(value, "occurred_at")


def _authorized_scope(principal: Principal, scope: ScopeRef) -> None:
    if scope.tenant_id != principal.tenant_ref:
        raise HTTPException(status_code=403, detail="tenant is outside authorized scope")
    if len(scope.store_ids) != 1:
        raise HTTPException(status_code=422, detail="control loop requires exactly one store")
    ensure_store_scope(principal, scope.store_ids[0])


def _objective(value: ObjectiveRequest) -> ObjectiveDefinition:
    return ObjectiveDefinition(**value.model_dump())


def _observation(value: ObservationRequest) -> MetricObservation:
    return MetricObservation(**value.model_dump())


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _event_dict(event: DecisionEvent) -> dict[str, Any]:
    return event.model_dump(mode="json")


def _persist_event(event: DecisionEvent, *, principal: Principal) -> str:
    """Persist the immutable projection through the existing outbox seam."""

    repository = getattr(runtime, "repo", None)
    writer = getattr(repository, "append_event", None)
    if not callable(writer):
        raise HTTPException(status_code=503, detail="decision ledger persistence is unavailable")
    payload = {
        "contract_id": "kjds-decision-ledger-v1",
        "event": _event_dict(event),
        "external_write_allowed": False,
    }
    try:
        existing_events = repository.events_after(0) if callable(getattr(repository, "events_after", None)) else ()
        for item in existing_events:
            existing_payload = item.get("payload") if isinstance(item, Mapping) else None
            existing_event = existing_payload.get("event") if isinstance(existing_payload, Mapping) else None
            if isinstance(existing_event, Mapping) and (
                existing_event.get("event_id") == event.event_id
                or existing_event.get("idempotency_key") == event.idempotency_key
            ):
                return "already_persisted"
        writer(_EVENT_TYPE, event.decision_id, payload, actor_id=principal.actor_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="decision ledger persistence failed") from exc
    return "persisted"


def _hydrate_ledger_from_repository() -> None:
    """Restore decision events once the repository is available.

    The control-loop ledger is an in-process index over the canonical event
    outbox.  Restoring it lazily avoids import-order coupling in tests and
    startup, while ``DecisionLedger.hydrate`` verifies every persisted event
    before it can affect status, idempotency, or replay.
    """

    if len(_ledger):
        return
    repository = getattr(runtime, "repo", None)
    reader = getattr(repository, "events_after", None)
    if not callable(reader):
        return
    with _ledger_hydration_lock:
        if len(_ledger):
            return
        try:
            records = reader(0) or ()
            durable_events = []
            for record in records:
                if not isinstance(record, Mapping) or record.get("type") != _EVENT_TYPE:
                    continue
                payload = record.get("payload")
                event = payload.get("event") if isinstance(payload, Mapping) else None
                if isinstance(event, Mapping):
                    durable_events.append(event)
            if durable_events:
                _ledger.hydrate(durable_events)
        except DecisionLedgerError as exc:
            raise HTTPException(status_code=503, detail="decision ledger restoration failed") from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail="decision ledger restoration unavailable") from exc


@router.post("/v1/control-loop/objectives/evaluate")
def evaluate_control_loop(
    body: EvaluateRequest,
    principal: Annotated[Principal, Depends(current_principal)],
):
    """Evaluate a scoped objective without granting action authority."""

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    _authorized_scope(principal, body.objective.scope)
    _authorized_scope(principal, body.observation.scope)

    def project() -> dict[str, Any]:
        decision = evaluate_objective(_objective(body.objective), _observation(body.observation))
        serialized = decision.model_dump(mode="json")
        result = {
            "contract_id": "kjds-objective-control-loop-v1",
            "status": decision.status,
            "objective_id": decision.objective_id,
            "decision": serialized,
            "cadence": body.objective.cadence,
            "quality_state": body.observation.quality_state,
            "claim_level": "decision_projection",
            "projection_sha256": _hash(serialized),
            "external_write_allowed": False,
            "execution": "proposal_only",
        }
        return result

    try:
        return run(project)
    except (ObjectiveControlLoopError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v1/control-loop/metrics/compile")
def compile_control_metric(
    body: MetricRecipeRequest,
    principal: Annotated[Principal, Depends(current_principal)],
):
    """Compile one metric recipe against the versioned catalog."""

    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    _authorized_scope(principal, body.scope)

    def compile() -> dict[str, Any]:
        recipe = MetricRecipe(**body.model_dump())
        compiled = _compiler.compile(recipe)
        serialized = compiled.model_dump(mode="json")
        return {
            "contract_id": "kjds-metric-recipe-compile-v1",
            "status": "COMPILED",
            "execution": "read_only",
            "recipe": serialized["recipe"],
            "metric": serialized["metric"],
            "source_dataset": compiled.source_dataset,
            "plan_hash": compiled.plan_hash,
            "quality_state": "VALID" if "VALID" in recipe.quality_states else recipe.quality_states[0],
            "external_write_allowed": False,
        }

    try:
        return run(compile)
    except (MetricRecipeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/v1/control-loop/decisions", status_code=201)
def append_control_decision(
    body: DecisionAppendRequest,
    principal: Annotated[Principal, Depends(current_principal)],
):
    """Append one decision event and bind it to the existing outbox."""

    ensure_role(principal, "operator", "reviewer", "compliance", "admin")
    _authorized_scope(principal, body.scope)
    _hydrate_ledger_from_repository()

    def append() -> dict[str, Any]:
        try:
            payload = _bounded_payload(body.payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            event = _ledger.append(
                body.event_type,
                decision_id=body.decision_id,
                payload=payload,
                actor_id=principal.actor_id,
                idempotency_key=body.idempotency_key,
                scope=body.scope,
                occurred_at=body.occurred_at,
            )
        except DecisionLedgerError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        persistence = _persist_event(event, principal=principal)
        return {
            "contract_id": "kjds-decision-ledger-v1",
            "status": "recorded" if persistence == "persisted" else "replayed",
            "event": _event_dict(event),
            "ledger_verified": _ledger.verify(),
            "persistence": persistence,
            "external_write_allowed": False,
        }

    return run(append)


@router.get("/v1/control-loop/decisions")
def list_control_decisions(
    principal: Annotated[Principal, Depends(current_principal)],
    store_ref: str | None = None,
    decision_id: str | None = None,
    limit: int = 100,
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    if store_ref is not None:
        ensure_store_scope(principal, store_ref)
    _hydrate_ledger_from_repository()

    def read() -> dict[str, Any]:
        selected_store = store_ref
        events = []
        for event in _ledger.events(decision_id=decision_id):
            scope = event.scope
            if scope is None or scope.tenant_id != principal.tenant_ref:
                continue
            if selected_store is not None and selected_store not in scope.store_ids:
                continue
            if any(store not in principal.store_refs for store in scope.store_ids):
                continue
            events.append(_event_dict(event))
        events = events[-limit:]
        return {
            "contract_id": "kjds-decision-ledger-v1",
            "status": "VALID" if _ledger.verify() else "BLOCKED",
            "quality_state": "VALID" if _ledger.verify() else "BLOCKED",
            "count": len(events),
            "events": events,
            "ledger_length": len(_ledger),
            "ledger_verified": _ledger.verify(),
            "scope": {
                "tenant_id": principal.tenant_ref,
                "store_ref": selected_store,
            },
            "external_write_allowed": False,
        }

    return run(read)


@router.get("/v1/control-loop/status")
def control_loop_status(
    principal: Annotated[Principal, Depends(current_principal)],
):
    ensure_role(principal, "operator", "reviewer", "compliance", "admin", "monitor")
    _hydrate_ledger_from_repository()
    verified = _ledger.verify()
    return {
        "contract_id": "kjds-control-loop-status-v1",
        "status": "VALID" if verified else "BLOCKED",
        "quality_state": "VALID" if verified else "BLOCKED",
        "objective_contract": "kjds-objective-control-loop-v1",
        "metric_contract": "kjds-metric-recipe-compile-v1",
        "decision_contract": "kjds-decision-ledger-v1",
        "ledger_length": len(_ledger),
        "ledger_verified": verified,
        "execution": "proposal_only",
        "external_write_allowed": False,
    }


__all__ = [
    "router",
    "evaluate_control_loop",
    "compile_control_metric",
    "append_control_decision",
    "list_control_decisions",
    "control_loop_status",
]
