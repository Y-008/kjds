import pytest

from apps.control_plane.ozon_live_contracts import (
    FINANCE_TRANSACTION_CONTRACT_VERSION,
    FINANCE_TRANSACTION_PATH,
    FORMAL_FACT_CATALOG_VERSION,
    LIVE_CONNECTOR_CATALOG_VERSION,
    live_connector_contract_catalog,
    validate_finance_transactions_payload,
)


def test_live_connector_catalog_separates_live_contracts_from_formal_facts():
    catalog = live_connector_contract_catalog()
    assert catalog == [
        {
            "catalog_version": LIVE_CONNECTOR_CATALOG_VERSION,
            "contract_domain": "live_connector",
            "contract_version": FINANCE_TRANSACTION_CONTRACT_VERSION,
            "operation": "ozon.finance.read",
            "official_origin": "https://api-seller.ozon.ru",
            "method": "POST",
            "path": FINANCE_TRANSACTION_PATH,
            "description": (
                "Read-only Ozon Seller finance transaction envelope. "
                "Operation fields remain observed candidates until admitted from "
                "a current official response."
            ),
            "related_formal_fact_version": FORMAL_FACT_CATALOG_VERSION,
            "required_operation_fields": [],
            "observed_operation_fields": [
                "operation_id",
                "amount",
                "operation_type",
                "operation_date",
                "posting",
                "items",
                "services",
            ],
            "operation_field_admission": "unverified_observation_only",
        }
    ]


def test_validate_finance_transactions_payload_accepts_minimal_semantic_contract():
    contract = validate_finance_transactions_payload(
        {
            "result": {
                "operations": [
                    {
                        "operation_id": "op-1",
                        "amount": "42.50",
                        "posting": {
                            "posting_number": "posting-1",
                            "items": [{"sku": "sku-1"}],
                        },
                    }
                ],
                "page_count": 2,
            }
        }
    )
    assert contract == {"operation_count": 1, "page_count": 2}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"result": {"operations": ["not-an-object"]}}, "objects"),
        ({"result": {"operations": [], "page_count": -1}}, "page_count"),
    ],
)
def test_validate_finance_transactions_payload_fails_closed_on_envelope_drift(payload, message):
    with pytest.raises(ValueError, match=message):
        validate_finance_transactions_payload(payload)


def test_unadmitted_operation_fields_are_preserved_without_semantic_claims():
    contract = validate_finance_transactions_payload(
        {
            "result": {
                "operations": [
                    {"amount": "NaN", "posting": "provider-shape-not-yet-admitted"}
                ]
            }
        }
    )
    assert contract == {"operation_count": 1, "page_count": None}
