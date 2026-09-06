from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.control_plane.demand_censoring import (
    StockoutDemandInput,
    estimate_stockout_demand,
)


def test_stockout_demand_keeps_observed_and_estimates_lost_sales_separately():
    result = estimate_stockout_demand(
        StockoutDemandInput(
            sku="sku-1",
            interval_start=datetime(2026, 9, 1, tzinfo=UTC),
            interval_end=datetime(2026, 9, 11, tzinfo=UTC),
            observed_units=Decimal("12"),
            in_stock_rate=Decimal("0.4"),
            baseline_units_per_day=Decimal("2"),
        )
    )
    assert result.quality_state == "PARTIAL"
    assert result.observed_demand == Decimal("12")
    assert result.lost_sales_estimate == Decimal("8")
    assert result.censored_demand == Decimal("20")


def test_missing_baseline_is_no_data_and_never_zero_lost_sales():
    result = estimate_stockout_demand(
        StockoutDemandInput(
            sku="sku-1",
            interval_start=datetime(2026, 9, 1, tzinfo=UTC),
            interval_end=datetime(2026, 9, 2, tzinfo=UTC),
            observed_units=Decimal("0"),
            in_stock_rate=Decimal("0"),
        )
    )
    assert result.quality_state == "NO_DATA"
    assert result.censored_demand is None
    assert result.lost_sales_estimate is None


def test_stockout_input_rejects_invalid_window_and_rate():
    with pytest.raises(ValueError):
        estimate_stockout_demand(
            StockoutDemandInput(
                sku="sku-1",
                interval_start=datetime(2026, 9, 2, tzinfo=UTC),
                interval_end=datetime(2026, 9, 1, tzinfo=UTC),
                observed_units=Decimal("1"),
                in_stock_rate=Decimal("1.1"),
            )
        )
