from __future__ import annotations

from typing import Literal

type ObservationMarketplace = Literal[
    "1688",
    "alibaba",
    "ozon",
    "pinduoduo",
    "taobao",
    "tmall",
    "tvcmall",
    "xianyu",
    "yiwugo",
]

SALES_MARKETPLACES = frozenset({"ozon"})
SUPPLIER_MARKETPLACES = frozenset(
    {
        "1688",
        "alibaba",
        "pinduoduo",
        "taobao",
        "tmall",
        "tvcmall",
        "xianyu",
        "yiwugo",
    }
)
OBSERVATION_MARKETPLACES = SALES_MARKETPLACES | SUPPLIER_MARKETPLACES


def is_supplier_marketplace(value: object) -> bool:
    return str(value or "").strip().lower() in SUPPLIER_MARKETPLACES
