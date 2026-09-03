from __future__ import annotations

from dataclasses import dataclass
from typing import Any

LIVE_CONNECTOR_CATALOG_VERSION = "ozon-live-connector-v1"
FORMAL_FACT_CATALOG_VERSION = "ozon-v1"
FINANCE_TRANSACTION_CONTRACT_VERSION = "ozon-finance-transactions-v1"
FINANCE_TRANSACTION_PATH = "/v3/finance/transaction/list"
OFFICIAL_OZON_ORIGIN = "https://api-seller.ozon.ru"


@dataclass(frozen=True, slots=True)
class LiveConnectorContract:
    contract_version: str
    operation: str
    method: str
    path: str
    description: str
    related_formal_fact_version: str
    required_operation_fields: tuple[str, ...]
    observed_operation_fields: tuple[str, ...]


LIVE_CONNECTOR_CONTRACTS: tuple[LiveConnectorContract, ...] = (
    LiveConnectorContract(
        contract_version=FINANCE_TRANSACTION_CONTRACT_VERSION,
        operation="ozon.finance.read",
        method="POST",
        path=FINANCE_TRANSACTION_PATH,
        description=(
            "Read-only Ozon Seller finance transaction envelope. "
            "Operation fields remain observed candidates until admitted from "
            "a current official response."
        ),
        related_formal_fact_version=FORMAL_FACT_CATALOG_VERSION,
        required_operation_fields=(),
        observed_operation_fields=(
            "operation_id",
            "amount",
            "operation_type",
            "operation_date",
            "posting",
            "items",
            "services",
        ),
    ),
)


def live_connector_contract_catalog() -> list[dict[str, Any]]:
    return [
        {
            "catalog_version": LIVE_CONNECTOR_CATALOG_VERSION,
            "contract_domain": "live_connector",
            "contract_version": contract.contract_version,
            "operation": contract.operation,
            "official_origin": OFFICIAL_OZON_ORIGIN,
            "method": contract.method,
            "path": contract.path,
            "description": contract.description,
            "related_formal_fact_version": contract.related_formal_fact_version,
            "required_operation_fields": list(contract.required_operation_fields),
            "observed_operation_fields": list(contract.observed_operation_fields),
            "operation_field_admission": "unverified_observation_only",
        }
        for contract in LIVE_CONNECTOR_CONTRACTS
    ]


def validate_finance_transactions_payload(response: dict[str, Any]) -> dict[str, Any]:
    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError("Ozon finance response is missing result")
    operations = result.get("operations")
    if not isinstance(operations, list):
        raise ValueError("Ozon finance response is missing result.operations")
    page_count = result.get("page_count")
    if page_count is not None and (
        isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 0
    ):
        raise ValueError("Ozon finance response contains an invalid page_count")
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("Ozon finance operations must contain objects")
    return {
        "operation_count": len(operations),
        "page_count": page_count,
    }
