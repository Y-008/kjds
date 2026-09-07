"""Deterministic, read-only objective control loop.

The loop turns one scoped objective and one observed metric into an immutable
decision projection.  It never reads providers, persists facts, grants a
permit, or executes a connector action; callers hand the projection to the
existing approval/permit/readback chain when a later stage is authorized.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .data_fabric_contracts import QualityStateValue, ScopeRef

Cadence = Literal["fast", "medium", "slow"]
ObjectiveDirection = Literal["maximize", "minimize"]
DecisionStatus = Literal["PROPOSED", "HOLD", "STOPPED"]
DecisionAction = Literal["increase", "decrease", "hold", "stop"]

_CADENCE_SECONDS = {"fast": 900, "medium": 3600, "slow": 86400}


def _decimal(value: Any, field_name: str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return result


def _utc(value: Any, field_name: str) -> datetime:
    parsed = value
    if isinstance(parsed, str):
        parsed = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_canonical(item) for item in value]
    return value


class ObjectiveControlLoopError(ValueError):
    """Raised when an objective or observation violates loop invariants."""


class ObjectiveDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1", min_length=1, max_length=80)
    scope: ScopeRef
    metric_id: str = Field(min_length=1, max_length=200)
    direction: ObjectiveDirection
    target: Decimal
    cadence: Cadence
    cooldown_seconds: int | None = Field(default=None, ge=0)
    max_change: Decimal = Field(default=Decimal("0"), ge=0)
    hysteresis: Decimal = Field(default=Decimal("0"), ge=0)
    stop_rule: Literal["never", "target_reached", "quality_invalid"] = "target_reached"
    owner: str = Field(min_length=1, max_length=200)
    rollback_rule: str = Field(min_length=1, max_length=400)

    @field_validator("objective_id", "version", "metric_id", "owner", "rollback_rule", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        result = str(value).strip()
        if not result:
            raise ValueError("objective identifiers cannot be blank")
        return result

    @field_validator("target", "max_change", "hysteresis", mode="before")
    @classmethod
    def normalize_decimal(cls, value: Any, info: Any) -> Decimal:
        return _decimal(value, info.field_name)

    @model_validator(mode="after")
    def validate_change(self) -> ObjectiveDefinition:
        if self.max_change == 0:
            raise ValueError("max_change must be positive")
        return self

    @property
    def cooldown(self) -> int:
        return self.cooldown_seconds if self.cooldown_seconds is not None else _CADENCE_SECONDS[self.cadence]


class MetricObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objective_id: str = Field(min_length=1, max_length=200)
    scope: ScopeRef
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_value: Decimal
    quality_state: QualityStateValue
    observed_at: datetime
    evidence_refs: tuple[str, ...] = ()
    safety_event: bool = False

    @field_validator("observed_value", mode="before")
    @classmethod
    def normalize_observed_value(cls, value: Any) -> Decimal:
        return _decimal(value, "observed_value")

    @field_validator("observed_at", mode="before")
    @classmethod
    def normalize_observed_at(cls, value: Any) -> datetime:
        return _utc(value, "observed_at")

    @field_validator("evidence_refs", mode="before")
    @classmethod
    def normalize_refs(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = (value,)
        result = tuple(str(item).strip() for item in value)
        if any(not item for item in result):
            raise ValueError("evidence references cannot be blank")
        if len(result) != len(set(result)):
            raise ValueError("evidence references must be unique")
        return result


class ControlDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str
    objective_id: str
    status: DecisionStatus
    action: DecisionAction
    delta: Decimal
    reason: str
    scope: ScopeRef
    snapshot_sha256: str
    observed_at: datetime
    evidence_refs: tuple[str, ...]
    external_write_allowed: Literal[False] = False
    decision_hash: str


def evaluate_objective(
    objective: ObjectiveDefinition | Mapping[str, Any],
    observation: MetricObservation | Mapping[str, Any],
    *,
    previous: ControlDecision | None = None,
) -> ControlDecision:
    """Evaluate one observation without granting execution authority."""

    obj = objective if isinstance(objective, ObjectiveDefinition) else ObjectiveDefinition.model_validate(objective)
    obs = observation if isinstance(observation, MetricObservation) else MetricObservation.model_validate(observation)
    if obs.objective_id != obj.objective_id:
        raise ObjectiveControlLoopError("observation objective_id does not match objective")
    if obs.scope != obj.scope:
        raise ObjectiveControlLoopError("observation scope does not match objective scope")
    if previous is not None and previous.scope != obj.scope:
        raise ObjectiveControlLoopError("previous decision scope does not match objective scope")

    gap = obj.target - obs.observed_value if obj.direction == "maximize" else obs.observed_value - obj.target
    target_reached = gap <= obj.hysteresis
    if obj.stop_rule == "target_reached" and target_reached:
        status: DecisionStatus = "STOPPED"
        action: DecisionAction = "stop"
        delta = Decimal("0")
        reason = "target_reached_within_hysteresis"
    elif obj.stop_rule == "quality_invalid" and obs.quality_state != "VALID":
        status, action, delta, reason = "STOPPED", "stop", Decimal("0"), "quality_invalid"
    elif obs.quality_state != "VALID":
        status, action, delta, reason = "HOLD", "hold", Decimal("0"), f"quality_{obs.quality_state.lower()}"
    elif previous is not None and not obs.safety_event:
        elapsed = (obs.observed_at - previous.observed_at).total_seconds()
        if elapsed < obj.cooldown:
            status, action, delta, reason = "HOLD", "hold", Decimal("0"), "cooldown_active"
        else:
            status, action, delta, reason = _propose(obj, gap)
    else:
        status, action, delta, reason = _propose(obj, gap)

    basis = {
        "objective": obj,
        "observation": obs,
        "previous_decision_hash": previous.decision_hash if previous else None,
        "status": status,
        "action": action,
        "delta": delta,
        "reason": reason,
        "external_write_allowed": False,
    }
    digest = hashlib.sha256(json.dumps(_canonical(basis), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ControlDecision(
        decision_id=f"decision:{obj.objective_id}:{obs.snapshot_sha256[:16]}",
        objective_id=obj.objective_id,
        status=status,
        action=action,
        delta=delta,
        reason=reason,
        scope=obj.scope,
        snapshot_sha256=obs.snapshot_sha256,
        observed_at=obs.observed_at,
        evidence_refs=obs.evidence_refs,
        decision_hash=digest,
    )


def _propose(obj: ObjectiveDefinition, gap: Decimal) -> tuple[DecisionStatus, DecisionAction, Decimal, str]:
    if gap <= obj.hysteresis:
        return "HOLD", "hold", Decimal("0"), "within_hysteresis"
    delta = min(abs(gap), obj.max_change)
    if obj.direction == "maximize":
        return "PROPOSED", "increase", delta, "below_target"
    return "PROPOSED", "decrease", delta, "above_target"


__all__ = [
    "ControlDecision",
    "DecisionAction",
    "DecisionStatus",
    "MetricObservation",
    "ObjectiveControlLoopError",
    "ObjectiveDefinition",
    "evaluate_objective",
]
