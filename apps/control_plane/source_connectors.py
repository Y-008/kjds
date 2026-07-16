from __future__ import annotations

from dataclasses import dataclass

from .sourcing import SourcePlatform


@dataclass(frozen=True, slots=True)
class SourceConnectorCapability:
    platform: SourcePlatform
    ingestion: str
    authentication: str
    product_data: bool
    price_data: bool
    logistics_hint: bool
    notes: str


SOURCE_CONNECTORS = (
    SourceConnectorCapability(
        SourcePlatform.ALIBABA_1688,
        "firecrawl_browser",
        "seller_login",
        True,
        True,
        True,
        "优先供货源；登录态采集阶梯价、MOQ、规格、重量和国内运费",
    ),
    SourceConnectorCapability(
        SourcePlatform.TAOBAO,
        "firecrawl_browser",
        "buyer_login",
        True,
        True,
        True,
        "补充零售价格与评价，不作为稳定批发库存事实",
    ),
    SourceConnectorCapability(
        SourcePlatform.TMALL, "firecrawl_browser", "buyer_login", True, True, True, "品牌与规格对标"
    ),
    SourceConnectorCapability(
        SourcePlatform.JD, "firecrawl_browser", "optional_login", True, True, True, "适合标准品规格和国内零售价校验"
    ),
    SourceConnectorCapability(
        SourcePlatform.PINDUODUO,
        "firecrawl_browser",
        "buyer_login",
        True,
        True,
        False,
        "只作价格雷达，供应稳定性需人工验证",
    ),
    SourceConnectorCapability(
        SourcePlatform.ALIBABA, "api_or_firecrawl", "api_key_or_login", True, True, True, "全球批发供货源"
    ),
    SourceConnectorCapability(
        SourcePlatform.ALIEXPRESS, "api_or_firecrawl", "api_key_or_login", True, True, True, "跨境零售竞争与样品采购"
    ),
    SourceConnectorCapability(
        SourcePlatform.AMAZON,
        "sp_api_or_firecrawl",
        "seller_api_or_public",
        True,
        True,
        False,
        "市场价格与内容对标，不推定销量",
    ),
    SourceConnectorCapability(
        SourcePlatform.TEMU, "firecrawl_browser", "optional_login", True, True, False, "低价竞争雷达"
    ),
    SourceConnectorCapability(SourcePlatform.SHOPIFY, "admin_api", "store_token", True, True, True, "自有或已授权店铺"),
    SourceConnectorCapability(
        SourcePlatform.WOOCOMMERCE, "rest_api", "consumer_key", True, True, True, "自有或已授权店铺"
    ),
)


def source_connector_catalog() -> list[dict]:
    return [
        {
            "platform": item.platform.value,
            "ingestion": item.ingestion,
            "authentication": item.authentication,
            "capabilities": {
                "product_data": item.product_data,
                "price_data": item.price_data,
                "logistics_hint": item.logistics_hint,
            },
            "notes": item.notes,
            "status": "ready_for_credentials",
        }
        for item in SOURCE_CONNECTORS
    ]
