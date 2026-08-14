import json
from pathlib import Path

import pytest

from scripts.build_market_recon_report import OUT, build_report, build_rows

pytestmark = pytest.mark.skipif(
    not all(
        (OUT / name).is_file()
        for name in (
            "full_product_info.json",
            "supply_1688/supply_crawl.json",
            "analytics_by_window.json",
            "finance_by_month.json",
        )
    ),
    reason="market-recon report fixtures are not committed",
)


def _load(name: str):  # type: ignore[no-untyped-def]
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_real_market_recon_rows_never_compare_cny_to_rub() -> None:
    info = _load("full_product_info.json")
    supply = _load("supply_1688/supply_crawl.json")
    analytics = _load("analytics_by_window.json")

    rows = build_rows(info, supply, analytics)

    assert len(rows) == 18
    assert all(row["own_price"]["currency"] == "CNY" for row in rows)
    observed_market_prices = [row["market_reference_price"] for row in rows if row["market_reference_price"]]
    missing_market_prices = [row for row in rows if row["market_reference_price"] is None]
    assert observed_market_prices
    assert all(price["currency"] == "RUB" for price in observed_market_prices)
    assert all("market_price_currency_missing_or_invalid" in row["reason_codes"] for row in missing_market_prices)
    assert all(row["decision_class"] == "needs_data" for row in rows)
    assert all(row["profit_basis"]["scenario_profit"] is None for row in rows)
    assert all(
        "fx_basis_missing" in row["reason_codes"]
        for row in rows
        if row["market_reference_price"] is not None
    )
    assert all(row["automatic_reprice_allowed"] is False for row in rows)
    assert all(row["pilot_proposal_allowed"] is False for row in rows)


def test_currency_safe_report_refuses_finance_sum_without_currency() -> None:
    info = _load("full_product_info.json")
    supply = _load("supply_1688/supply_crawl.json")
    analytics = _load("analytics_by_window.json")
    finance = _load("finance_by_month.json")
    rows = build_rows(info, supply, analytics)

    from datetime import UTC, datetime

    report = build_report(rows, finance, datetime(2026, 8, 2, tzinfo=UTC))

    assert "BLOCKED / NEEDS_DATA" in report
    assert "记录缺显式币种，故不汇总净额" in report
    assert "320.00 CNY" in report
    assert "1925.94 RUB" in report
    assert "假设汇率" in report
    assert "12.5" not in report
    assert "automatic_reprice_allowed=false" in report


def test_old_market_recon_artifact_is_marked_invalidated() -> None:
    legacy = Path(OUT / "market_recon_report.md").read_text(encoding="utf-8")
    assert "INVALIDATED" in legacy[:500]
