from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any

from .evidence import parse_timestamp

CONTRACT_VERSION = "ozon-v1"


class OzonRecordType(StrEnum):
    ORDER = "ozon_order"
    FEE = "ozon_fee"
    ACCRUAL = "ozon_accrual"
    RETURN = "ozon_return"
    SETTLEMENT = "ozon_settlement"


@dataclass(frozen=True, slots=True)
class RecordContract:
    record_type: OzonRecordType
    required_fields: frozenset[str]
    optional_fields: frozenset[str]
    description: str


CONTRACTS: dict[OzonRecordType, RecordContract] = {
    OzonRecordType.ORDER: RecordContract(
        OzonRecordType.ORDER,
        frozenset({"external_id", "sku", "quantity", "currency", "gross_revenue", "effective_at"}),
        frozenset({"status"}),
        "Ozon order or shipment fact",
    ),
    OzonRecordType.FEE: RecordContract(
        OzonRecordType.FEE,
        frozenset({"external_id", "fee_type", "amount", "currency", "effective_at"}),
        frozenset({"sku", "status"}),
        "Ozon fee or service charge fact",
    ),
    OzonRecordType.ACCRUAL: RecordContract(
        OzonRecordType.ACCRUAL,
        frozenset(
            {"external_id", "accrual_group", "accrual_type", "amount", "currency", "effective_at"}
        ),
        frozenset({"sku"}),
        "Ozon official accrual-ledger row; accounting classification remains pending",
    ),
    OzonRecordType.RETURN: RecordContract(
        OzonRecordType.RETURN,
        frozenset({"external_id", "sku", "quantity", "effective_at"}),
        frozenset({"amount", "currency", "return_reason", "status"}),
        "Ozon return, cancellation, or non-collection fact",
    ),
    OzonRecordType.SETTLEMENT: RecordContract(
        OzonRecordType.SETTLEMENT,
        frozenset({"external_id", "amount", "currency", "effective_at"}),
        frozenset({"status"}),
        "Ozon settlement statement fact",
    ),
}


def detect_record_type(filename: str, headers: list[str]) -> OzonRecordType:
    signature = " ".join([Path(filename).stem.lower(), *(header.lower() for header in headers)])
    if "начислен" in signature and "группа услуг" in signature and "тип начисления" in signature:
        return OzonRecordType.ACCRUAL
    if any(token in signature for token in ("settlement", "payout", "payment", "выплат", "реализац")):
        return OzonRecordType.SETTLEMENT
    if any(token in signature for token in ("return", "refund", "возврат", "невыкуп")):
        return OzonRecordType.RETURN
    if any(token in signature for token in ("fee", "charge", "commission", "transaction", "комисс", "начисл")):
        return OzonRecordType.FEE
    return OzonRecordType.ORDER


def normalize_record(record_type: OzonRecordType, values: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    contract = CONTRACTS[record_type]
    normalized = {key: str("" if value is None else value).strip() for key, value in values.items()}
    errors = [f"missing {field}" for field in sorted(contract.required_fields) if not normalized.get(field)]

    if normalized.get("quantity"):
        try:
            quantity = Decimal(_numeric_text(normalized["quantity"]))
            if not quantity.is_finite() or quantity != quantity.to_integral_value() or quantity <= 0:
                raise ValueError
            normalized["quantity"] = str(int(quantity))
        except (InvalidOperation, OverflowError, ValueError):
            errors.append("quantity: must be a positive integer")

    for field in ("gross_revenue", "amount"):
        if normalized.get(field):
            try:
                amount = Decimal(_numeric_text(normalized[field]))
                if not amount.is_finite():
                    raise InvalidOperation
                normalized[field] = str(amount)
            except InvalidOperation:
                errors.append(f"{field}: invalid decimal")

    if normalized.get("currency"):
        currency = normalized["currency"].upper()
        if len(currency) != 3 or not currency.isalpha() or not currency.isascii():
            errors.append("currency: must be a three-letter code")
        normalized["currency"] = currency

    if normalized.get("effective_at"):
        try:
            normalized["effective_at"] = parse_timestamp(normalized["effective_at"], "effective_at").isoformat()
        except ValueError as exc:
            errors.append(str(exc))

    return normalized, sorted(set(errors))


def natural_key(record_type: OzonRecordType, payload: dict[str, Any]) -> str:
    external_id = str(payload["external_id"])
    if record_type is OzonRecordType.FEE:
        return f"{external_id}:{payload['fee_type']}"
    return external_id


def contract_catalog() -> list[dict[str, Any]]:
    return [
        {
            "version": CONTRACT_VERSION,
            "record_type": contract.record_type.value,
            "required_fields": sorted(contract.required_fields),
            "optional_fields": sorted(contract.optional_fields),
            "description": contract.description,
        }
        for contract in CONTRACTS.values()
    ]


def _numeric_text(value: str) -> str:
    return value.replace(" ", "").replace(",", ".")
