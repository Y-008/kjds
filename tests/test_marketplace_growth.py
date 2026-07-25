from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.control_plane.marketplace_growth import MarketplaceGrowthPlanner
from apps.control_plane.marketplace_growth_workspace import (
    InMemoryMarketplaceGrowthStore,
    MarketplaceGrowthWorkspace,
)


class FakeStore:
    def __init__(self, scenarios: dict[str, object], offers: dict[str, object]) -> None:
        self.scenarios = scenarios
        self.offers = offers

    def get_scenario(self, scenario_id: str):
        return self.scenarios[scenario_id]

    def get_offer(self, offer_id: str):
        return self.offers[offer_id]


class FakeSourcing:
    @staticmethod
    def release_ready(scenario) -> bool:
        return scenario.release_ready


class FakeRepository:
    @staticmethod
    def get_product(product_id: str):
        return SimpleNamespace(id=product_id, name="Складная лестница")


class FakeEvidence:
    def __init__(self) -> None:
        self.validated: list[list[str]] = []

    def require_valid(self, evidence_ids: list[str]) -> None:
        self.validated.append(evidence_ids)


def scenario(
    *,
    scenario_id: str,
    price_rub: str,
    rub_per_cny: str = "11.50",
    fixed_costs_cny: str,
    release_ready: bool,
) -> object:
    price = Decimal(price_rub)
    fx = Decimal(rub_per_cny)
    revenue = price / fx
    platform_fee = revenue * Decimal("0.15")
    return_reserve = revenue * Decimal("0.05")
    advertising = Decimal("0")
    total = (
        Decimal(fixed_costs_cny)
        + platform_fee
        + return_reserve
        + advertising
    )
    return SimpleNamespace(
        id=scenario_id,
        offer_id=f"off_{scenario_id}",
        target_platform="OZON",
        inputs=SimpleNamespace(
            sale_price_rub=price,
            rub_per_cny=fx,
            platform_fee_rate=Decimal("0.15"),
            return_reserve_rate=Decimal("0.05"),
        ),
        revenue_cny=revenue,
        total_cost_cny=total,
        platform_fee_cny=platform_fee,
        advertising_cny=advertising,
        return_reserve_cny=return_reserve,
        release_ready=release_ready,
    )


def planner(*scenarios: object) -> tuple[MarketplaceGrowthPlanner, FakeEvidence]:
    evidence = FakeEvidence()
    scenario_map = {item.id: item for item in scenarios}
    offers = {
        item.offer_id: SimpleNamespace(
            id=item.offer_id,
            product_id=f"prd_{item.id}",
        )
        for item in scenarios
    }
    return (
        MarketplaceGrowthPlanner(
            sourcing_store=FakeStore(scenario_map, offers),
            sourcing=FakeSourcing(),
            repository=FakeRepository(),
            evidence=evidence,
        ),
        evidence,
    )


def observation(
    scenario_id: str,
    sku: str,
    *,
    prices: list[str],
    reviews: int = 2,
    orders: int = 0,
    stock: int = 8,
    rating: str = "5.0",
    content_score: str = "95.5",
    conversion_rate: str | None = None,
    compliance_risk: str = "low",
) -> dict:
    return {
        "scenario_id": scenario_id,
        "marketplace_sku": sku,
        "category": "folding ladder",
        "competitor_prices_rub": [Decimal(item) for item in prices],
        "stock": stock,
        "review_count": reviews,
        "orders_14d": orders,
        "rating": Decimal(rating),
        "content_score": Decimal(content_score),
        "conversion_rate": (
            Decimal(conversion_rate) if conversion_rate is not None else None
        ),
        "compliance_risk": compliance_risk,
        "observed_at": "2026-07-25T08:00:00+00:00",
        "evidence_ids": [f"ev_{sku}_market", f"ev_{sku}_seller"],
    }


