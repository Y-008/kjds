from decimal import Decimal

from apps.control_plane.risk_adjusted_profit import (
    RiskAdjustedProfitSimulator,
)


def components(cost: str) -> list[dict]:
    names = [
        "procurement",
        "purchase_buffer",
        "domestic_logistics",
        "packaging",
        "international_logistics",
        "customs",
        "marketplace_commission",
        "fulfillment_last_mile",
        "warehousing",
        "advertising",
        "returns_refunds",
        "discounts_promotions",
        "taxes",
        "fx_reserve",
        "loss_damage",
    ]
    return [
        {
            "name": name,
            "amount_cny": cost,
            "authority": (
                "evidence_backed_observation"
                if name == "procurement"
                else "policy_estimate"
            ),
        }
        for name in names
    ]


def test_simulation_is_deterministic_and_reproducible():
    simulator = RiskAdjustedProfitSimulator()
    baseline = components("20.00")
    downside = components("30.00")
    first = simulator.simulate(
        revenue_cny=Decimal("80.00"),
        baseline_components=baseline,
        downside_components=downside,
        seed_input="candidate-fingerprint-1",
    )
    second = simulator.simulate(
        revenue_cny=Decimal("80.00"),
        baseline_components=baseline,
        downside_components=downside,
        seed_input="candidate-fingerprint-1",
    )
    assert first == second
    assert first["deterministic"] is True
    assert first["scenarios"] == 2000


def test_simulation_risk_metrics_are_consistent():
    simulator = RiskAdjustedProfitSimulator()
    result = simulator.simulate(
        revenue_cny=Decimal("100.00"),
        baseline_components=components("25.00"),
        downside_components=components("45.00"),
        seed_input="candidate-fingerprint-2",
        return_rate=Decimal("0.10"),
        supply_failure_prob=Decimal("0.10"),
        price_war_prob=Decimal("0.20"),
    )
    expected = Decimal(result["expected_profit_cny"])
    cvar = Decimal(result["cvar_10_cny"])
    utility = Decimal(result["decision_utility_cny"])
    assert Decimal(result["p_profit_positive"]) >= 0
    assert Decimal(result["p_profit_positive"]) <= 1
    assert cvar < expected  # tail mean is below the mean
    assert utility < expected  # risk penalties reduce utility
    # Decision utility = E - CVaR loss - MU*return_risk - NU*supply_risk.
    # With MU=NU=0.5, return_rate=supply_failure_prob=0.10, revenue=100.
    expected_loss = max(Decimal("0"), -cvar)
    assert utility == expected - expected_loss - Decimal("10.00")
    assert Decimal(result["cvar_loss_cny"]) == expected_loss
    assert all(
        key in result
        for key in (
            "expected_profit_cny",
            "profit_std_cny",
            "p_profit_positive",
            "cvar_10_cny",
            "decision_utility_cny",
        )
    )


def test_simulation_rejects_invalid_rates():
    simulator = RiskAdjustedProfitSimulator()
    try:
        simulator.simulate(
            revenue_cny=Decimal("100.00"),
            baseline_components=components("25.00"),
            downside_components=components("45.00"),
            seed_input="x",
            return_rate=Decimal("1.5"),
        )
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
