from datetime import UTC, datetime

import pytest

from apps.control_plane.analytics_query_plan import (
    AnalyticsQueryPlanError,
    compile_query_plan,
)
from apps.control_plane.data_fabric_contracts import AnalysisRecipe, PeriodRef, ScopeRef


def recipe(*, metrics: tuple[str, ...] = ("cm3",)) -> AnalysisRecipe:
    return AnalysisRecipe(
        recipe_id="recipe-1",
        version="1",
        scope=ScopeRef(tenant_id="t1", entity_id="e1", store_ids=("s1",)),
        period=PeriodRef(
            period_type="month",
            start_at=datetime(2026, 9, 1, tzinfo=UTC),
            end_at=datetime(2026, 10, 1, tzinfo=UTC),
            timezone="Europe/Moscow",
            currency="RUB",
            as_of=datetime(2026, 9, 6, tzinfo=UTC),
        ),
        dimensions=("category", "price_band", "sku"),
        metrics=metrics,
        compare_with=("previous_period",),
    )


def test_compile_plan_is_read_only_and_stable() -> None:
    first = compile_query_plan(recipe())
    second = compile_query_plan(recipe())

    assert first.execution == "read_only"
    assert first.source_datasets == ("profit.cm3.v1",)
    assert first.plan_hash == second.plan_hash
    assert len(first.plan_hash) == 64


def test_compile_plan_rejects_unknown_metric() -> None:
    with pytest.raises(AnalyticsQueryPlanError, match="unknown metrics"):
        compile_query_plan(recipe(metrics=("unknown_metric",)))


def test_compile_plan_rejects_unsupported_dimension() -> None:
    invalid = recipe().model_copy(update={"dimensions": ("warehouse",)})

    with pytest.raises(AnalyticsQueryPlanError, match="unsupported"):
        compile_query_plan(invalid)


def test_demand_and_risk_profit_metrics_bind_to_explicit_products():
    compiled = compile_query_plan(
        recipe(metrics=("observed_demand", "lost_sales_estimate", "risk_adjusted_profit"))
        .model_copy(update={"dimensions": ("store", "sku")})
    )
    assert compiled.source_datasets == (
        "demand.censoring.v1",
        "profit.cm3.v1",
    )
