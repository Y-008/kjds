"""Compile validated analytics recipes into deterministic read-only plans."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field

from .data_fabric_contracts import (
    AnalysisRecipe,
    DataProductDescriptor,
    MetricDefinition,
    PeriodRef,
    ScopeRef,
)


class AnalyticsQueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution: str = "read_only"
    recipe_id: str = Field(min_length=1)
    scope: dict[str, Any]
    period: dict[str, Any]
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    filters: tuple[tuple[str, str, str], ...]
    compare_with: tuple[str, ...]
    source_datasets: tuple[str, ...]
    metric_versions: dict[str, str]
    plan_hash: str = Field(min_length=64, max_length=64)


DEFAULT_METRIC_CATALOG: tuple[MetricDefinition, ...] = (
    MetricDefinition(
        metric_id="units_sold",
        version="1",
        name="Units sold",
        formula="sum(order_line.quantity)",
        fact_grain="order_line",
        dimensions=("store", "category", "sku", "month"),
        aggregation="sum",
        currency_rule="not_applicable",
    ),
    MetricDefinition(
        metric_id="net_sales",
        version="1",
        name="Net sales",
        formula="gross_sales - discount - refund",
        fact_grain="order_line",
        dimensions=("store", "category", "sku", "month"),
        aggregation="sum",
        currency_rule="source_currency",
    ),
    MetricDefinition(
        metric_id="cm3",
        version="1",
        name="CM3",
        formula="net_sales - full_cost",
        fact_grain="sku_store_period",
        dimensions=("store", "category", "price_band", "sku", "month"),
        aggregation="sum",
        currency_rule="explicit_fx_snapshot",
    ),
    MetricDefinition(
        metric_id="cash_locked",
        version="1",
        name="Cash locked in inventory",
        formula="inventory_value.available + inventory_value.in_transit",
        fact_grain="sku_warehouse_time",
        dimensions=("store", "warehouse", "category", "sku", "month"),
        aggregation="sum",
        currency_rule="explicit_fx_snapshot",
    ),
    MetricDefinition(
        metric_id="observed_demand",
        version="1",
        name="Observed demand",
        formula="sum(demand.observed_units)",
        fact_grain="sku_store_period",
        dimensions=("store", "category", "sku", "month"),
        aggregation="sum",
        currency_rule="not_applicable",
    ),
    MetricDefinition(
        metric_id="censored_demand",
        version="1",
        name="Censored demand estimate",
        formula="sum(demand.censored_units)",
        fact_grain="sku_store_period",
        dimensions=("store", "category", "sku", "month"),
        aggregation="sum",
        currency_rule="not_applicable",
    ),
    MetricDefinition(
        metric_id="lost_sales_estimate",
        version="1",
        name="Lost sales estimate",
        formula="sum(demand.lost_sales_units)",
        fact_grain="sku_store_period",
        dimensions=("store", "category", "sku", "month"),
        aggregation="sum",
        currency_rule="not_applicable",
    ),
    MetricDefinition(
        metric_id="realized_profit",
        version="1",
        name="Realized profit",
        formula="sum(settled_profit)",
        fact_grain="order_store_period",
        dimensions=("store", "category", "sku", "month"),
        aggregation="sum",
        currency_rule="explicit_fx_snapshot",
    ),
    MetricDefinition(
        metric_id="risk_adjusted_profit",
        version="1",
        name="Risk-adjusted profit",
        formula="realized_profit - expected_return_cost - chargeback_reserve + recovery_amount - reopened_settlement",
        fact_grain="order_store_period",
        dimensions=("store", "category", "sku", "month"),
        aggregation="sum",
        currency_rule="explicit_fx_snapshot",
    ),
)


class AnalyticsQueryPlanError(ValueError):
    """Raised when a recipe cannot be compiled safely."""


def compile_query_plan(
    recipe: AnalysisRecipe,
    *,
    catalog: tuple[MetricDefinition, ...] = DEFAULT_METRIC_CATALOG,
) -> AnalyticsQueryPlan:
    definitions = {metric.metric_id: metric for metric in catalog}
    unknown_metrics = sorted(set(recipe.metrics) - definitions.keys())
    if unknown_metrics:
        raise AnalyticsQueryPlanError(
            "unknown metrics: " + ", ".join(unknown_metrics)
        )

    unsupported_dimensions = sorted(
        {
            dimension
            for metric_id in recipe.metrics
            for dimension in recipe.dimensions
            if dimension not in definitions[metric_id].dimensions
        }
    )
    if unsupported_dimensions:
        raise AnalyticsQueryPlanError(
            "dimensions unsupported by selected metrics: "
            + ", ".join(unsupported_dimensions)
        )

    source_datasets = tuple(
        sorted(
            {
                "profit.cm3.v1" if metric_id in {"cm3", "realized_profit", "risk_adjusted_profit"}
                else "orders.canonical.v1" if metric_id in {"units_sold", "net_sales"}
                else "demand.censoring.v1" if metric_id in {"observed_demand", "censored_demand", "lost_sales_estimate"}
                else "inventory.snapshot.v1"
                for metric_id in recipe.metrics
            }
        )
    )
    metric_versions = {
        metric_id: definitions[metric_id].version for metric_id in recipe.metrics
    }
    canonical = {
        "execution": "read_only",
        "recipe_id": recipe.recipe_id,
        "scope": recipe.scope.model_dump(mode="json"),
        "period": recipe.period.model_dump(mode="json"),
        "dimensions": recipe.dimensions,
        "metrics": recipe.metrics,
        "filters": recipe.filters,
        "compare_with": recipe.compare_with,
        "source_datasets": source_datasets,
        "metric_versions": metric_versions,
    }
    plan_hash = hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
    return AnalyticsQueryPlan(**canonical, plan_hash=plan_hash)


# ``QualityState`` lives in the temporal fact adapter.  Keeping the executor's
# public values as strings avoids making the query-plan module depend on either
# the in-memory or SQL adapter while preserving the same wire vocabulary.
QUALITY_STATES = (
    "NO_DATA",
    "PARTIAL",
    "STALE",
    "BLOCKED",
    "UNKNOWN_OUTCOME",
    "VALID",
)
_TERMINAL_QUALITY = frozenset({"NO_DATA", "BLOCKED", "UNKNOWN_OUTCOME"})
_QUALITY_PRIORITY = {
    "VALID": 0,
    "PARTIAL": 1,
    "STALE": 2,
    "NO_DATA": 3,
    "UNKNOWN_OUTCOME": 4,
    "BLOCKED": 5,
}


@dataclass(frozen=True, slots=True)
class AnalyticsExecutionResult:
    """Deterministic read-only result for one compiled analytics recipe.

    Numeric values are serialized as decimal strings at the boundary.  Quality
    and value fields are deliberately independent: a valid zero is retained,
    while an unavailable value is represented by an excluded row/reason rather
    than by a fabricated zero.
    """

    status: str
    quality_state: str
    scope: dict[str, Any]
    period: dict[str, Any]
    metrics: tuple[str, ...]
    aggregates: tuple[dict[str, Any], ...]
    included_count: int
    excluded_count: int
    excluded_rows: tuple[dict[str, Any], ...]
    source_watermarks: dict[str, str]
    data_product_gate: dict[str, Any]
    result_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "quality_state": self.quality_state,
            "scope": self.scope,
            "period": self.period,
            "metrics": list(self.metrics),
            "aggregates": list(self.aggregates),
            "included_count": self.included_count,
            "excluded_count": self.excluded_count,
            "excluded_rows": list(self.excluded_rows),
            "source_watermarks": dict(self.source_watermarks),
            "data_product_gate": self.data_product_gate,
            "result_hash": self.result_hash,
        }


def _canonical_hash(value: Any) -> str:
    """Hash JSON-safe values without allowing NaN/Infinity into a result."""

    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AnalyticsQueryPlanError("analytics result is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def _as_descriptor(value: Any) -> DataProductDescriptor | None:
    if isinstance(value, DataProductDescriptor):
        return value
    if isinstance(value, Mapping):
        try:
            return DataProductDescriptor.model_validate(value)
        except (TypeError, ValueError):
            return None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return DataProductDescriptor.model_validate(model_dump(mode="python"))
        except (TypeError, ValueError):
            return None
    return None


def _product_map(products: Mapping[str, Any] | Sequence[Any] | None) -> dict[str, DataProductDescriptor]:
    if products is None:
        return {}
    values = products.items() if isinstance(products, Mapping) else ((None, item) for item in products)
    result: dict[str, DataProductDescriptor] = {}
    for key, value in values:
        descriptor = _as_descriptor(value)
        if descriptor is None:
            continue
        result[descriptor.dataset_id] = descriptor
        if key is not None and str(key) != descriptor.dataset_id:
            # A mapping key is only an index convenience; never let it create
            # a second identity for the descriptor itself.
            result.setdefault(str(key), descriptor)
    return result


def _scope_tokens(scope: ScopeRef) -> frozenset[str]:
    stores = ",".join(scope.store_ids)
    warehouses = ",".join(scope.warehouse_ids)
    return frozenset(
        {
            f"{scope.tenant_id}:{scope.entity_id}",
            f"{scope.tenant_id}:{scope.entity_id}:{stores}",
            f"{scope.tenant_id}:{scope.entity_id}:{stores}:{warehouses}",
            f"{scope.tenant_id}/{scope.entity_id}/{stores}",
        }
    )


def _scope_model(value: ScopeRef | Mapping[str, Any]) -> ScopeRef:
    """Normalize the wire-shaped plan scope to the canonical scope contract."""

    if isinstance(value, ScopeRef):
        return value
    try:
        return ScopeRef.model_validate(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsQueryPlanError("analytics plan scope is invalid") from exc


def _period_model(value: PeriodRef | Mapping[str, Any]) -> PeriodRef:
    """Normalize the wire-shaped plan period to the canonical period contract."""

    if isinstance(value, PeriodRef):
        return value
    try:
        return PeriodRef.model_validate(value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsQueryPlanError("analytics plan period is invalid") from exc


def evaluate_data_product_gate(
    plan: AnalyticsQueryPlan,
    products: Mapping[str, Any] | Sequence[Any] | None,
    *,
    purpose: str = "analytics",
) -> dict[str, Any]:
    """Check that every source dataset is a verified, scoped product.

    Registry entries marked ``contract_only`` or ``deprecated`` remain visible
    as metadata but cannot feed a numeric projection.  Optional scope/purpose
    restrictions are enforced when present; an empty restriction means the
    registry has not declared one yet and does not silently invent a mismatch.
    """

    descriptors = _product_map(products)
    scope = _scope_model(plan.scope)
    rows: list[dict[str, Any]] = []
    reasons: list[str] = []
    for dataset_id in plan.source_datasets:
        descriptor = descriptors.get(dataset_id)
        if descriptor is None:
            status = "UNKNOWN"
            reason = "data_product_missing"
            rows.append({"dataset_id": dataset_id, "status": status, "reason": reason})
            reasons.append(f"{dataset_id}:{reason}")
            continue
        reason: str | None = None
        if descriptor.status != "verified":
            reason = f"data_product_{descriptor.status}"
        elif not descriptor.authority or descriptor.authority.strip().lower() in {"unknown", "unverified"}:
            reason = "data_product_authority_unverified"
        elif descriptor.allowed_purposes and purpose not in set(descriptor.allowed_purposes):
            reason = "data_product_purpose_not_allowed"
        elif descriptor.allowed_scopes and not (_scope_tokens(scope) & set(descriptor.allowed_scopes)):
            reason = "data_product_scope_not_allowed"
        status = "VERIFIED" if reason is None else "BLOCKED"
        row = {
            "dataset_id": dataset_id,
            "status": status,
            "version": descriptor.version,
            "authority": descriptor.authority,
        }
        if reason is not None:
            row["reason"] = reason
            reasons.append(f"{dataset_id}:{reason}")
        rows.append(row)
    status = "VERIFIED" if not reasons and rows else "BLOCKED"
    document = {
        "contract_id": "kjds-analytics-data-product-gate-v1",
        "purpose": purpose,
        "scope": scope.model_dump(mode="json"),
        "source_datasets": list(plan.source_datasets),
        "products": rows,
        "status": status,
        "reasons": sorted(set(reasons)),
    }
    return {
        "contract_id": document["contract_id"],
        "purpose": purpose,
        "status": status,
        "verified": status == "VERIFIED",
        "products": rows,
        "reasons": sorted(set(reasons)),
        "gate_hash": _canonical_hash(document),
    }


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AnalyticsQueryPlanError(f"{field} must include a timezone")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as exc:
        raise AnalyticsQueryPlanError(f"{field} is out of range") from exc


def _fact_view(fact: Any) -> dict[str, Any]:
    """Normalize a TemporalFactRevision or a transport mapping."""

    is_mapping = isinstance(fact, Mapping)
    if is_mapping:
        payload_value = fact.get("payload", fact.get("data", {}))
        scope_value = fact.get("scope")
        values = fact
    else:
        payload_value = getattr(fact, "payload", {})
        scope_value = getattr(fact, "scope", None)
        values = None
    if not isinstance(payload_value, Mapping):
        raise AnalyticsQueryPlanError("fact payload must be an object")
    if scope_value is None and is_mapping:
        scope_value = {
            "tenant_id": fact.get("tenant_id", fact.get("tenant_ref")),
            "entity_id": fact.get("entity_id", fact.get("entity_ref")),
            "store_ids": (fact.get("store_id", fact.get("store_ref")),),
            "warehouse_ids": (fact.get("warehouse_id", fact.get("warehouse_ref")),),
        }
        scope_value = {
            key: value
            for key, value in scope_value.items()
            if value is not None and value != (None,)
        }
    try:
        scope = scope_value if isinstance(scope_value, ScopeRef) else ScopeRef.model_validate(scope_value)
    except (TypeError, ValueError) as exc:
        raise AnalyticsQueryPlanError("fact scope is invalid") from exc
    quality_raw = values.get("quality_state") if is_mapping else getattr(fact, "quality_state", "VALID")
    quality = str(getattr(quality_raw, "value", quality_raw or "NO_DATA")).strip().upper()
    if quality not in QUALITY_STATES:
        quality = "BLOCKED"
    event_value = values.get("event_time") if is_mapping else getattr(fact, "event_time", None)
    observed_value = values.get("observed_time") if is_mapping else getattr(fact, "observed_time", None)
    try:
        if not isinstance(event_value, datetime):
            event_value = datetime.fromisoformat(str(event_value).replace("Z", "+00:00")) if event_value else None
        if not isinstance(observed_value, datetime):
            observed_value = datetime.fromisoformat(str(observed_value).replace("Z", "+00:00")) if observed_value else None
    except (TypeError, ValueError) as exc:
        raise AnalyticsQueryPlanError("fact timestamps are invalid") from exc
    if event_value is None or observed_value is None:
        raise AnalyticsQueryPlanError("fact event_time and observed_time are required")
    return {
        "fact_id": str(values.get("fact_id", values.get("id", ""))) if is_mapping else str(getattr(fact, "fact_id", "")),
        "revision_id": str(values.get("revision_id", "")) if is_mapping else str(getattr(fact, "revision_id", "")),
        "revision": values.get("revision", 1) if is_mapping else getattr(fact, "revision", 1),
        "scope": scope,
        "payload": dict(payload_value),
        "quality_state": quality,
        "event_time": _utc(event_value, "fact.event_time"),
        "observed_time": _utc(observed_value, "fact.observed_time"),
        "source_system": str(values.get("source_system", "unknown")) if is_mapping else str(getattr(fact, "source_system", "unknown")),
    }


def _scope_exact(actual: ScopeRef, expected: ScopeRef) -> bool:
    return (
        actual.tenant_id == expected.tenant_id
        and actual.entity_id == expected.entity_id
        and (not expected.store_ids or set(actual.store_ids) == set(expected.store_ids))
        and (not expected.warehouse_ids or set(actual.warehouse_ids) == set(expected.warehouse_ids))
    )


def _field_value(view: Mapping[str, Any], field: str, period: PeriodRef) -> Any:
    payload = view["payload"]
    scope: ScopeRef = view["scope"]
    if field in payload:
        return payload[field]
    aliases = {
        "store": scope.store_ids[0] if len(scope.store_ids) == 1 else ",".join(scope.store_ids),
        "warehouse": scope.warehouse_ids[0] if len(scope.warehouse_ids) == 1 else ",".join(scope.warehouse_ids),
        "tenant": scope.tenant_id,
        "entity": scope.entity_id,
        "sku": payload.get("sku", payload.get("sku_id", payload.get("marketplace_sku"))),
        "category": payload.get("category", payload.get("category_id", payload.get("category_name"))),
    }
    if field == "month":
        try:
            zone = ZoneInfo(period.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise AnalyticsQueryPlanError("period timezone is invalid") from exc
        return view["event_time"].astimezone(zone).strftime("%Y-%m")
    if field in aliases:
        return aliases[field]
    return payload.get(field)


def _matches_filters(view: Mapping[str, Any], plan: AnalyticsQueryPlan) -> bool:
    period = _period_model(plan.period)
    for field, operator, expected in plan.filters:
        actual = _field_value(view, field, period)
        op = operator.strip().lower()
        if op in {"=", "eq"}:
            matched = str(actual) == expected
        elif op in {"!=", "ne"}:
            matched = str(actual) != expected
        elif op in {"in", "not_in"}:
            options = {item.strip() for item in expected.split(",") if item.strip()}
            matched = str(actual) in options
            if op == "not_in":
                matched = not matched
        else:
            try:
                left = Decimal(str(actual))
                right = Decimal(str(expected))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise AnalyticsQueryPlanError(f"unsupported filter operator: {operator}") from exc
            if not left.is_finite() or not right.is_finite():
                raise AnalyticsQueryPlanError("filters cannot contain non-finite numbers")
            if op in {">", "gt"}:
                matched = left > right
            elif op in {">=", "gte"}:
                matched = left >= right
            elif op in {"<", "lt"}:
                matched = left < right
            elif op in {"<=", "lte"}:
                matched = left <= right
            else:
                raise AnalyticsQueryPlanError(f"unsupported filter operator: {operator}")
        if not matched:
            return False
    return True


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise AnalyticsQueryPlanError(f"{field} is missing or invalid")
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AnalyticsQueryPlanError(f"{field} is invalid") from exc
    if not result.is_finite():
        raise AnalyticsQueryPlanError(f"{field} is non-finite")
    return result


def _metric_value(metric: str, payload: Mapping[str, Any]) -> Decimal | None:
    if metric == "units_sold":
        for key in ("units_sold", "units", "quantity", "qty"):
            if key in payload:
                value = _decimal(payload[key], key)
                if value < 0:
                    raise AnalyticsQueryPlanError("units_sold cannot be negative")
                return value
        return None
    if metric == "net_sales":
        for key in ("net_sales", "net_revenue"):
            if key in payload:
                return _decimal(payload[key], key)
        gross = next((payload[key] for key in ("gross_sales", "gross_revenue", "revenue", "sales") if key in payload), None)
        if gross is None:
            return None
        value = _decimal(gross, "gross_sales")
        for key in ("discount", "discounts", "promotion_discount"):
            if key in payload:
                value -= _decimal(payload[key], key)
        for key in ("refund", "refunds", "refund_amount", "returns"):
            if key in payload:
                value -= _decimal(payload[key], key)
        return value
    return None


def _decimal_string(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _period_dict(period: PeriodRef) -> dict[str, Any]:
    return period.model_dump(mode="json")


def execute_analytics_plan(
    plan: AnalyticsQueryPlan,
    facts: Sequence[Any] | None,
    *,
    data_products: Mapping[str, Any] | Sequence[Any] | None = None,
    source_error: str | None = None,
    source_quality_state: str | None = None,
) -> AnalyticsExecutionResult:
    """Execute the small read-only metric subset against scoped facts.

    This is intentionally an in-process projection seam.  It accepts facts
    supplied by either temporal adapter and never opens a repository or writes
    a Fact/ledger.  A caller must provide the registry snapshot; omission is a
    blocked data-product gate rather than an implicit bypass.
    """

    gate = evaluate_data_product_gate(plan, data_products)
    if source_quality_state is not None:
        source_quality_state = str(
            getattr(source_quality_state, "value", source_quality_state)
        ).strip().upper()
        if source_quality_state not in QUALITY_STATES:
            raise AnalyticsQueryPlanError("source_quality_state is invalid")
    expected_scope = _scope_model(plan.scope)
    period_ref = _period_model(plan.period)
    aggregates: dict[tuple[tuple[str, str], ...], dict[str, Any]] = {}
    excluded: list[dict[str, Any]] = []
    source_watermarks: dict[str, str] = {}
    included_count = 0
    quality_seen: list[str] = []
    period_start = _utc(period_ref.start_at, "period.start_at")
    period_end = _utc(period_ref.end_at, "period.end_at")

    if gate["verified"] and not source_error:
        for raw_fact in facts or ():
            try:
                view = _fact_view(raw_fact)
            except AnalyticsQueryPlanError as exc:
                excluded.append({"fact_id": "", "quality_state": "BLOCKED", "reason": str(exc)})
                quality_seen.append("BLOCKED")
                continue
            fact_id = view["fact_id"]
            quality = view["quality_state"]
            if not _scope_exact(view["scope"], expected_scope):
                excluded.append({"fact_id": fact_id, "revision_id": view["revision_id"], "quality_state": quality, "reason": "scope_mismatch"})
                quality_seen.append("BLOCKED")
                continue
            if view["event_time"] < period_start or view["event_time"] >= period_end:
                excluded.append({"fact_id": fact_id, "revision_id": view["revision_id"], "quality_state": quality, "reason": "outside_period"})
                continue
            if not _matches_filters(view, plan):
                continue
            if quality in _TERMINAL_QUALITY:
                excluded.append({"fact_id": fact_id, "revision_id": view["revision_id"], "quality_state": quality, "reason": f"quality_{quality.lower()}"})
                quality_seen.append(quality)
                continue
            values: dict[str, Decimal] = {}
            missing_metrics: list[str] = []
            for metric in plan.metrics:
                value = _metric_value(metric, view["payload"])
                if value is None:
                    missing_metrics.append(metric)
                else:
                    values[metric] = value
            if not values:
                excluded.append({"fact_id": fact_id, "revision_id": view["revision_id"], "quality_state": quality, "reason": "metric_value_missing"})
                quality_seen.append("PARTIAL")
                continue
            dimensions: dict[str, str] = {}
            for dimension in plan.dimensions:
                raw_value = _field_value(view, dimension, period_ref)
                dimensions[dimension] = str(raw_value) if raw_value is not None and str(raw_value) else "__unknown__"
            key = tuple(sorted(dimensions.items()))
            row = aggregates.setdefault(
                key,
                {
                    **dimensions,
                    "dimensions": dimensions,
                    "metrics": {},
                    "quality_state": "VALID",
                    "included_count": 0,
                    "excluded_count": 0,
                },
            )
            for metric, value in values.items():
                previous = Decimal(str(row["metrics"].get(metric, "0")))
                row["metrics"][metric] = _decimal_string(previous + value)
                # Keep flattened aliases for simple BI clients while retaining
                # the explicit metrics object as the canonical shape.
                row[metric] = row["metrics"][metric]
            if missing_metrics:
                row["excluded_count"] += 1
                row.setdefault("quality_reasons", []).append("metric_missing:" + ",".join(sorted(missing_metrics)))
                row["quality_state"] = "PARTIAL"
                quality_seen.append("PARTIAL")
            elif _QUALITY_PRIORITY[quality] > _QUALITY_PRIORITY[row["quality_state"]]:
                row["quality_state"] = quality
                quality_seen.append(quality)
            row["included_count"] += 1
            included_count += 1
            source = view["source_system"] or "unknown"
            observed = view["observed_time"].isoformat()
            if observed > source_watermarks.get(source, ""):
                source_watermarks[source] = observed
    elif source_error:
        excluded.append({"fact_id": "", "quality_state": "BLOCKED", "reason": source_error})

    if not gate["verified"] or source_error:
        quality_state = "BLOCKED"
    elif source_quality_state in {"BLOCKED", "UNKNOWN_OUTCOME"}:
        quality_state = source_quality_state
    elif not facts:
        quality_state = source_quality_state if source_quality_state in {"PARTIAL", "STALE"} else "NO_DATA"
    elif not included_count:
        quality_state = max(quality_seen or ["NO_DATA"], key=lambda item: _QUALITY_PRIORITY[item])
    elif any(item == "BLOCKED" for item in quality_seen):
        quality_state = "BLOCKED"
    elif any(item == "UNKNOWN_OUTCOME" for item in quality_seen):
        quality_state = "UNKNOWN_OUTCOME"
    elif any(item == "STALE" for item in quality_seen) or any(row["quality_state"] == "STALE" for row in aggregates.values()):
        quality_state = "STALE"
    elif any(item == "PARTIAL" for item in quality_seen) or any(row["quality_state"] == "PARTIAL" for row in aggregates.values()):
        quality_state = "PARTIAL"
    else:
        quality_state = "VALID"

    aggregate_rows: list[dict[str, Any]] = []
    for key in sorted(aggregates):
        row = aggregates[key]
        row["quality_reasons"] = sorted(set(row.get("quality_reasons", [])))
        aggregate_rows.append(row)
    period = _period_dict(period_ref)
    scope = expected_scope.model_dump(mode="json")
    document = {
        "contract_id": "kjds-analytics-execution-v1",
        "plan_hash": plan.plan_hash,
        "scope": scope,
        "period": period,
        "status": quality_state,
        "aggregates": aggregate_rows,
        "included_count": included_count,
        "excluded_count": len(excluded),
        "excluded_rows": excluded,
        "source_watermarks": source_watermarks,
        "data_product_gate": gate,
    }
    return AnalyticsExecutionResult(
        status=quality_state,
        quality_state=quality_state,
        scope=scope,
        period=period,
        metrics=plan.metrics,
        aggregates=tuple(aggregate_rows),
        included_count=included_count,
        excluded_count=len(excluded),
        excluded_rows=tuple(excluded),
        source_watermarks=dict(sorted(source_watermarks.items())),
        data_product_gate=gate,
        result_hash=_canonical_hash(document),
    )


def comparison_period(
    period: PeriodRef | Mapping[str, Any],
    relation: str,
) -> PeriodRef:
    """Build a deterministic comparison window with the same timezone/currency."""

    period = _period_model(period)
    relation = str(relation).strip()
    duration = period.end_at - period.start_at
    if relation in {"previous_period", "rolling"}:
        start = period.start_at - duration
        end = period.start_at
    elif relation == "same_period_last_year":
        def previous_year(value: datetime) -> datetime:
            try:
                return value.replace(year=value.year - 1)
            except ValueError:  # Feb 29 in a leap year
                return value.replace(year=value.year - 1, day=28)
        start = previous_year(period.start_at)
        end = previous_year(period.end_at)
    else:
        raise AnalyticsQueryPlanError(f"unsupported comparison: {relation}")
    return PeriodRef(
        period_type="custom",
        start_at=start,
        end_at=end,
        timezone=period.timezone,
        currency=period.currency,
        as_of=period.as_of,
        partial=period.partial,
        closed=period.closed,
    )


def compare_analytics_results(
    current: AnalyticsExecutionResult,
    comparison: AnalyticsExecutionResult,
    *,
    relation: str,
) -> dict[str, Any]:
    """Return per-dimension deltas without turning missing values into zero."""

    def index(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[tuple[str, str], ...], Mapping[str, Any]]:
        result: dict[tuple[tuple[str, str], ...], Mapping[str, Any]] = {}
        for row in rows:
            dimensions = row.get("dimensions")
            if isinstance(dimensions, Mapping):
                result[tuple(sorted((str(k), str(v)) for k, v in dimensions.items()))] = row
        return result

    current_rows = index(current.aggregates)
    comparison_rows = index(comparison.aggregates)
    delta_rows: list[dict[str, Any]] = []
    for key in sorted(set(current_rows) | set(comparison_rows)):
        left = current_rows.get(key)
        right = comparison_rows.get(key)
        dimensions = dict(key)
        metrics: dict[str, str | None] = {}
        metric_states: dict[str, str] = {}
        metric_names = set(current.metrics) | set(comparison.metrics)
        if left:
            metric_names.update((left.get("metrics") or {}).keys())
        if right:
            metric_names.update((right.get("metrics") or {}).keys())
        for metric in sorted(metric_names):
            left_value = (left or {}).get("metrics", {}).get(metric)
            right_value = (right or {}).get("metrics", {}).get(metric)
            if left_value is None or right_value is None:
                metrics[metric] = None
                metric_states[metric] = "NO_DATA"
            else:
                metrics[metric] = _decimal_string(_decimal(left_value, metric) - _decimal(right_value, metric))
                metric_states[metric] = "VALID"
        delta_rows.append({
            **dimensions,
            "dimensions": dimensions,
            "metrics": metrics,
            "metric_quality": metric_states,
            "quality_state": "VALID" if metrics and all(value is not None for value in metrics.values()) else "NO_DATA",
        })
    document = {
        "relation": relation,
        "period": comparison.period,
        "quality_state": comparison.quality_state,
        "rows": delta_rows,
        "current_result_hash": current.result_hash,
        "comparison_result_hash": comparison.result_hash,
    }
    return {
        "relation": relation,
        "period": comparison.period,
        "quality_state": comparison.quality_state,
        "current_quality_state": current.quality_state,
        "rows": delta_rows,
        "result_hash": _canonical_hash(document),
        "current_result_hash": current.result_hash,
        "comparison_result_hash": comparison.result_hash,
    }


# Discoverable aliases for callers that use either terminology.
execute_query_plan = execute_analytics_plan
aggregate_analytics_facts = execute_analytics_plan


__all__ = [
    "AnalyticsExecutionResult",
    "AnalyticsQueryPlan",
    "AnalyticsQueryPlanError",
    "DEFAULT_METRIC_CATALOG",
    "QUALITY_STATES",
    "aggregate_analytics_facts",
    "compare_analytics_results",
    "comparison_period",
    "compile_query_plan",
    "evaluate_data_product_gate",
    "execute_analytics_plan",
    "execute_query_plan",
]
