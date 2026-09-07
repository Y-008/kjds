import pytest

from apps.control_plane.data_fabric_contracts import ScopeRef
from apps.control_plane.metric_recipe_compiler import MetricRecipeCompiler, MetricRecipeError, compile_metric_recipe

SCOPE = ScopeRef(tenant_id="tenant-a", entity_id="entity-a", store_ids=("store-a",))


def recipe(**overrides):
    value = {
        "recipe_id": "r-profit",
        "scope": SCOPE,
        "metric_id": "realized_profit",
        "metric_version": "1",
        "dimensions": ("store", "sku"),
        "quality_states": ("VALID", "PARTIAL"),
        "currency": "RUB",
    }
    value.update(overrides)
    return value


def test_compiler_is_read_only_and_hash_stable():
    first = compile_metric_recipe(recipe())
    second = compile_metric_recipe(recipe())
    assert first.execution == "read_only"
    assert first.source_dataset == "profit.cm3.v1"
    assert first.plan_hash == second.plan_hash


def test_compiler_rejects_unknown_version_dimension_and_currency():
    compiler = MetricRecipeCompiler()
    with pytest.raises(MetricRecipeError, match="unknown metric"):
        compiler.compile(recipe(metric_id="missing"))
    with pytest.raises(MetricRecipeError, match="version mismatch"):
        compiler.compile(recipe(metric_version="2"))
    with pytest.raises(MetricRecipeError, match="dimensions unsupported"):
        compiler.compile(recipe(dimensions=("warehouse",)))
    with pytest.raises(MetricRecipeError, match="currency is not applicable"):
        compiler.compile(recipe(metric_id="units_sold", metric_version="1", dimensions=("store",), currency="RUB"))


def test_recipe_quality_and_filter_values_are_normalized():
    result = compile_metric_recipe(
        recipe(
            dimensions="sku",
            quality_states="valid",
            filters=[{"field": "store", "operator": "in", "value": ["store-a", "store-b"]}],
        )
    )
    assert result.recipe.dimensions == ("sku",)
    assert result.recipe.quality_states == ("VALID",)
    assert result.recipe.filters[0].value == ("store-a", "store-b")
