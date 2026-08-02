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
    order = next(
        item for item in catalog if item["record_type"] == "ozon_order"
    )
    assert "store_ref" in order["optional_fields"]


def test_order_scope_is_preserved_for_sale_triggered_procurement():
    normalized, errors = normalize_record(
        OzonRecordType.ORDER,
        {
            "external_id": "order-1",
            "store_ref": "ozon-primary",
            "sku": "SKU-1",
            "quantity": "1",
            "gross_revenue": "1000",
            "currency": "RUB",
            "status": "awaiting_packaging",
            "effective_at": "2026-07-27T01:00:00+00:00",
        },
    )

    assert errors == []
    assert normalized["store_ref"] == "ozon-primary"
    assert normalized["status"] == "awaiting_packaging"


def test_record_type_detection_covers_order_fee_return_and_settlement_exports():
    assert detect_record_type("orders.csv", ["order_id"]) is OzonRecordType.ORDER
    assert detect_record_type("transactions.csv", ["fee_type"]) is OzonRecordType.FEE
    assert detect_record_type("returns.csv", ["return_reason"]) is OzonRecordType.RETURN
    assert detect_record_type("payouts.csv", ["amount"]) is OzonRecordType.SETTLEMENT
    assert (
        detect_record_type(
            "warehouse_stock.csv",
            ["warehouse_id", "available_stock"],
        )
        is OzonRecordType.INVENTORY
    )
    assert (
        detect_record_type(
            "Отчет по начислениям.xlsx", ["ID начисления", "Группа услуг", "Тип начисления"]
        )
        is OzonRecordType.ACCRUAL
    )


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


def test_normalization_rejects_non_finite_numbers_and_non_ascii_currency():
    _, order_errors = normalize_record(
        OzonRecordType.ORDER,
        {
            "external_id": "order-unsafe",
            "sku": "sku-1",
            "quantity": "Infinity",
            "gross_revenue": "NaN",
            "currency": "РУБ",
            "effective_at": "2026-07-16T10:00:00+03:00",
        },
    )

    assert "quantity: must be a positive integer" in order_errors
    assert "gross_revenue: invalid decimal" in order_errors
    assert "currency: must be a three-letter code" in order_errors


def test_inventory_contract_normalizes_exact_cell_and_zero_quantities():
    normalized, errors = normalize_record(
        OzonRecordType.INVENTORY,
        {
            "external_id": "snapshot-1",
            "sku": "SKU-1",
            "warehouse_ref": "warehouse-cn-1",
            "cluster_ref": "cn-east",
            "fulfillment_mode": "real_fbs",
            "available_quantity": "3",
            "reserved_quantity": "0",
            "in_transit_quantity": "0",
            "damaged_quantity": "0",
            "quarantine_quantity": "0",
            "effective_at": "2026-07-16T10:00:00+03:00",
        },
    )

    assert errors == []
    assert normalized["fulfillment_mode"] == "realFBS"
    assert natural_key(
        OzonRecordType.INVENTORY,
        normalized,
    ) == "SKU-1:warehouse-cn-1:realFBS:cn-east"


def test_inventory_contract_rejects_negative_quantity_and_ru_fbs_mode():
    _, errors = normalize_record(
        OzonRecordType.INVENTORY,
        {
            "external_id": "snapshot-1",
            "sku": "SKU-1",
            "warehouse_ref": "warehouse-cn-1",
            "fulfillment_mode": "FBS",
            "available_quantity": "-1",
            "reserved_quantity": "0",
            "effective_at": "2026-07-16T10:00:00+03:00",
        },
    )

    assert "available_quantity: must be a non-negative integer" in errors
    assert "fulfillment_mode: must be FBP or realFBS" in errors


def test_return_contract_preserves_explicit_order_link_when_present():
    normalized, errors = normalize_record(
        OzonRecordType.RETURN,
        {
            "external_id": "return-1",
            "order_external_id": "order-1",
            "sku": "SKU-1",
            "quantity": "1",
            "effective_at": "2026-07-16T10:00:00+03:00",
        },
    )

    assert errors == []
    assert normalized["order_external_id"] == "order-1"
