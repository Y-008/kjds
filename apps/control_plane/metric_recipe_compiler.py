"""Pure, deterministic compilation of metric recipes.

The compiler deliberately stops at a read-only plan.  It does not query a
provider, persist a recipe, or grant authority to execute an action.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from .data_fabric_contracts import MetricDefinition, QualityStateValue, ScopeRef

_QUALITY_STATES = frozenset(
    {"VALID", "PARTIAL", "STALE", "BLOCKED", "NO_DATA", "UNKNOWN_OUTCOME"}
)
_FILTER_OPERATORS = frozenset({"=", "!=", "<", "<=", ">", ">=", "in", "not_in"})


def _finite_decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field_name} must be finite")
    return parsed


class MetricRecipeError(ValueError):
    """Raised when a recipe cannot be compiled into a safe read-only plan."""


class MetricFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str = Field(min_length=1, max_length=160)
    operator: str = Field(min_length=1, max_length=20)
    value: str | int | Decimal | tuple[str, ...]

    @field_validator("field", mode="before")
    @classmethod
    def normalize_field(cls, value: Any) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("metric filter field cannot be blank")
        return normalized

    @field_validator("operator", mode="before")
    @classmethod
    def normalize_operator(cls, value: Any) -> str:
        normalized = str(value).strip().lower()
        if normalized not in _FILTER_OPERATORS:
            raise ValueError("metric filter operator is unsupported")
        return normalized

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, value: Any) -> Any:
        if isinstance(value, (list, set, frozenset)):
            result = tuple(str(item).strip() for item in value)
            if not result or any(not item for item in result):
                raise ValueError("metric filter values cannot be blank")
            return result
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("metric filter value cannot be blank")
            return value
        if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            return _finite_decimal(value, "metric filter value")
        raise ValueError("metric filter value must be scalar or a string sequence")


class MetricRecipe(BaseModel):
    """A versioned, scope-bound description of one metric read."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    recipe_id: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1", min_length=1, max_length=80)
    scope: ScopeRef
    metric_id: str = Field(
        validation_alias=AliasChoices("metric_id", "metric", "metric_ref"),
        min_length=1,
        max_length=200,
    )
    metric_version: str | None = Field(default=None, min_length=1, max_length=80)
    dimensions: tuple[str, ...] = ()
    filters: tuple[MetricFilter, ...] = ()
    period_ref: str | None = Field(default=None, max_length=200)
    quality_states: tuple[QualityStateValue, ...] = ("VALID",)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    # A recipe may carry an explicit threshold for callers that need a
    # numeric quality gate; it is data, not an execution permission.
    quality_threshold: Decimal | None = None

    @field_validator("recipe_id", "version", "metric_id", mode="before")
    @classmethod
    def normalize_identifiers(cls, value: Any) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("metric recipe identifiers cannot be blank")
        return normalized

    @field_validator("dimensions", mode="before")
    @classmethod
    def normalize_dimensions(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = (value,)
        result = tuple(str(item).strip() for item in value)
        if any(not item for item in result):
            raise ValueError("metric dimensions cannot be blank")
        return result

    @field_validator("quality_states", mode="before")
    @classmethod
    def normalize_quality_states(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            value = (value,)
        result = tuple(str(item).strip().upper().replace("-", "_") for item in value)
        if not result or any(item not in _QUALITY_STATES for item in result):
            raise ValueError("metric recipe quality state is invalid")
        return result

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
            raise ValueError("metric recipe currency must be a three-letter code")
        return normalized

    @field_validator("quality_threshold", mode="before")
    @classmethod
    def normalize_threshold(cls, value: Any) -> Decimal | None:
        return None if value is None else _finite_decimal(value, "quality_threshold")

    @model_validator(mode="after")
    def validate_recipe(self) -> MetricRecipe:
        if len(self.dimensions) != len(set(self.dimensions)):
            raise ValueError("metric recipe dimensions must be unique")
        if len(self.quality_states) != len(set(self.quality_states)):
            raise ValueError("metric recipe quality states must be unique")
        if self.quality_threshold is not None and not Decimal("0") <= self.quality_threshold <= Decimal("1"):
            raise ValueError("quality_threshold must be between 0 and 1")
        return self


class CompiledMetricRecipe(BaseModel):
    """The immutable result of compilation, suitable for a decision record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution: Literal["read_only"] = "read_only"
    recipe: MetricRecipe
    metric: MetricDefinition
    source_dataset: str
    plan_hash: str = Field(min_length=64, max_length=64)


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


def _default_catalog() -> tuple[MetricDefinition, ...]:
    # Import lazily so this contract remains cheap and has no import cycle for
    # callers that supply their own catalog.
    from .analytics_query_plan import DEFAULT_METRIC_CATALOG

    return DEFAULT_METRIC_CATALOG


def _dataset_for(metric_id: str) -> str:
    if metric_id in {"units_sold", "net_sales"}:
        return "orders.canonical.v1"
    if metric_id in {"cm3", "realized_profit", "risk_adjusted_profit"}:
        return "profit.cm3.v1"
    if metric_id in {"observed_demand", "censored_demand", "lost_sales_estimate", "stockout_interval", "stockout_interval_days"}:
        return "demand.censoring.v1"
    if metric_id == "cash_locked":
        return "inventory.snapshot.v1"
    return f"metric.{metric_id}.v{1}"


class MetricRecipeCompiler:
    """Compile recipes against a versioned metric catalog."""

    def __init__(self, *, catalog: Sequence[MetricDefinition] | None = None) -> None:
        self.catalog = tuple(catalog) if catalog is not None else _default_catalog()
        ids = [item.metric_id for item in self.catalog]
        if len(ids) != len(set(ids)):
            raise MetricRecipeError("metric catalog contains duplicate metric ids")

    def compile(self, recipe: MetricRecipe | Mapping[str, Any]) -> CompiledMetricRecipe:
        candidate = recipe if isinstance(recipe, MetricRecipe) else MetricRecipe.model_validate(recipe)
        metric = next((item for item in self.catalog if item.metric_id == candidate.metric_id), None)
        if metric is None:
            raise MetricRecipeError(f"unknown metric: {candidate.metric_id}")
        if candidate.metric_version is not None and candidate.metric_version != metric.version:
            raise MetricRecipeError(
                f"metric version mismatch: expected {metric.version}, got {candidate.metric_version}"
            )
        unsupported = sorted(set(candidate.dimensions) - set(metric.dimensions))
        if unsupported:
            raise MetricRecipeError(
                "dimensions unsupported by metric: " + ", ".join(unsupported)
            )
        if candidate.currency is not None and metric.currency_rule == "not_applicable":
            raise MetricRecipeError("currency is not applicable to this metric")
        for item in candidate.filters:
            if item.operator in {"in", "not_in"} and not isinstance(item.value, tuple):
                raise MetricRecipeError(f"filter {item.field} requires a sequence value")
        canonical = _canonical(
            {
                "execution": "read_only",
                "recipe": candidate,
                "metric": metric,
                "source_dataset": _dataset_for(metric.metric_id),
            }
        )
        plan_hash = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return CompiledMetricRecipe(
            recipe=candidate,
            metric=metric,
            source_dataset=_dataset_for(metric.metric_id),
            plan_hash=plan_hash,
        )


def compile_metric_recipe(
    recipe: MetricRecipe | Mapping[str, Any],
    *,
    catalog: Sequence[MetricDefinition] | None = None,
) -> CompiledMetricRecipe:
    """Functional entry point for callers that do not need a compiler object."""

    return MetricRecipeCompiler(catalog=catalog).compile(recipe)


__all__ = [
    "CompiledMetricRecipe",
    "MetricFilter",
    "MetricRecipe",
    "MetricRecipeCompiler",
    "MetricRecipeError",
    "compile_metric_recipe",
]
