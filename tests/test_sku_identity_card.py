from apps.control_plane.sku_identity_card import (
    CORE_IDENTITY_SPECS,
    SKU_IDENTITY_CARD_FIELDS,
    build_identity_card,
    canonical_value,
    card_fingerprint,
    core_spec_mismatches,
    core_spec_missing,
    identity_card_summary,
)


def hoist_item(**overrides):
    item = {
        "source_url": "https://detail.1688.com/offer/1.html",
        "specifications": {
            "product_type": "electric_hoist",
            "额定载重": "500kg",
            "提升高度": "7.6m",
            "电压": "220V",
            "频率": "50Hz",
            "功率": "1500W",
            "单绳载重": "500kg",
            "双绳载重": "1000kg",
            "遥控方式": "radio",
            "整机重量": "32kg",
            "包装尺寸": "55x30x22cm",
            "配件清单": "遥控器, 挂钩",
        },
        "product_identity": {"model_or_variant": "PA500"},
    }
    item.update(overrides)
    return item


def test_build_identity_card_normalizes_aliases():
    card = build_identity_card(hoist_item())
    assert card["rated_load_kg"] == "500kg"
    assert card["voltage_v"] == "220V"
    assert card["power_w"] == "1500W"
    assert card["supplier_url"] == "https://detail.1688.com/offer/1.html"
    assert set(card) == set(SKU_IDENTITY_CARD_FIELDS)


def test_canonical_value_converts_units():
    card = build_identity_card(
        {
            "specifications": {
                "额定载重": "0.5吨",
                "功率": "1.5kW",
                "电压": "220伏",
                "提升高度": "7.6米",
            }
        }
    )
    assert canonical_value(card, "rated_load_kg") == "500"
    assert canonical_value(card, "power_w") == "1500"
    assert canonical_value(card, "voltage_v") == "220"
    assert canonical_value(card, "lift_height_m") == "7.6"


def test_core_spec_mismatches_catches_load_and_voltage_conflicts():
    market = build_identity_card(
        hoist_item(specifications={"额定载重": "1000kg", "电压": "220V"})
    )
    supplier = build_identity_card(
        hoist_item(specifications={"额定载重": "500kg", "电压": "220V"})
    )
    assert core_spec_mismatches(market, supplier) == ["rated_load_kg"]

    supplier_380 = build_identity_card(
        hoist_item(specifications={"额定载重": "1000kg", "电压": "380V"})
    )
    assert core_spec_mismatches(market, supplier_380) == ["voltage_v"]


def test_same_value_different_units_are_not_a_mismatch():
    market = build_identity_card(
        hoist_item(specifications={"额定载重": "500kg"})
    )
    supplier = build_identity_card(
        hoist_item(specifications={"额定载重": "0.5t"})
    )
    assert core_spec_mismatches(market, supplier) == []


def test_empty_core_specs_are_missing_but_not_mismatches():
    market = build_identity_card({"specifications": {}})
    supplier = build_identity_card({"specifications": {}})
    assert core_spec_mismatches(market, supplier) == []
    assert set(core_spec_missing(market)) == set(CORE_IDENTITY_SPECS)
    summary = identity_card_summary(market, supplier)
    assert summary["status"] == "unverifiable"
    assert summary["confirmed_mismatches"] == []


def test_verified_summary_when_core_specs_agree():
    market = build_identity_card(hoist_item())
    supplier = build_identity_card(hoist_item())
    summary = identity_card_summary(market, supplier)
    assert summary["status"] == "verified"
    assert summary["confirmed_mismatches"] == []
    assert len(summary["market_card_fingerprint"]) == 64
    assert len(summary["supplier_card_fingerprint"]) == 64


def test_fingerprint_is_stable_and_sensitive_to_specs():
    first = build_identity_card(hoist_item())
    second = build_identity_card(hoist_item())
    changed = build_identity_card(
        hoist_item(specifications={"额定载重": "1000kg"})
    )
    assert card_fingerprint(first) == card_fingerprint(second)
    assert card_fingerprint(first) != card_fingerprint(changed)
