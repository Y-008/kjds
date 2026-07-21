import json
from pathlib import Path

from apps.control_plane.cost_evidence_review import ACTUAL_COST_AUTHORITIES


def test_cost_authority_registry_covers_each_known_cost_without_global_authority():
    path = (
        Path(__file__).parents[1]
        / "docs"
        / "project"
        / "registries"
        / "cost_authority_sources.json"
    )
    registry = json.loads(path.read_text(encoding="utf-8"))

    assert registry["actual_authority_ids"] == {
        key: sorted(value) for key, value in ACTUAL_COST_AUTHORITIES.items()
    }

    sources = registry["sources"]
    ids = [source["id"] for source in sources]
    assert len(ids) == len(set(ids))
    assert {
        "product_cost",
        "domestic_logistics",
        "warehousing",
        "international_logistics",
        "last_mile",
        "platform_fee",
        "advertising",
        "refund",
        "return",
        "customs",
        "tax",
        "fx",
    } <= {cost_type for source in sources for cost_type in source["cost_types"]}

    for source in sources:
        assert source["estimate_authority"]
        assert source["actual_authority"]
        assert source["usage"]

    ozon = next(source for source in sources if source["id"] == "ozon_seller_finance")
    assert ozon["requires_review"] is True
    assert "report" in ozon["actual_authority"]
    assert ozon["seller_account_verified_at"] == "2026-07-19"
    assert any("ACCRUALS_DETAILS" in url for url in ozon["official_urls"])
    assert any("UNIT_ECONOMY" in url for url in ozon["official_urls"])

    fx = next(source for source in sources if source["id"] == "bank_of_russia_fx_reference")
    assert "booked" in fx["actual_authority"]


def test_official_cost_rules_are_registered_as_review_required_sources():
    root = Path(__file__).parents[1]
    cost_registry = json.loads(
        (root / "docs/project/registries/cost_authority_sources.json").read_text(
            encoding="utf-8"
        )
    )
    radar_registry = json.loads(
        (root / "docs/project/registries/authority_sources.json").read_text(
            encoding="utf-8"
        )
    )

    costs = {source["id"]: source for source in cost_registry["sources"]}
    radar = {source["id"]: source for source in radar_registry["sources"]}
    expected = {
        "ozon_crossborder_logistics_contract": (
            "ozon_seller_finance",
            "https://docs.ozon.ru/legal/en/partners/logistics/contract/?__rr=1",
        ),
        "ozon_pay_per_click_help": (
            "ozon_seller_finance",
            "https://docs.ozon.ru/global/promotion/product-promotions/pay-per-click/edit-and-pause/",
        ),
        "kuajing84_warehouse_help": (
            "kuajing84_fulfillment",
            "https://www.kuajing84.com/index/index/help_details/help_id/MDAwMDAwMDAwMH7QtWE.html",
        ),
    }
    for radar_id, (cost_id, url) in expected.items():
        assert url in costs[cost_id]["official_urls"]
        assert radar[radar_id]["url"] == url
        assert radar[radar_id]["type"] == "manual"
        assert radar[radar_id]["requires_review"] is True
        assert "actual" in radar[radar_id]["note"].lower() or "applicable" in radar[
            radar_id
        ]["note"].lower()
