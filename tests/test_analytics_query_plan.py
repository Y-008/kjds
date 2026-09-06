from datetime import UTC, datetime

import pytest

from apps.control_plane.analytics_query_plan import (
    AnalyticsQueryPlanError,
    compare_analytics_results,
    comparison_period,
    compile_query_plan,
    execute_analytics_plan,
)
from apps.control_plane.data_fabric_contracts import (
    AnalysisRecipe,
    DataProductDescriptor,
    PeriodRef,
    ScopeRef,
)


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


def _orders_recipe(
    *,
    start: datetime,
    end: datetime,
    compare_with: tuple[str, ...] = (),
) -> AnalysisRecipe:
    return AnalysisRecipe(
        recipe_id="orders-rollup",
        version="1",
        scope=ScopeRef(tenant_id="t1", entity_id="e1", store_ids=("s1",)),
        period=PeriodRef(
            period_type="custom",
            start_at=start,
            end_at=end,
            timezone="UTC",
            currency="USD",
            as_of=end,
        ),
        dimensions=("store", "sku"),
        metrics=("net_sales", "units_sold"),
        compare_with=compare_with,
    )


def _verified_orders_product(*, status: str = "verified") -> DataProductDescriptor:
    return DataProductDescriptor(
        dataset_id="orders.canonical.v1",
        version="1",
        owner="oms",
        grain="order_line",
        quality_threshold=0.0,
        rebuild_method="test replay",
        status=status,
        authority="canonical_fact",
    )


def _verified_demand_product(*, status: str = "verified") -> DataProductDescriptor:
    return DataProductDescriptor(
        dataset_id="demand.censoring.v1",
        version="1",
        owner="demand",
        grain="sku_store_period",
        quality_threshold=0.0,
        rebuild_method="test replay",
        status=status,
        authority="projection",
    )


def _order_fact(
    fact_id: str,
    event_time: datetime,
    *,
    gross_sales: int | float = 0,
    quantity: int | float = 0,
    sku: str = "sku-1",
    quality_state: str = "VALID",
    tenant_id: str = "t1",
) -> dict:
    return {
        "fact_id": fact_id,
        "revision_id": f"rev-{fact_id}",
        "revision": 1,
        "scope": {
            "tenant_id": tenant_id,
            "entity_id": "e1",
            "store_ids": ("s1",),
            "warehouse_ids": (),
        },
        "event_time": event_time,
        "observed_time": event_time,
        "quality_state": quality_state,
        "source_system": "ozon",
        "payload": {
            "gross_sales": gross_sales,
            "quantity": quantity,
            "sku": sku,
        },
    }


def _demand_fact(
    fact_id: str,
    event_time: datetime,
    *,
    observed_units: int | float = 0,
    censored_units: int | float | None = None,
    lost_sales_units: int | float | None = None,
    stockout_interval_days: int | float | None = None,
    quality_state: str = "VALID",
    tenant_id: str = "t1",
) -> dict:
    payload = {
        "sku": "sku-1",
        "observed_units": observed_units,
    }
    if censored_units is not None:
        payload["censored_units"] = censored_units
    if lost_sales_units is not None:
        payload["lost_sales_units"] = lost_sales_units
    if stockout_interval_days is not None:
        payload["stockout_interval_days"] = stockout_interval_days
    return {
        "fact_id": fact_id,
        "revision_id": f"rev-{fact_id}",
        "revision": 1,
        "scope": {
            "tenant_id": tenant_id,
            "entity_id": "e1",
            "store_ids": ("s1",),
            "warehouse_ids": (),
        },
        "event_time": event_time,
        "observed_time": event_time,
        "quality_state": quality_state,
        "source_system": "demand-model",
        "payload": payload,
    }


def test_execute_orders_rolls_up_net_sales_and_units_without_losing_zero() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    plan = compile_query_plan(_orders_recipe(start=start, end=end))
    facts = [
        _order_fact("f1", start, gross_sales=10, quantity=2),
        _order_fact("f2", start, gross_sales=5, quantity=1),
        _order_fact("f-zero", start, gross_sales=0, quantity=0, sku="sku-zero"),
    ]
    facts[0]["scope"]["warehouse_ids"] = ("warehouse-1",)

    result = execute_analytics_plan(
        plan,
        facts,
        data_products=(_verified_orders_product(),),
    )

    assert result.status == "VALID"
    assert result.included_count == 3
    assert result.excluded_count == 0
    by_sku = {row["sku"]: row for row in result.aggregates}
    assert by_sku["sku-1"]["metrics"] == {"net_sales": "15", "units_sold": "3"}
    assert by_sku["sku-zero"]["metrics"] == {"net_sales": "0", "units_sold": "0"}