def test_live_ladder_is_ranked_for_price_reset_before_ads() -> None:
    live = scenario(
        scenario_id="scn_ladder",
        price_rub="4163.50",
        fixed_costs_cny="80",
        release_ready=True,
    )
    service, evidence = planner(live)

    result = service.plan_portfolio(
        observations=[
            observation(
                "scn_ladder",
                "OZN2077394982",
                prices=["1303", "1714", "1996", "2103"],
            )
        ],
        target_cm3_rate=Decimal("0.15"),
        created_by="operator-1",
        as_of="2026-07-25T12:00:00+00:00",
    )

    row = result["portfolio"][0]
    assert row["commercial_status"] == "price_reset_required"
    assert row["current"]["price_position"] == "above_market"
    assert row["economics"]["recommended_test_price_rub"] == "1611.25"
    assert row["ad_eligible"] is False
    assert [item["type"] for item in row["actions"]] == [
        "run_price_reset_experiment",
        "complete_content_roles",
        "build_verified_review_depth",
        "prove_organic_conversion",
        "keep_ads_off",
    ]
    assert result["automatic_marketplace_write"] is False
    assert result["automatic_ad_spend"] is False
    assert evidence.validated == [
        ["ev_OZN2077394982_market", "ev_OZN2077394982_seller"]
    ]


def test_supplier_listing_cost_cannot_unlock_advertising() -> None:
    estimated = scenario(
        scenario_id="scn_estimated",
        price_rub="1800",
        fixed_costs_cny="60",
        release_ready=False,
    )
    service, _ = planner(estimated)

    result = service.plan_portfolio(
        observations=[
            observation(
                "scn_estimated",
                "OZN-EST",
                prices=["1600", "1750", "1850", "2000"],
                reviews=20,
                orders=5,
                content_score="100",
                conversion_rate="0.03",
            )
        ],
        target_cm3_rate=Decimal("0.15"),
        created_by="operator-1",
        as_of="2026-07-25T12:00:00+00:00",
    )

    row = result["portfolio"][0]
    assert row["commercial_status"] == "cost_authority_required"
    assert row["gates"]["cost_release_ready"] is False
    assert row["ad_eligible"] is False
    assert row["actions"][0]["type"] == "verify_actual_landed_cost"


def test_aligned_proven_sku_gets_a_bounded_ad_ceiling() -> None:
    proven = scenario(
        scenario_id="scn_proven",
        price_rub="1800",
        fixed_costs_cny="60",
        release_ready=True,
    )
    service, _ = planner(proven)

    result = service.plan_portfolio(
        observations=[
            observation(
                "scn_proven",
                "OZN-PROVEN",
                prices=["1600", "1750", "1850", "2000"],
                reviews=20,
                orders=5,
                content_score="100",
                conversion_rate="0.03",
            )
        ],
        target_cm3_rate=Decimal("0.15"),
        created_by="operator-1",
        as_of="2026-07-25T12:00:00+00:00",
    )

    row = result["portfolio"][0]
    assert row["commercial_status"] == "ad_test_eligible"
    assert row["ad_eligible"] is True
    assert Decimal(row["economics"]["target_acos_ceiling"]) > 0
    assert Decimal(row["economics"]["max_cpc_cny"]) > 0
    assert row["actions"][-1]["type"] == "start_capped_ad_experiment"


def test_high_compliance_risk_overrides_growth_priority() -> None:
    risky = scenario(
        scenario_id="scn_risky",
        price_rub="1800",
        fixed_costs_cny="60",
        release_ready=True,
    )
    service, _ = planner(risky)

    result = service.plan_portfolio(
        observations=[
            observation(
                "scn_risky",
                "OZN-RISK",
                prices=["1600", "1750", "1850"],
                reviews=20,
                orders=5,
                content_score="100",
                conversion_rate="0.03",
                compliance_risk="high",
            )
        ],
        target_cm3_rate=Decimal("0.15"),
        created_by="operator-1",
        as_of="2026-07-25T12:00:00+00:00",
    )

    row = result["portfolio"][0]
    assert row["commercial_status"] == "compliance_hold"
    assert row["priority_score"] == -100
    assert row["actions"] == [
        {
            "type": "hold_listing",
            "reason": "Resolve product compliance or intellectual-property risk before growth work",
        }
    ]


