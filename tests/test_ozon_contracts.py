from apps.control_plane.ozon_contracts import (
    OzonRecordType,
    contract_catalog,
    detect_record_type,
    natural_key,
    normalize_record,
)


def test_catalog_exposes_versioned_contracts_for_all_formal_fact_types():
    catalog = contract_catalog()

    assert {item["record_type"] for item in catalog} == {item.value for item in OzonRecordType}
    assert {item["version"] for item in catalog} == {"ozon-v1"}
    assert all(item["required_fields"] for item in catalog)


def test_record_type_detection_covers_order_fee_return_and_settlement_exports():
    assert detect_record_type("orders.csv", ["order_id"]) is OzonRecordType.ORDER
    assert detect_record_type("transactions.csv", ["fee_type"]) is OzonRecordType.FEE
    assert detect_record_type("returns.csv", ["return_reason"]) is OzonRecordType.RETURN
    assert detect_record_type("payouts.csv", ["amount"]) is OzonRecordType.SETTLEMENT


def test_normalization_is_strict_and_time_zone_aware():
    normalized, errors = normalize_record(
        OzonRecordType.FEE,
        {
            "external_id": "operation-1",
            "fee_type": "delivery",
            "amount": "1 299,50",
            "currency": "rub",
            "effective_at": "2026-07-16T10:00:00+03:00",
        },
    )

    assert errors == []
    assert normalized["amount"] == "1299.50"
    assert normalized["currency"] == "RUB"
    assert normalized["effective_at"] == "2026-07-16T07:00:00+00:00"
    assert natural_key(OzonRecordType.FEE, normalized) == "operation-1:delivery"


def test_normalization_rejects_ambiguous_time_and_invalid_money():
    _, errors = normalize_record(
        OzonRecordType.SETTLEMENT,
        {
            "external_id": "payment-1",
            "amount": "not-money",
            "currency": "RUBLE",
            "effective_at": "2026-07-16 10:00:00",
        },
    )

    assert "amount: invalid decimal" in errors
    assert "currency: must be a three-letter code" in errors
    assert "effective_at must include a timezone" in errors