def test_execute_demand_metrics_exposes_stockout_censoring_and_interval() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    demand_recipe = _orders_recipe(start=start, end=end).model_copy(
        update={
            "metrics": (
                "observed_demand",
                "censored_demand",
                "lost_sales_estimate",
                "stockout_interval",
            )
        }
    )
    plan = compile_query_plan(demand_recipe)
    result = execute_analytics_plan(
        plan,
        [
            _demand_fact(
                "demand-1",
                start,
                observed_units=12,
                censored_units=20,
                lost_sales_units=8,
                stockout_interval_days=0.6,
                quality_state="PARTIAL",
            )
        ],
        data_products=(_verified_demand_product(),),
    )

    assert result.status == "PARTIAL"
    assert result.included_count == 1
    assert result.excluded_count == 0
    assert result.aggregates[0]["metrics"] == {
        "censored_demand": "20",
        "lost_sales_estimate": "8",
        "observed_demand": "12",
        "stockout_interval": "0.6",
    }
    assert result.aggregates[0]["quality_state"] == "PARTIAL"


def test_demand_missing_estimates_are_partial_and_zero_observed_is_retained() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    recipe = _orders_recipe(start=start, end=end).model_copy(
        update={
            "metrics": (
                "observed_demand",
                "censored_demand",
                "lost_sales_estimate",
                "stockout_interval_days",
            )
        }
    )
    result = execute_analytics_plan(
        compile_query_plan(recipe),
        [_demand_fact("demand-no-baseline", start, observed_units=0, stockout_interval_days=0)],
        data_products=(_verified_demand_product(),),
    )

    assert result.status == "PARTIAL"
    assert result.included_count == 1
    assert result.aggregates[0]["metrics"] == {
        "observed_demand": "0",
        "stockout_interval_days": "0",
    }
    assert "metric_missing:censored_demand,lost_sales_estimate" in result.aggregates[0]["quality_reasons"]


def test_demand_metric_rejects_negative_or_conflicting_aliases() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    recipe = _orders_recipe(start=start, end=end).model_copy(
        update={"metrics": ("observed_demand",)}
    )
    plan = compile_query_plan(recipe)
    with pytest.raises(AnalyticsQueryPlanError, match="cannot be negative"):
        execute_analytics_plan(
            plan,
            [_demand_fact("negative", start, observed_units=-1)],
            data_products=(_verified_demand_product(),),
        )

    conflicting = _demand_fact("conflicting", start, observed_units=2)
    conflicting["payload"]["observed_demand"] = 3
    with pytest.raises(AnalyticsQueryPlanError, match="aliases disagree"):
        execute_analytics_plan(
            plan,
            [conflicting],
            data_products=(_verified_demand_product(),),
        )


def test_unreviewed_experiment_facts_are_excluded_from_long_term_rollups() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    recipe = _orders_recipe(start=start, end=end)
    fact = _order_fact("experimental", start, gross_sales=99, quantity=3)
    fact["payload"]["experiment"] = {
        "experiment_id": "price-a",
        "review_eligible": False,
        "causal_evidence": [],
        "stop_rule": None,
    }

    result = execute_analytics_plan(
        compile_query_plan(recipe),
        [fact],
        data_products=(_verified_orders_product(),),
    )

    assert result.status == "PARTIAL"
    assert result.aggregates == ()
    assert result.included_count == 0
    assert result.excluded_count == 1
    excluded = result.excluded_rows[0]
    assert excluded["reason"] == "experiment_not_long_term_eligible"
    assert excluded["experiment_id"] == "price-a"
    assert set(excluded["experiment_reasons"]) == {
        "experiment_causal_evidence_missing",
        "experiment_not_review_eligible",
        "experiment_stop_rule_missing",
    }