def test_medium_compliance_risk_requires_review_and_blocks_ads() -> None:
    medium = scenario(
        scenario_id="scn_medium",
        price_rub="1800",
        fixed_costs_cny="60",
        release_ready=True,
    )
    service, _ = planner(medium)

    result = service.plan_portfolio(
        observations=[
            observation(
                "scn_medium",
                "OZN-MEDIUM",
                prices=["1600", "1750", "1850"],
                reviews=20,
                orders=5,
                content_score="100",
                conversion_rate="0.03",
                compliance_risk="medium",
            )
        ],
        target_cm3_rate=Decimal("0.15"),
        created_by="operator-1",
        as_of="2026-07-25T12:00:00+00:00",
    )

    row = result["portfolio"][0]
    assert row["commercial_status"] == "compliance_review_required"
    assert row["ad_eligible"] is False
    assert row["actions"][0]["type"] == "complete_compliance_review"


def test_market_snapshots_require_three_prices_and_unique_skus() -> None:
    first = scenario(
        scenario_id="scn_a",
        price_rub="1800",
        fixed_costs_cny="60",
        release_ready=True,
    )
    second = scenario(
        scenario_id="scn_b",
        price_rub="1800",
        fixed_costs_cny="60",
        release_ready=True,
    )
    service, _ = planner(first, second)

    with pytest.raises(ValueError, match="at least 3"):
        service.plan_portfolio(
            observations=[
                observation("scn_a", "OZN-A", prices=["1600", "1700"])
            ],
            target_cm3_rate=Decimal("0.15"),
            created_by="operator-1",
            as_of="2026-07-25T12:00:00+00:00",
        )

    with pytest.raises(ValueError, match="duplicate SKUs"):
        service.plan_portfolio(
            observations=[
                observation("scn_a", "OZN-DUP", prices=["1600", "1700", "1800"]),
                observation("scn_b", "OZN-DUP", prices=["1600", "1700", "1800"]),
            ],
            target_cm3_rate=Decimal("0.15"),
            created_by="operator-1",
            as_of="2026-07-25T12:00:00+00:00",
        )


def test_workspace_persists_idempotent_facts_and_plans_latest_portfolio() -> None:
    live = scenario(
        scenario_id="scn_workspace",
        price_rub="1800",
        fixed_costs_cny="60",
        release_ready=True,
    )
    service, _ = planner(live)
    workspace = MarketplaceGrowthWorkspace(
        planner=service,
        store=InMemoryMarketplaceGrowthStore(),
    )
    facts = observation(
        "scn_workspace",
        "OZN-WORKSPACE",
        prices=["1600", "1750", "1850", "2000"],
        reviews=20,
        orders=5,
        content_score="100",
        conversion_rate="0.03",
    )

    first = workspace.capture_snapshot(
        source="operator_verified",
        idempotency_key="workspace-import-1",
        observations=[facts],
        captured_by="operator-1",
    )
    replay = workspace.capture_snapshot(
        source="operator_verified",
        idempotency_key="workspace-import-1",
        observations=[facts],
        captured_by="operator-1",
    )

    assert replay["id"] == first["id"]
    assert replay["snapshot_hash"] == first["snapshot_hash"]
    latest = workspace.latest_observations()
    assert latest[0]["marketplace_sku"] == "OZN-WORKSPACE"
    assert latest[0]["snapshot_id"] == first["id"]

    plan = workspace.plan_latest(
        target_cm3_rate=Decimal("0.15"),
        created_by="operator-1",
        as_of="2026-07-25T12:00:00+00:00",
    )
    assert plan["summary"]["sku_count"] == 1
    assert plan["portfolio"][0]["commercial_status"] == "ad_test_eligible"
    assert plan["automatic_marketplace_write"] is False


def test_workspace_rejects_changed_payload_under_same_idempotency_key() -> None:
    live = scenario(
        scenario_id="scn_conflict",
        price_rub="1800",
        fixed_costs_cny="60",
        release_ready=True,
    )
    service, _ = planner(live)
    workspace = MarketplaceGrowthWorkspace(
        planner=service,
        store=InMemoryMarketplaceGrowthStore(),
    )
    facts = observation(
        "scn_conflict",
        "OZN-CONFLICT",
        prices=["1600", "1750", "1850"],
    )
    workspace.capture_snapshot(
        source="ozon_export",
        idempotency_key="export-1",
        observations=[facts],
        captured_by="operator-1",
    )

    changed = {**facts, "stock": 99}
    with pytest.raises(ValueError, match="idempotency conflict"):
        workspace.capture_snapshot(
            source="ozon_export",
            idempotency_key="export-1",
            observations=[changed],
            captured_by="operator-1",
        )
