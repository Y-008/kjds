"""Risk-adjusted expected contribution profit simulation (BAS-104 extension).

The batch-opportunity economics previously produced two deterministic cost
cases (baseline and downside).  This module upgrades the candidate economics
with a seeded Monte Carlo distribution over the uncertain 15-item cost
components, selling price, returns, supply failure and price-war loss, and
returns a risk-adjusted decision utility:

    utility = E[profit] - lambda * CVaR_loss_10% - mu * return_risk - nu * stockout_risk

The deterministic downside CM3 stays the hard admission gate; this module only
ranks/annotates.  All randomness is seeded from a stable policy version plus
the candidate fingerprint so every run is reproducible and auditable.

``CVaR_loss_10%`` is the expected *loss* in the worst decile, i.e. the
non-negative max(0, -tail mean profit); the raw worst-decile mean profit is
kept in the result as ``cvar_10_cny`` for audit.
"""

from __future__ import annotations

import hashlib
import random
from decimal import Decimal
from typing import Any

CONTRACT_ID = "kjds-risk-adjusted-profit-simulation-v1"
POLICY_VERSION = "2026-08-02.1"
SCENARIOS = 2000
CVAR_ALPHA = Decimal("0.10")
LAMBDA = Decimal("1.0")
MU = Decimal("0.5")
NU = Decimal("0.5")
DEFAULT_PRICE_VOLATILITY = Decimal("0.05")
DEFAULT_RETURN_RATE = Decimal("0.05")
DEFAULT_SUPPLY_FAILURE_PROB = Decimal("0.05")
DEFAULT_PRICE_WAR_PROB = Decimal("0.10")


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


class RiskAdjustedProfitSimulator:
    """Seeded Monte Carlo simulation of candidate contribution profit."""

    def simulate(
        self,
        *,
        revenue_cny: Decimal,
        baseline_components: list[dict[str, Any]],
        downside_components: list[dict[str, Any]],
        seed_input: str,
        price_volatility: Decimal | None = None,
        return_rate: Decimal | None = None,
        supply_failure_prob: Decimal | None = None,
        price_war_prob: Decimal | None = None,
    ) -> dict[str, Any]:
        revenue = Decimal(revenue_cny)
        price_vol = price_volatility or DEFAULT_PRICE_VOLATILITY
        ret_rate = return_rate or DEFAULT_RETURN_RATE
        supply_fail = supply_failure_prob or DEFAULT_SUPPLY_FAILURE_PROB
        war_prob = price_war_prob or DEFAULT_PRICE_WAR_PROB
        for value, name in (
            (price_vol, "price_volatility"),
            (ret_rate, "return_rate"),
            (supply_fail, "supply_failure_prob"),
            (war_prob, "price_war_prob"),
        ):
            if value < 0 or value > 1:
                raise ValueError(f"{name} must be between 0 and 1")
        if revenue <= 0:
            raise ValueError("revenue_cny must be positive")
        baseline = {
            str(item.get("name") or ""): Decimal(
                str(item.get("amount_cny") or "0")
            )
            for item in baseline_components
        }
        downside = {
            str(item.get("name") or ""): Decimal(
                str(item.get("amount_cny") or "0")
            )
            for item in downside_components
        }
        names = [str(item.get("name") or "") for item in baseline_components]
        if names != [str(item.get("name") or "") for item in downside_components]:
            raise ValueError("Baseline and downside component sets differ")
        evidence_backed = {
            str(item.get("name") or "")
            for item in baseline_components
            if item.get("authority") == "evidence_backed_observation"
        }

        seed = int.from_bytes(
            hashlib.sha256(
                f"{POLICY_VERSION}:{seed_input}".encode()
            ).digest()[:8],
            "big",
        )
        rng = random.Random(seed)
        profits: list[Decimal] = []
        for _ in range(SCENARIOS):
            # Selling price: log-normal around revenue.
            price = revenue * Decimal(
                str(rng.lognormvariate(0.0, float(price_vol)))
            )
            # Sample each uncertain component between its baseline and
            # downside amount (mode at baseline); evidence-backed costs are
            # fixed observations and are not sampled.
            total_cost = Decimal("0")
            for name in names:
                low = min(baseline[name], downside[name])
                high = max(baseline[name], downside[name])
                if name in evidence_backed or high <= low:
                    amount = baseline[name]
                else:
                    beta = rng.betavariate(2.0, 2.0)
                    amount = low + (high - low) * Decimal(str(beta))
                total_cost += amount
            profit = price - total_cost
            # Return loss: expected return costs a fraction of the sale.
            if rng.random() < float(ret_rate):
                profit -= price * Decimal("0.5")
            # Supply failure: lost revenue and rework loss.
            if rng.random() < float(supply_fail):
                profit -= price * Decimal("0.25")
            # Price war: margin compression.
            if rng.random() < float(war_prob):
                profit -= revenue * Decimal("0.08")
            profits.append(profit)

        profits.sort()
        expected = _money(
            sum(profits) / Decimal(len(profits))
        )
        std = _money(
            (
                sum((p - expected) ** 2 for p in profits)
                / Decimal(len(profits))
            ).sqrt()
        )
        positive = sum(1 for p in profits if p > 0)
        p_positive = Decimal(positive) / Decimal(len(profits))
        tail_count = max(1, int(Decimal(len(profits)) * CVAR_ALPHA))
        tail = profits[:tail_count]
        cvar = _money(sum(tail) / Decimal(len(tail)))
        # Decision utility penalizes the expected tail *loss* (non-negative),
        # not the tail mean profit itself.
        cvar_loss = max(Decimal("0"), -cvar)
        utility = _money(
            expected
            - LAMBDA * cvar_loss
            - MU * ret_rate * revenue
            - NU * supply_fail * revenue
        )
        return {
            "contract_id": CONTRACT_ID,
            "policy_version": POLICY_VERSION,
            "scenarios": SCENARIOS,
            "seed_input_sha256": hashlib.sha256(
                seed_input.encode()
            ).hexdigest(),
            "expected_profit_cny": str(expected),
            "profit_std_cny": str(std),
            "p_profit_positive": str(p_positive),
            "cvar_10_cny": str(cvar),
            "cvar_loss_cny": str(cvar_loss),
            "decision_utility_cny": str(utility),
            "return_rate": str(ret_rate),
            "supply_failure_prob": str(supply_fail),
            "price_war_prob": str(war_prob),
            "price_volatility": str(price_vol),
            "deterministic": True,
        }
