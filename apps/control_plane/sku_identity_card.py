"""Lightweight canonical SKU identity card (BAS-104 trial phase).

The full "three Passports" machinery is a scale-up governance artifact.  For
the current trial phase (1688 supply -> Ozon market -> cost/profit matching)
the operator asked for a lightweight identity card that prevents dangerous
spec mismatches: matching a 500kg purchase price against a 1000kg Ozon sale,
conflating single-rope and double-rope loads, or comparing 220V/50Hz bare
machines with 380V or set-inclusive offers.

The card is a flat, canonical 17-field record built deterministically from
observation specifications and identity fields.  A small set of core specs
must agree between the market side and the supply side before a match is
allowed; unverifiable (empty on both sides) stays compatible but is reported
as a gap, never guessed.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

CONTRACT_ID = "kjds-sku-identity-card-v1"
POLICY_VERSION = "2026-08-02.1"

SKU_IDENTITY_CARD_FIELDS: tuple[str, ...] = (
    "sku_id",
    "product_type",
    "rated_load_kg",
    "single_rope_load_kg",
    "double_rope_load_kg",
    "lift_height_m",
    "lift_speed_m_min",
    "voltage_v",
    "frequency_hz",
    "power_w",
    "wire_rope_spec",
    "remote_control_type",
    "machine_weight_kg",
    "package_dimensions_cm",
    "accessory_list",
    "supplier_url",
    "main_image_url",
)

# Fields that must agree exactly between market and supply before matching.
# These are the failure modes the operator called out: load, voltage,
# frequency, power, lift height and product type.
CORE_IDENTITY_SPECS: tuple[str, ...] = (
    "product_type",
    "rated_load_kg",
    "lift_height_m",
    "voltage_v",
    "frequency_hz",
    "power_w",
)

_ALIASES: dict[str, str] = {}
for _field, _aliases in {
    "sku_id": ("sku_id", "sku", "内部sku", "内部sku id"),
    "product_type": (
        "product_type",
        "产品类型",
        "类型",
        "商品类型",
        "category",
        "品类",
    ),
    "rated_load_kg": ("rated_load_kg", "额定载重", "额定起重量", "载重", "起重量"),
    "single_rope_load_kg": (
        "single_rope_load_kg",
        "单绳载重",
        "单绳起重量",
        "单绳额定载重",
    ),
    "double_rope_load_kg": (
        "double_rope_load_kg",
        "双绳载重",
        "双绳起重量",
        "双绳额定载重",
    ),
    "lift_height_m": ("lift_height_m", "提升高度", "起升高度"),
    "lift_speed_m_min": ("lift_speed_m_min", "提升速度", "起升速度"),
    "voltage_v": ("voltage_v", "电压", "额定电压"),
    "frequency_hz": ("frequency_hz", "频率", "额定频率"),
    "power_w": ("power_w", "功率", "电机功率", "额定功率"),
    "wire_rope_spec": ("wire_rope_spec", "钢丝绳规格", "钢丝绳"),
    "remote_control_type": ("remote_control_type", "遥控方式", "遥控", "遥控器"),
    "machine_weight_kg": ("machine_weight_kg", "整机重量", "主机重量", "净重"),
    "package_dimensions_cm": ("package_dimensions_cm", "包装尺寸", "箱子尺寸"),
    "accessory_list": ("accessory_list", "配件清单", "配件", "附件"),
    "supplier_url": ("supplier_url", "供应商链接", "商品链接", "链接"),
    "main_image_url": ("main_image_url", "主图", "主图链接", "图片"),
}.items():
    for _alias in _aliases:
        _ALIASES[_alias] = _field

_ALIASES_BY_FIELD: dict[str, tuple[str, ...]] = {
    field: (field, *[
        alias
        for alias, target in _ALIASES.items()
        if target == field and alias != field
    ])
    for field in SKU_IDENTITY_CARD_FIELDS
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _parse_number(value: str) -> Decimal | None:
    match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _normalize_measure(value: Any, field: str) -> str:
    """Canonical scalar for comparison, with unit conversion where safe."""
    text = _clean(value).lower()
    if not text:
        return ""
    number = _parse_number(text)
    if number is None:
        return text
    if field in {
        "rated_load_kg",
        "single_rope_load_kg",
        "double_rope_load_kg",
        "machine_weight_kg",
    }:
        if "t" in text or "吨" in text:
            number = number * 1000
        return _fmt(number)
    if field == "power_w":
        if "kw" in text or "千瓦" in text:
            number = number * 1000
        return _fmt(number)
    if field in {"lift_height_m", "lift_speed_m_min"}:
        return _fmt(number)
    if field in {"voltage_v", "frequency_hz"}:
        return _fmt(number)
    return text


def _fmt(value: Decimal) -> str:
    text = format(value.quantize(Decimal("0.001")), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def build_identity_card(item: dict[str, Any]) -> dict[str, str]:
    """Build the canonical 17-field card from an observation item."""
    merged: dict[str, str] = {}
    for source in (
        item.get("specifications") or {},
        item.get("product_identity") or {},
        item,
    ):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            merged[str(key).strip()] = _clean(value)
    card = {
        field: next(
            (
                merged[alias]
                for alias in _ALIASES_BY_FIELD[field]
                if alias in merged and merged[alias]
            ),
            "",
        )
        for field in SKU_IDENTITY_CARD_FIELDS
    }
    card["supplier_url"] = (
        card["supplier_url"] or _clean(item.get("source_url"))
    )
    return card


def canonical_value(card: dict[str, str], field: str) -> str:
    if field not in CORE_IDENTITY_SPECS:
        return _clean(card.get(field))
    return _normalize_measure(card.get(field), field)


def card_fingerprint(card: dict[str, str]) -> str:
    payload = {
        field: canonical_value(card, field)
        for field in SKU_IDENTITY_CARD_FIELDS
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def core_spec_missing(card: dict[str, str]) -> list[str]:
    return [
        field
        for field in CORE_IDENTITY_SPECS
        if not canonical_value(card, field)
    ]


def core_spec_mismatches(
    market_card: dict[str, str],
    supplier_card: dict[str, str],
) -> list[str]:
    """Confirmed core-spec conflicts between market and supply sides.

    A field is only a confirmed conflict when BOTH sides carry a value and
    the normalized values differ.  Empty-on-one-side is reported through
    ``core_spec_missing`` and never blocks matching by itself.
    """
    mismatches: list[str] = []
    for field in CORE_IDENTITY_SPECS:
        market_value = canonical_value(market_card, field)
        supplier_value = canonical_value(supplier_card, field)
        if market_value and supplier_value and market_value != supplier_value:
            mismatches.append(field)
    return mismatches


def identity_card_summary(
    market_card: dict[str, str],
    supplier_card: dict[str, str],
) -> dict[str, Any]:
    mismatches = core_spec_mismatches(market_card, supplier_card)
    missing = sorted(
        set(core_spec_missing(market_card))
        | set(core_spec_missing(supplier_card))
    )
    return {
        "contract_id": CONTRACT_ID,
        "policy_version": POLICY_VERSION,
        "status": (
            "mismatch"
            if mismatches
            else "unverifiable"
            if missing
            else "verified"
        ),
        "confirmed_mismatches": mismatches,
        "missing_core_specs": missing,
        "market_card_fingerprint": card_fingerprint(market_card),
        "supplier_card_fingerprint": card_fingerprint(supplier_card),
    }
