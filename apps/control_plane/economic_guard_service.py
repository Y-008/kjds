"""Deterministic economic gates for autonomous operating decisions."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class EconomicGuardInput:
    cash_available: Decimal
    min_cash: Decimal = Decimal("0")
    margin_rate: Decimal | None = None
    min_margin_rate: Decimal | None = None
    inventory_days: Decimal | None = None
    max_inventory_days: Decimal | None = None
    budget_remaining: Decimal | None = None
    min_budget_remaining: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class EconomicGuardResult:
    status: Literal["allowed", "blocked"]
    reasons: tuple[str, ...]
    snapshot_sha256: str


def _coerce_decimal(
    value: object,
    field: str,
    reasons: list[str],
    *,
    required: bool = False,
    nonnegative: bool = False,
    ratio: bool = False,
) -> Decimal | None:
    """Normalize a guard input without allowing Decimal traps to escape.

    Economic gates run in unattended paths, so malformed numeric snapshots
    must become an explicit blocked result rather than raising
    ``InvalidOperation`` (or being treated as zero).  The returned value is
    only used for comparisons and deterministic hashing after validation.
    """

    if value is None:
        if required:
            reasons.append(f"{field}_missing")
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        reasons.append(f"{field}_invalid")
        return None
    if not number.is_finite():
        reasons.append(f"{field}_non_finite")
        return None
    if nonnegative and number < 0:
        reasons.append(f"{field}_negative")
    if ratio and not Decimal("0") <= number <= Decimal("1"):
        reasons.append(f"{field}_out_of_range")
    return number


def evaluate_economic_guard(values: EconomicGuardInput) -> EconomicGuardResult:
    reasons: list[str] = []
    cash_available = _coerce_decimal(
        values.cash_available,
        "cash_available",
        reasons,
        required=True,
        nonnegative=True,
    )
    min_cash = _coerce_decimal(
        values.min_cash, "min_cash", reasons, required=True, nonnegative=True
    )
    margin_rate = _coerce_decimal(
        values.margin_rate, "margin_rate", reasons, ratio=True
    )
    min_margin_rate = _coerce_decimal(
        values.min_margin_rate, "min_margin_rate", reasons, ratio=True
    )
    inventory_days = _coerce_decimal(
        values.inventory_days, "inventory_days", reasons, nonnegative=True
    )
    max_inventory_days = _coerce_decimal(
        values.max_inventory_days,
        "max_inventory_days",
        reasons,
        nonnegative=True,
    )
    budget_remaining = _coerce_decimal(
        values.budget_remaining, "budget_remaining", reasons
    )
    min_budget_remaining = _coerce_decimal(
        values.min_budget_remaining,
        "min_budget_remaining",
        reasons,
        required=True,
        nonnegative=True,
    )
    if cash_available is not None and min_cash is not None and cash_available < min_cash:
        reasons.append("cash_below_floor")
    if (
        margin_rate is not None
        and min_margin_rate is not None
        and margin_rate < min_margin_rate
    ):
        reasons.append("margin_below_floor")
    if (
        inventory_days is not None
        and max_inventory_days is not None
        and inventory_days > max_inventory_days
    ):
        reasons.append("inventory_days_above_ceiling")
    if (
        budget_remaining is not None
        and min_budget_remaining is not None
        and budget_remaining < min_budget_remaining
    ):
        reasons.append("budget_below_floor")
    # A negative available budget is itself a malformed economic snapshot,
    # even when a caller supplied a negative floor that would otherwise make
    # the comparison appear safe.
    if budget_remaining is not None and budget_remaining < 0:
        reasons.append("budget_remaining_negative")
    status: Literal["allowed", "blocked"] = "blocked" if reasons else "allowed"
    canonical = {
        "status": status,
        "reasons": sorted(set(reasons)),
        "cash_available": str(cash_available) if cash_available is not None else None,
        "min_cash": str(min_cash) if min_cash is not None else None,
        "margin_rate": str(margin_rate) if margin_rate is not None else None,
        "min_margin_rate": str(min_margin_rate) if min_margin_rate is not None else None,
        "inventory_days": str(inventory_days) if inventory_days is not None else None,
        "max_inventory_days": str(max_inventory_days) if max_inventory_days is not None else None,
        "budget_remaining": str(budget_remaining) if budget_remaining is not None else None,
        "min_budget_remaining": str(min_budget_remaining) if min_budget_remaining is not None else None,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return EconomicGuardResult(status=status, reasons=tuple(reasons), snapshot_sha256=digest)
