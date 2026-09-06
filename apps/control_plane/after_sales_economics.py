"""Risk-adjusted profit for after-sales exposure and reopened settlements."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

ClaimStatus = Literal["none", "open", "approved", "paid", "rejected", "reopened"]


@dataclass(frozen=True, slots=True)
class AfterSalesProfitInput:
    realized_profit: Decimal
    expected_return_cost: Decimal = Decimal("0")
    chargeback_reserve: Decimal = Decimal("0")
    recovery_amount: Decimal = Decimal("0")
    reopened_settlement: Decimal = Decimal("0")
    claim_status: ClaimStatus = "none"


@dataclass(frozen=True, slots=True)
class AfterSalesProfitResult:
    realized_profit: Decimal
    risk_adjusted_profit: Decimal
    expected_return_cost: Decimal
    chargeback_reserve: Decimal
    recovery_amount: Decimal
    reopened_settlement: Decimal
    claim_status: ClaimStatus
    status: Literal["VALID", "BLOCKED"]
    snapshot_sha256: str


def calculate_after_sales_profit(values: AfterSalesProfitInput) -> AfterSalesProfitResult:
    """Keep realized cash separate from reserves and later recoveries."""

    for name, amount in (
        ("expected_return_cost", values.expected_return_cost),
        ("chargeback_reserve", values.chargeback_reserve),
        ("recovery_amount", values.recovery_amount),
        ("reopened_settlement", values.reopened_settlement),
    ):
        if amount < 0:
            raise ValueError(f"{name} cannot be negative")
    risk_adjusted = (
        values.realized_profit
        - values.expected_return_cost
        - values.chargeback_reserve
        + values.recovery_amount
        - values.reopened_settlement
    )
    status: Literal["VALID", "BLOCKED"] = "VALID"
    canonical = {
        "realized_profit": str(values.realized_profit),
        "expected_return_cost": str(values.expected_return_cost),
        "chargeback_reserve": str(values.chargeback_reserve),
        "recovery_amount": str(values.recovery_amount),
        "reopened_settlement": str(values.reopened_settlement),
        "claim_status": values.claim_status,
        "risk_adjusted_profit": str(risk_adjusted),
        "status": status,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return AfterSalesProfitResult(
        realized_profit=values.realized_profit,
        risk_adjusted_profit=risk_adjusted,
        expected_return_cost=values.expected_return_cost,
        chargeback_reserve=values.chargeback_reserve,
        recovery_amount=values.recovery_amount,
        reopened_settlement=values.reopened_settlement,
        claim_status=values.claim_status,
        status=status,
        snapshot_sha256=digest,
    )


__all__ = ["AfterSalesProfitInput", "AfterSalesProfitResult", "calculate_after_sales_profit"]
