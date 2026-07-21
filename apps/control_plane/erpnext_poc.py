from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

CONTRACT_VERSION = 1
POC_MODE = "poc_dry_run"
ALLOWED_DOCTYPES = frozenset(
    {
        "Item",
        "Purchase Order",
        "Purchase Receipt",
        "Landed Cost Voucher",
        "Sales Invoice",
        "Journal Entry",
        "Payment Entry",
    }
)
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")


def _decimal_text(value: str, field: str, *, positive: bool = False, nonnegative: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a decimal string")
    try:
        parsed = Decimal(value.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a finite decimal string") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal string")
    if positive and parsed <= 0:
        raise ValueError(f"{field} must be positive")
    if nonnegative and parsed < 0:
        raise ValueError(f"{field} must be nonnegative")
    return format(parsed, "f")


def _currency(value: str, field: str = "currency") -> str:
    if not isinstance(value, str) or len(value) != 3 or not value.isascii() or not value.isalpha():
        raise ValueError(f"{field} must be a three-letter ASCII currency")
    normalized = value.upper()
    if value != normalized:
        raise ValueError(f"{field} must be uppercase")
    return normalized


def _ref(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_REF.fullmatch(value.strip()):
        raise ValueError(f"{field} must be a stable safe reference")
    return value.strip()


def _date(value: str, field: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO date") from exc


def _timestamp(value: str, field: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.isoformat()


def _reject_floats(value: Any, path: str = "payload") -> None:
    if isinstance(value, float):
        raise ValueError(f"{path} cannot contain floating-point values")
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_floats(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_floats(child, f"{path}[{index}]")


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class MoneyValue:
    amount: str
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _decimal_text(self.amount, "amount"))
        object.__setattr__(self, "currency", _currency(self.currency))

    @property
    def decimal(self) -> Decimal:
        return Decimal(self.amount)


@dataclass(frozen=True, slots=True)
class FxContext:
    transaction_currency: str
    company_currency: str
    rate: str
    effective_at: str
    evidence_id: str

    def __post_init__(self) -> None:
        transaction = _currency(self.transaction_currency, "transaction_currency")
        company = _currency(self.company_currency, "company_currency")
        if transaction == company:
            raise ValueError("FX context is only valid for different currencies")
        object.__setattr__(self, "transaction_currency", transaction)
        object.__setattr__(self, "company_currency", company)
        object.__setattr__(self, "rate", _decimal_text(self.rate, "rate", positive=True))
        object.__setattr__(self, "effective_at", _timestamp(self.effective_at, "effective_at"))
        object.__setattr__(self, "evidence_id", _ref(self.evidence_id, "evidence_id"))


@dataclass(frozen=True, slots=True)
class ErpNextProjectionEnvelope:
    contract_version: int
    mode: str
    doctype: str
    external_id: str
    idempotency_key: str
    payload_sha256: str
    source_type: str
    source_id: str
    source_version: int
    evidence_ids: tuple[str, ...]
    current_owner: str
    candidate_owner: str
    automatic_submit: bool
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence_ids"] = list(self.evidence_ids)
        return result


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    status: str
    source_amount: str
    target_amount: str
    difference: str
    tolerance: str
    currency: str
    automatic_adjustment: bool = False


class ErpNextPocProjector:
    """Contract-only ERPNext projector. It intentionally has no remote write method."""

    def project_item(
        self,
        *,
        product_id: str,
        version: int,
        sku: str,
        name: str,
        stock_uom: str,
        evidence_ids: Iterable[str],
    ) -> ErpNextProjectionEnvelope:
        sku = _ref(sku, "sku")
        if not name.strip() or not stock_uom.strip():
            raise ValueError("Item name and stock_uom are required")
        return self._envelope(
            doctype="Item",
            source_type="canonical_product",
            source_id=product_id,
            source_version=version,
            evidence_ids=evidence_ids,
            payload={
                "docstatus": 0,
                "item_code": sku,
                "item_name": name.strip(),
                "stock_uom": stock_uom.strip(),
                "is_stock_item": 1,
                "custom_kjds_product_id": product_id,
            },
        )

    def project_purchase_order(
        self,
        *,
        order_id: str,
        version: int,
        supplier_ref: str,
        transaction_date: str,
        schedule_date: str,
        items: list[dict[str, str]],
        company_currency: str,
        evidence_ids: Iterable[str],
        fx: FxContext | None = None,
    ) -> ErpNextProjectionEnvelope:
        supplier_ref = _ref(supplier_ref, "supplier_ref")
        company_currency = _currency(company_currency, "company_currency")
        projection_evidence = list(evidence_ids)
        if not items:
            raise ValueError("Purchase Order requires at least one item")
        projected_items: list[dict[str, str]] = []
        currencies: set[str] = set()
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(f"items[{index}] must be an object")
            item_code = _ref(item.get("item_code", ""), f"items[{index}].item_code")
            quantity = _decimal_text(item.get("quantity", ""), f"items[{index}].quantity", positive=True)
            rate = MoneyValue(item.get("unit_rate", ""), item.get("currency", ""))
            currencies.add(rate.currency)
            projected_items.append({"item_code": item_code, "qty": quantity, "rate": rate.amount})
        if len(currencies) != 1:
            raise ValueError("Purchase Order items must use one transaction currency")
        transaction_currency = next(iter(currencies))
        conversion_rate = "1"
        fx_payload: dict[str, str] | None = None
        if transaction_currency != company_currency:
            if fx is None:
                raise ValueError("Cross-currency Purchase Order requires FX evidence")
            if fx.transaction_currency != transaction_currency or fx.company_currency != company_currency:
                raise ValueError("FX context currencies do not match Purchase Order")
            conversion_rate = fx.rate
            fx_payload = asdict(fx)
            projection_evidence.append(fx.evidence_id)
        elif fx is not None:
            raise ValueError("Same-currency Purchase Order must not include FX context")
        payload: dict[str, Any] = {
            "docstatus": 0,
            "supplier": supplier_ref,
            "transaction_date": _date(transaction_date, "transaction_date"),
            "schedule_date": _date(schedule_date, "schedule_date"),
            "currency": transaction_currency,
            "conversion_rate": conversion_rate,
            "items": projected_items,
            "custom_kjds_order_id": order_id,
        }
        if fx_payload is not None:
            payload["custom_kjds_fx_context"] = fx_payload
        return self._envelope(
            doctype="Purchase Order",
            source_type="sample_purchase_order",
            source_id=order_id,
            source_version=version,
            evidence_ids=projection_evidence,
            payload=payload,
        )

    def project_journal_candidate(
        self,
        *,
        source_id: str,
        version: int,
        posting_date: str,
        currency: str,
        lines: list[dict[str, str]],
        evidence_ids: Iterable[str],
    ) -> ErpNextProjectionEnvelope:
        currency = _currency(currency)
        if len(lines) < 2:
            raise ValueError("Journal candidate requires at least two lines")
        debit = Decimal("0")
        credit = Decimal("0")
        projected_lines: list[dict[str, str]] = []
        for index, line in enumerate(lines):
            if not isinstance(line, dict):
                raise ValueError(f"lines[{index}] must be an object")
            account = _ref(line.get("account", ""), f"lines[{index}].account")
            line_debit = _decimal_text(line.get("debit", "0"), f"lines[{index}].debit", nonnegative=True)
            line_credit = _decimal_text(line.get("credit", "0"), f"lines[{index}].credit", nonnegative=True)
            if (Decimal(line_debit) == 0) == (Decimal(line_credit) == 0):
                raise ValueError(f"lines[{index}] must contain exactly one positive debit or credit")
            debit += Decimal(line_debit)
            credit += Decimal(line_credit)
            projected_lines.append(
                {"account": account, "debit_in_account_currency": line_debit, "credit_in_account_currency": line_credit}
            )
        if debit != credit:
            raise ValueError("Journal candidate must balance exactly")
        return self._envelope(
            doctype="Journal Entry",
            source_type="finance_reconciliation",
            source_id=source_id,
            source_version=version,
            evidence_ids=evidence_ids,
            payload={
                "docstatus": 0,
                "posting_date": _date(posting_date, "posting_date"),
                "accounts": projected_lines,
                "custom_kjds_currency": currency,
                "custom_kjds_source_id": source_id,
            },
        )

    def _envelope(
        self,
        *,
        doctype: str,
        source_type: str,
        source_id: str,
        source_version: int,
        evidence_ids: Iterable[str],
        payload: dict[str, Any],
    ) -> ErpNextProjectionEnvelope:
        if doctype not in ALLOWED_DOCTYPES:
            raise ValueError(f"Unsupported ERPNext DocType: {doctype}")
        source_type = _ref(source_type, "source_type")
        source_id = _ref(source_id, "source_id")
        if isinstance(source_version, bool) or not isinstance(source_version, int) or source_version < 1:
            raise ValueError("source_version must be a positive integer")
        normalized_evidence = tuple(dict.fromkeys(_ref(value, "evidence_id") for value in evidence_ids))
        if not normalized_evidence:
            raise ValueError("ERPNext projection requires evidence")
        if payload.get("docstatus") != 0:
            raise ValueError("ERPNext PoC projections must remain draft documents")
        _reject_floats(payload)
        payload_json = _canonical_json(payload)
        payload_sha256 = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        doctype_key = doctype.lower().replace(" ", "_")
        idempotency_key = f"kjds:erpnext:v{CONTRACT_VERSION}:{doctype_key}:{source_type}:{source_id}:v{source_version}"
        external_seed = f"{source_type}:{source_id}"
        external_id = f"KJDS-{source_type.upper()}-{hashlib.sha256(external_seed.encode()).hexdigest()[:24]}"
        return ErpNextProjectionEnvelope(
            contract_version=CONTRACT_VERSION,
            mode=POC_MODE,
            doctype=doctype,
            external_id=external_id,
            idempotency_key=idempotency_key,
            payload_sha256=payload_sha256,
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
            evidence_ids=normalized_evidence,
            current_owner="kjds",
            candidate_owner="erpnext",
            automatic_submit=False,
            payload=payload,
        )


def validate_projection_batch(envelopes: Iterable[ErpNextProjectionEnvelope]) -> list[ErpNextProjectionEnvelope]:
    result = list(envelopes)
    seen: dict[str, str] = {}
    for envelope in result:
        if envelope.mode != POC_MODE or envelope.automatic_submit:
            raise ValueError("ERPNext contract stage only permits non-submitting dry-run projections")
        previous_hash = seen.get(envelope.idempotency_key)
        if previous_hash is not None and previous_hash != envelope.payload_sha256:
            raise ValueError("Same ERPNext idempotency key has conflicting payloads")
        seen[envelope.idempotency_key] = envelope.payload_sha256
    return result


def reconcile_money(*, source: MoneyValue, target: MoneyValue, tolerance: str = "0") -> ReconciliationResult:
    tolerance_text = _decimal_text(tolerance, "tolerance", nonnegative=True)
    if source.currency != target.currency:
        return ReconciliationResult(
            status="blocked",
            source_amount=source.amount,
            target_amount=target.amount,
            difference="0",
            tolerance=tolerance_text,
            currency=source.currency,
        )
    difference = target.decimal - source.decimal
    status = "matched" if abs(difference) <= Decimal(tolerance_text) else "difference"
    return ReconciliationResult(
        status=status,
        source_amount=source.amount,
        target_amount=target.amount,
        difference=format(difference, "f"),
        tolerance=tolerance_text,
        currency=source.currency,
    )


def verify_frappe_webhook(*, body: bytes, signature: str, secret: str) -> bool:
    if not isinstance(body, bytes):
        raise ValueError("Webhook body must be raw bytes")
    if not secret:
        raise ValueError("Webhook secret is required")
    signature = signature.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
