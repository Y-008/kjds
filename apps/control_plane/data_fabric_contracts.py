"""Provider-neutral contracts for the KJDS data fabric and analytics boundary.

These models intentionally describe transport and validation only. They do not
create a second Fact, Evidence, Profit or execution authority.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

DataStatus = Literal[
    "ready",
    "partial",
    "stale",
    "conflicted",
    "blocked",
    "no_data",
    "unknown_outcome",
]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScopeRef(_Contract):
    tenant_id: str = Field(min_length=1, max_length=160)
    entity_id: str = Field(min_length=1, max_length=160)
    store_ids: tuple[str, ...] = ()
    warehouse_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def unique_scope_ids(self) -> ScopeRef:
        for values in (self.store_ids, self.warehouse_ids):
            if len(values) != len(set(values)):
                raise ValueError("scope identifiers must be unique")
        return self


class EvidenceRef(_Contract):
    kind: Literal["evidence", "fact", "decision", "action"]
    id: str = Field(min_length=1, max_length=200)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class QualitySummary(_Contract):
    completeness: float = Field(ge=0, le=1)
    freshness: Literal["fresh", "stale", "unknown"]
    excluded_count: int = Field(default=0, ge=0)
    reasons: tuple[str, ...] = ()


class DataEnvelope(_Contract):
    dataset: str = Field(min_length=1, max_length=200)
    scope: ScopeRef
    as_of: datetime
    fresh_until: datetime | None = None
    status: DataStatus
    data: tuple[dict[str, Any], ...] = ()
    quality: QualitySummary
    lineage: tuple[EvidenceRef, ...] = ()
    schema_version: str = Field(min_length=1, max_length=80)
    authority_hash: str = Field(min_length=1, max_length=200)
    next_cursor: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> DataEnvelope:
        if self.fresh_until is not None and self.fresh_until < self.as_of:
            raise ValueError("fresh_until must not precede as_of")
        if self.status in {"no_data", "blocked", "unknown_outcome"} and self.data:
            raise ValueError(f"{self.status} envelope cannot contain data rows")
        if self.status == "ready" and self.quality.freshness != "fresh":
            raise ValueError("ready envelope requires fresh quality")
        if self.quality.excluded_count and self.status == "ready":
            raise ValueError("excluded rows require partial or a non-ready status")
        return self


class DataProductDescriptor(_Contract):
    dataset_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    owner: str = Field(min_length=1, max_length=160)
    grain: str = Field(min_length=1, max_length=160)
    source_refs: tuple[str, ...] = ()
    allowed_scopes: tuple[str, ...] = ()
    allowed_purposes: tuple[str, ...] = ()
    refresh_sla_seconds: int | None = Field(default=None, ge=1)
    quality_threshold: float = Field(ge=0, le=1)
    rebuild_method: str = Field(min_length=1, max_length=500)


class MetricDefinition(_Contract):
    metric_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    formula: str = Field(min_length=1, max_length=4000)
    fact_grain: str = Field(min_length=1, max_length=160)
    dimensions: tuple[str, ...] = ()
    aggregation: Literal["sum", "count", "distinct", "average", "median", "ratio", "weighted"]
    currency_rule: str = Field(min_length=1, max_length=500)
    evidence_required: bool = True


class PeriodRef(_Contract):
    period_type: Literal["day", "week", "month", "quarter", "year", "ytd", "rolling", "custom"]
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=80)
    currency: str = Field(min_length=3, max_length=3)
    as_of: datetime
    partial: bool = False
    closed: bool = False

    @model_validator(mode="after")
    def valid_window(self) -> PeriodRef:
        if self.end_at <= self.start_at:
            raise ValueError("period end_at must be after start_at")
        if self.as_of < self.start_at:
            raise ValueError("period as_of cannot precede period start")
        return self


class AnalysisRecipe(_Contract):
    recipe_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=80)
    scope: ScopeRef
    period: PeriodRef
    dimensions: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    filters: tuple[tuple[str, str, str], ...] = ()
    compare_with: tuple[Literal["previous_period", "same_period_last_year", "rolling"] , ...] = ()

    @model_validator(mode="after")
    def unique_query_parts(self) -> AnalysisRecipe:
        if not self.metrics:
            raise ValueError("analysis recipe requires at least one metric")
        if len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError("analysis dimensions must be unique")
        if len(self.metrics) != len(set(self.metrics)):
            raise ValueError("analysis metrics must be unique")
        return self


class ActionEnvelope(_Contract):
    command_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=240)
    scope: ScopeRef
    input_snapshot_id: str = Field(min_length=1, max_length=200)
    mode: Literal["propose", "execute"] = "propose"
    permit_ref: str | None = None
    budget_reservation_ref: str | None = None
    expected_readback: str | None = None
    rollback_ref: str | None = None

    @model_validator(mode="after")
    def require_execution_controls(self) -> ActionEnvelope:
        if self.mode == "execute":
            missing = [
                name
                for name, value in {
                    "permit_ref": self.permit_ref,
                    "budget_reservation_ref": self.budget_reservation_ref,
                    "expected_readback": self.expected_readback,
                    "rollback_ref": self.rollback_ref,
                }.items()
                if not value
            ]
            if missing:
                raise ValueError("execute ActionEnvelope missing: " + ", ".join(missing))
        return self
