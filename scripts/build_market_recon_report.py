"""Build a currency-safe market recon report without implicit FX assumptions."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from apps.control_plane.money import MoneyAmount

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "market_recon"

PRODUCT_MAP = {
    "1982483707WZ": "锂电电锯",
    "TWPIUXSZBTOODQ": "折叠躺椅床",
    "OFJMUOELWGCGMZ": "折叠躺椅床",
    "ZLPDYUJBMUGQHU": "折叠躺椅床",
    "2105343364UB": "500kg电动葫芦吊",
    "ATEMJPKDKQCVHW": "折叠躺椅床",
    "RSPESLAQIZSXKB": "双人帐篷",
    "ITYVEDRNIADNUB": "折叠躺椅床",
    "MCHVEQZUDYOHYV": "折叠躺椅床",
    "1990014542NP": "钢制折叠梯",
    "DEBZKZYGXJPRHY": "变色唇膏",
    "OYXJMGAXCUIKOE": "折叠躺椅床",
    "2113123792SW": "钢制折叠梯",
    "HDNQYWCJCTMBAK": "比特币硬币",
    "PKTCTVHQFJMGLA": "手机吸盘支架",
    "2116716320XB": "婴儿浴盆",
    "RYJLLGXJCNBEPU": "折叠躺椅床",
    "1743696264UY": "牧田DHR182电锤",
}


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _timestamp(value: str | None) -> datetime:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed
    return datetime.now(UTC)


def _money(
    amount: Any,
    currency: Any,
    occurred_at: str | None,
    evidence_id: str,
) -> dict[str, Any] | None:
    parsed = _decimal(amount)
    if parsed is None or not isinstance(currency, str):
        return None
    try:
        return MoneyAmount(
            amount=parsed,
            currency=currency,
            occurred_at=_timestamp(occurred_at),
            evidence_id=evidence_id,
        ).to_dict()
    except ValueError:
        return None


def _price_index(item: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    indexes = item.get("price_indexes") or {}
    ozon = indexes.get("ozon_index_data") or {}
    evidence_id = f"source:full_product_info.json#offer_id={item.get('offer_id', 'unknown')}"
    market_money = _money(
        ozon.get("minimal_price"),
        ozon.get("minimal_price_currency"),
        item.get("updated_at"),
        evidence_id,
    )
    provider_metric = {
        "price_index_value": str(ozon.get("price_index_value") or ""),
        "color_index": indexes.get("color_index") or "",
        "computed_by_kjds": False,
    }
    return market_money, provider_metric


def _supply_stats(keyword: str, supply: dict[str, Any]) -> dict[str, Any]:
    source = supply.get(keyword) or {}
    cards = source.get("supplier_cards") or []
    prices = [price for card in cards if (price := _decimal(card.get("price"))) is not None and price > 0]
    prices.sort()
    return {
        "keyword": keyword,
        "supplier_count": int(source.get("supplier_count") or 0),
        "observed_cards": len(cards),
        "raw_price_min": format(prices[0], "f") if prices else None,
        "raw_price_median": format(prices[len(prices) // 2], "f") if prices else None,
        "raw_price_max": format(prices[-1], "f") if prices else None,
        "currency": None,
        "decision_eligible": False,
        "reason_codes": ["money_currency_missing", "variant_identity_unresolved"] if prices else ["no_supply_price"],
    }


def _analytics_orders(info: list[dict[str, Any]], analytics: list[dict[str, Any]]) -> dict[str, str]:
    if not analytics:
        return {}

    def norm(value: str) -> str:
        return re.sub(r"[^a-zа-я0-9]+", "", (value or "").lower())

    response = analytics[0].get("response") or {}
    result = response.get("result") or {}
    source_rows = result.get("data") or []
    metrics_by_name = {
        norm(str((row.get("dimensions") or [{}])[0].get("name") or "")): row.get("metrics") or []
        for row in source_rows
    }
    orders: dict[str, str] = {}
    for item in info:
        item_name = norm(str(item.get("name") or ""))
        match = next((metrics for name, metrics in metrics_by_name.items() if item_name in name or name in item_name), None)
        if match:
            orders[str(item.get("offer_id"))] = str(match[0])
    return orders


def build_rows(
    info: list[dict[str, Any]],
    supply: dict[str, Any],
    analytics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    orders = _analytics_orders(info, analytics)
    rows: list[dict[str, Any]] = []
    for item in info:
        offer_id = str(item.get("offer_id") or "")
        evidence_id = f"source:full_product_info.json#offer_id={offer_id or 'unknown'}"
        own_price = _money(item.get("price"), item.get("currency_code"), item.get("updated_at"), evidence_id)
        old_price = _money(item.get("old_price"), item.get("currency_code"), item.get("updated_at"), evidence_id)
        minimum_price = _money(item.get("min_price"), item.get("currency_code"), item.get("updated_at"), evidence_id)
        market_price, provider_metric = _price_index(item)
        keyword = PRODUCT_MAP.get(offer_id, "")
        supplier = _supply_stats(keyword, supply) if keyword else {
            "keyword": "",
            "supplier_count": 0,
            "observed_cards": 0,
            "currency": None,
            "decision_eligible": False,
            "reason_codes": ["supplier_mapping_missing"],
        }
        blockers = list(supplier["reason_codes"])
        if own_price is None:
            blockers.append("own_price_currency_missing_or_invalid")
        if market_price is None:
            blockers.append("market_price_currency_missing_or_invalid")
        if own_price and market_price and own_price["currency"] != market_price["currency"]:
            blockers.append("fx_basis_missing")
        rows.append(
            {
                "candidate_id": f"ozon:{offer_id}",
                "offer_id": offer_id,
                "name": item.get("name") or "",
                "own_price": own_price,
                "old_price": old_price,
                "minimum_price": minimum_price,
                "market_reference_price": market_price,
                "provider_price_index": provider_metric,
                "supplier_observation": supplier,
                "orders_observed": orders.get(offer_id, "0"),
                "profit_basis": {
                    "scenario_profit": None,
                    "accrual_profit": None,
                    "settlement_profit": None,
                    "cash_profit": None,
                },
                "decision_class": "needs_data",
                "decision_eligible": False,
                "reason_codes": sorted(set(blockers)),
                "automatic_reprice_allowed": False,
                "pilot_proposal_allowed": False,
            }
        )
    return rows


def _format_money(value: dict[str, Any] | None) -> str:
    return f"{value['amount']} {value['currency']}" if value else "UNKNOWN"


def build_report(rows: list[dict[str, Any]], finance: list[dict[str, Any]], generated_at: datetime) -> str:
    finance_operations = sum(len(month.get("operations") or []) for month in finance)
    lines = [
        "# Ozon × 1688 市场侦察报告（币种真相修复版）",
        "",
        f"生成时间：{generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "> **决策状态：BLOCKED / NEEDS_DATA。** 本报告不使用假设汇率，不计算利润、不提出调价或扩量建议。旧版将 CNY 自有售价与 RUB 市场参考直接比较，相关结论已经永久失效。",
        "",
        "## 一、可信范围",
        "",
        f"- 商品详情：{len(rows)} 个 SKU，原币种和来源位置已保留。",
        f"- 财务：{len(finance)} 个月窗口、{finance_operations} 条 operation 已采集，但记录缺显式币种，故不汇总净额。",
        "- 1688：原始价格完整保留；缺显式币种和精确变体匹配的记录不进入成本或利润计算。",
        "- Ozon `price_index_value` 仅作为平台返回的原始指标展示，KJDS 不在币种不一致时重算或据此调价。",
        "",
        "## 二、逐 SKU 币种隔离视图",
        "",
        "| SKU | 商品 | 自有售价 | 市场参考 | 平台指数 | 1688 原始中位值 | 决策 | 阻断原因 |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        supplier = row["supplier_observation"]
        raw_supply = supplier.get("raw_price_median") or "UNKNOWN"
        reasons = ", ".join(row["reason_codes"])
        lines.append(
            f"| {row['offer_id']} | {str(row['name'])[:36]} | {_format_money(row['own_price'])} | "
            f"{_format_money(row['market_reference_price'])} | {row['provider_price_index']['price_index_value']} | "
            f"{raw_supply} (currency UNKNOWN) | needs_data | {reasons} |"
        )
    lines.extend(
        [
            "",
            "## 三、解除阻断所需证据",
            "",
            "1. 提供发生时间匹配、来源可回查的 CNY→RUB `FxBasis`，再生成展示币种转换；原金额不得被覆盖。",
            "2. 明确 Finance API 每个金额字段的官方币种语义，并以官方合同/导出 Evidence 固化后再汇总应计利润。",
            "3. 为 1688 报价补齐显式币种、精确变体、MOQ、包装重量、报价时间和供应商原件，才能形成 landed cost。",
            "4. 取得结算和银行到账证据后，分别计算 settlement profit 与 cash profit，不以 scenario profit 替代。",
            "5. 仅在 downside CM3 为正且证据齐全时创建小额 Pilot Proposal；否则继续 `needs_data/blocked`。",
            "",
            "## 四、自动化边界",
            "",
            "- `automatic_reprice_allowed=false`",
            "- `pilot_proposal_allowed=false`",
            "- `external_write_allowed=false`",
            "- 原始数据允许全量入库；质量只决定可用层级，不决定是否保留。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    info = json.loads((OUT / "full_product_info.json").read_text(encoding="utf-8"))
    supply = json.loads((OUT / "supply_1688" / "supply_crawl.json").read_text(encoding="utf-8"))
    analytics = json.loads((OUT / "analytics_by_window.json").read_text(encoding="utf-8"))
    finance = json.loads((OUT / "finance_by_month.json").read_text(encoding="utf-8"))
    generated_at = datetime.now(UTC)
    rows = build_rows(info, supply, analytics)
    report = build_report(rows, finance, generated_at)
    (OUT / "market_recon_report_currency_safe.md").write_text(report, encoding="utf-8")
    (OUT / "per_sku_analysis_currency_safe.json").write_text(
        json.dumps(
            {
                "schema_version": "kjds-market-recon-currency-safe-v1",
                "status": "blocked",
                "generated_at": generated_at.isoformat(),
                "reason_codes": ["fx_basis_missing", "finance_currency_missing", "supplier_currency_missing"],
                "records": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
