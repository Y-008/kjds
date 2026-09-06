"""Deterministic demand estimates when stockouts censor observed sales."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

QualityState = Literal["NO_DATA", "PARTIAL", "STALE", "BLOCKED", "UNKNOWN_OUTCOME", "VALID"]


@dataclass(frozen=True, slots=True)
class StockoutDemandInput:
    sku: str
    interval_start: datetime
    interval_end: datetime
    observed_units: Decimal
    in_stock_rate: Decimal
    baseline_units_per_day: Decimal | None = None


@dataclass(frozen=True, slots=True)
class StockoutDemandEstimate:
    sku: str
    quality_state: QualityState
    observed_demand: Decimal
    censored_demand: Decimal | None
    lost_sales_estimate: Decimal | None
    stockout_interval_days: Decimal
    reason: str | None
    snapshot_sha256: str


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC)


def estimate_stockout_demand(values: StockoutDemandInput) -> StockoutDemandEstimate:
    """Estimate demand without treating a stockout as weak customer demand.

    ``baseline_units_per_day`` must come from a separately evidenced,
    non-stockout comparison window.  If it is missing, the result is
    ``NO_DATA`` and never fabricates lost sales.
    """

    if not values.sku.strip():
        raise ValueError("sku is required")
    start = _utc(values.interval_start)
    end = _utc(values.interval_end)
    if end <= start:
        raise ValueError("interval_end must be after interval_start")
    if values.observed_units < 0:
        raise ValueError("observed_units cannot be negative")
    if values.in_stock_rate < 0 or values.in_stock_rate > 1:
        raise ValueError("in_stock_rate must be between 0 and 1")
    days = Decimal(str((end - start).total_seconds())) / Decimal("86400")
    reason: str | None = None
    if values.baseline_units_per_day is None:
        quality: QualityState = "NO_DATA"
        censored = None
        lost = None
        reason = "non_stockout_baseline_missing"
    elif values.baseline_units_per_day < 0:
        raise ValueError("baseline_units_per_day cannot be negative")
    else:
        expected = values.baseline_units_per_day * days
        # A high observed value is retained; the model never subtracts
        # demand merely because the baseline was conservative.
        lost = max(Decimal("0"), expected - values.observed_units)
        censored = values.observed_units + lost
        quality = "VALID" if values.in_stock_rate >= 1 else "PARTIAL"
        if values.in_stock_rate >= 1:
            lost = Decimal("0")
            censored = values.observed_units
        reason = "stockout_censored" if values.in_stock_rate < 1 else None

    canonical = {
        "sku": values.sku,
        "interval_start": start.isoformat(),
        "interval_end": end.isoformat(),
        "observed_units": str(values.observed_units),
        "in_stock_rate": str(values.in_stock_rate),
        "baseline_units_per_day": (
            str(values.baseline_units_per_day)
            if values.baseline_units_per_day is not None
            else None
        ),
        "quality_state": quality,
        "observed_demand": str(values.observed_units),
        "censored_demand": str(censored) if censored is not None else None,
        "lost_sales_estimate": str(lost) if lost is not None else None,
        "stockout_interval_days": str(days),
        "reason": reason,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return StockoutDemandEstimate(
        sku=values.sku,
        quality_state=quality,
        observed_demand=values.observed_units,
        censored_demand=censored,
        lost_sales_estimate=lost,
        stockout_interval_days=days,
        reason=reason,
        snapshot_sha256=digest,
    )


__all__ = ["StockoutDemandInput", "StockoutDemandEstimate", "estimate_stockout_demand"]
