from decimal import Decimal

import pytest

from apps.control_plane.after_sales_economics import (
    AfterSalesProfitInput,
    calculate_after_sales_profit,
)


def test_after_sales_profit_separates_realized_and_risk_adjusted_values():
    result = calculate_after_sales_profit(
        AfterSalesProfitInput(
            realized_profit=Decimal("100"),
            expected_return_cost=Decimal("12"),
            chargeback_reserve=Decimal("8"),
            recovery_amount=Decimal("3"),
            reopened_settlement=Decimal("5"),
            claim_status="reopened",
        )
    )
    assert result.realized_profit == Decimal("100")
    assert result.risk_adjusted_profit == Decimal("78")
    assert result.status == "VALID"
    assert len(result.snapshot_sha256) == 64


def test_after_sales_costs_cannot_be_negative():
    with pytest.raises(ValueError, match="chargeback_reserve"):
        calculate_after_sales_profit(
            AfterSalesProfitInput(
                realized_profit=Decimal("10"),
                chargeback_reserve=Decimal("-1"),
            )
        )
