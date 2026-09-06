"""Compile validated analytics recipes into deterministic read-only plans."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .data_fabric_contracts import AnalysisRecipe, MetricDefinition


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