def test_reviewed_experiment_fact_can_enter_rollup_and_top_level_legacy_markers_are_gated() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    recipe = _orders_recipe(start=start, end=end)
    reviewed = _order_fact("reviewed-experimental", start, gross_sales=10, quantity=1)
    reviewed["payload"]["experiment_context"] = {
        "protocol_id": "protocol-1",
        "review_eligible": True,
        "causal_evidence": ["evidence-1"],
        "stop_rule": "stop-rule-1",
    }
    legacy_unreviewed = _order_fact("legacy-experimental", start, gross_sales=20, quantity=2)
    legacy_unreviewed.update(
        {
            "experiment_id": "protocol-2",
            "review_eligible": True,
            "causal_evidence": ["evidence-2"],
        }
    )

    result = execute_analytics_plan(
        compile_query_plan(recipe),
        [reviewed, legacy_unreviewed],
        data_products=(_verified_orders_product(),),
    )

    assert result.status == "PARTIAL"
    assert result.included_count == 1
    assert result.excluded_count == 1
    assert result.aggregates[0]["metrics"] == {"net_sales": "10", "units_sold": "1"}
    assert result.excluded_rows[0]["experiment_id"] == "protocol-2"


def test_null_nested_experiment_context_cannot_bypass_long_term_gate() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    end = datetime(2026, 9, 2, tzinfo=UTC)
    fact = _order_fact("null-experiment", start, gross_sales=10, quantity=1)
    fact["experiment_context"] = None

    result = execute_analytics_plan(
        compile_query_plan(_orders_recipe(start=start, end=end)),
        [fact],
        data_products=(_verified_orders_product(),),
    )

    assert result.aggregates == ()
    assert result.excluded_rows[0]["reason"] == "experiment_not_long_term_eligible"


def test_execute_quality_states_stay_separate_from_numeric_values() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    plan = compile_query_plan(_orders_recipe(start=start, end=start.replace(day=2)))
    result = execute_analytics_plan(
        plan,
        [
            _order_fact("valid", start, gross_sales=0, quantity=0),
            _order_fact("stale", start, gross_sales=4, quantity=1, quality_state="STALE"),
            _order_fact("unknown", start, gross_sales=7, quantity=1, quality_state="UNKNOWN_OUTCOME"),
        ],
        data_products=(_verified_orders_product(),),
    )

    assert result.status == "UNKNOWN_OUTCOME"
    assert result.aggregates[0]["metrics"] == {"net_sales": "4", "units_sold": "1"}
    assert {row["quality_state"] for row in result.excluded_rows} == {"UNKNOWN_OUTCOME"}
    assert result.aggregates[0]["quality_state"] == "STALE"


def test_execute_requires_verified_scoped_data_product() -> None:
    start = datetime(2026, 9, 1, tzinfo=UTC)
    plan = compile_query_plan(_orders_recipe(start=start, end=start.replace(day=2)))
    result = execute_analytics_plan(
        plan,
        [_order_fact("f1", start, gross_sales=10, quantity=1)],
        data_products=(_verified_orders_product(status="contract_only"),),
    )

    assert result.status == "BLOCKED"
    assert result.quality_state == "BLOCKED"
    assert result.aggregates == ()
    assert result.data_product_gate["verified"] is False
    assert "data_product_contract_only" in result.data_product_gate["reasons"][0]

    out_of_scope = execute_analytics_plan(
        plan,
        [_order_fact("cross-tenant", start, gross_sales=10, quantity=1, tenant_id="other")],
        data_products=(_verified_orders_product(),),
    )
    assert out_of_scope.status == "BLOCKED"
    assert out_of_scope.aggregates == ()
    assert out_of_scope.excluded_rows[0]["reason"] == "scope_mismatch"


def test_comparison_period_and_delta_preserve_missing_as_no_data() -> None:
    current_start = datetime(2026, 9, 1, tzinfo=UTC)
    current_end = datetime(2026, 9, 2, tzinfo=UTC)
    current_plan = compile_query_plan(
        _orders_recipe(
            start=current_start,
            end=current_end,
            compare_with=("previous_period",),
        )
    )
    previous = comparison_period(current_plan.period, "previous_period")
    previous_plan = compile_query_plan(
        _orders_recipe(start=previous.start_at, end=previous.end_at)
    )
    product = (_verified_orders_product(),)
    current = execute_analytics_plan(
        current_plan,
        [_order_fact("current", current_start, gross_sales=14, quantity=2)],
        data_products=product,
    )
    prior = execute_analytics_plan(
        previous_plan,
        [_order_fact("prior", previous.start_at, gross_sales=10, quantity=1)],
        data_products=product,
    )
    comparison = compare_analytics_results(current, prior, relation="previous_period")

    assert comparison["rows"][0]["metrics"] == {"net_sales": "4", "units_sold": "1"}
    assert comparison["rows"][0]["quality_state"] == "VALID"
    assert comparison["comparison_result_hash"] == prior.result_hash
