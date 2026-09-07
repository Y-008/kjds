"""Read-only semantic quality and shadow preflight for Ozon price/stock data.

The Ozon catalog reader already stores a product response as an immutable
catalog snapshot.  This module adds the next, deliberately side-effect-free
boundary: it validates the price and warehouse stock semantics and can build a
deterministic *shadow* change packet.  A shadow packet is useful to the
control-plane planner, but it is not an execution command.  It never opens a
socket, creates an Approval or Permit, writes a Fact, or calls an external
adapter.

The implementation keeps quality separate from numeric values.  In
particular, a missing stock value is represented by ``NO_DATA`` and is never
silently converted to ``0``; an unknown external outcome is represented by
``UNKNOWN_OUTCOME`` and cannot become an executable proposal.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from .data_fabric_contracts import QualityStateValue
from .economic_guard_service import EconomicGuardResult
from .experiment_contamination_checker import (
    check_experiment_contamination,
    evaluate_experiment_fact_admission,
)

FreshnessState = Literal["fresh", "stale", "unknown"]
ShadowStatus = Literal["shadow_ready", "blocked"]

DEFAULT_MAX_AGE = timedelta(minutes=15)
_MISSING = object()
_QUALITY_ALIASES = {
    "READY": "VALID",
    "FRESH": "VALID",
    "UNKNOWN": "UNKNOWN_OUTCOME",
    "UNKNOWN_RESULT": "UNKNOWN_OUTCOME",
}
_QUALITY_VALUES = {
    "NO_DATA",
    "PARTIAL",
    "STALE",
    "BLOCKED",
    "UNKNOWN_OUTCOME",
    "VALID",
}
_PRICE_FIELDS = ("price", "old_price", "min_price", "marketing_price", "marketing_seller_price")
_STOCK_VALUE_ALIASES = ("present", "available", "available_quantity", "stock", "quantity")
_WAREHOUSE_ALIASES = ("warehouse_ref", "warehouse_id", "warehouse")
_PATCH_META_KEYS = {
    "idempotency_key",
    "offer_id",
    "sku",
    "marketplace_sku",
}
_PATCH_ALLOWED_KEYS = {
    "price",
    "price_rub",
    "currency_code",
    "stock",
    "available_stock",
    "warehouse_ref",
    "warehouse_id",
    "stocks",
    *_PATCH_META_KEYS,
}


def _json_safe(value: Any) -> Any:
    """Convert values to the canonical JSON representation used for hashes."""

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite Decimal cannot be hashed")
        return _decimal_text(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("naive datetime cannot be hashed")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_json_safe(item) for item in value), key=repr)
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError("non-finite float cannot be hashed")
        return value
    if hasattr(value, "model_dump"):
        return _json_safe(value.model_dump(mode="python"))
    raise TypeError(f"unsupported hash value: {type(value).__name__}")


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_safe(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _decimal_text(value: Decimal) -> str:
    """Return a stable decimal spelling (without insignificant zeroes)."""

    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _aware(value: Any, field: str) -> datetime:
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _optional_aware(value: Any, field: str) -> datetime | None:
    return None if value is None else _aware(value, field)


def _required_text(value: Any, field: str, *, max_length: int = 240) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    if len(text) > max_length or any(char in text for char in ("\r", "\n", "\0")):
        raise ValueError(f"{field} is invalid")
    return text


def _optional_text(value: Any, *, max_length: int = 240) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_length or any(char in text for char in ("\r", "\n", "\0")):
        return None
    return text


def _hash_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        return None
    return text


def _quality_state(value: Any) -> QualityStateValue | None:
    if value is None:
        return None
    normalized = str(value).strip().upper().replace("-", "_").replace(" ", "_")
    normalized = _QUALITY_ALIASES.get(normalized, normalized)
    return normalized if normalized in _QUALITY_VALUES else None  # type: ignore[return-value]


def _parse_decimal(value: Any, *, field: str, positive: bool) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is not a decimal")
    candidate = value
    if isinstance(candidate, Mapping):
        # Ozon has returned both scalar price fields and small objects with a
        # ``value``/``amount`` member over time.  Accept one unambiguous scalar
        # while rejecting conflicting aliases.
        present = [
            candidate[name]
            for name in ("value", "amount", "price", "display_value")
            if name in candidate and candidate[name] is not None
        ]
        if not present:
            raise ValueError(f"{field} is ambiguous")
        if any(str(item).strip() != str(present[0]).strip() for item in present[1:]):
            raise ValueError(f"{field} is ambiguous")
        candidate = present[0]
    try:
        number = candidate if isinstance(candidate, Decimal) else Decimal(str(candidate).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not a decimal") from exc
    if not number.is_finite() or (number <= 0 if positive else number < 0):
        qualifier = "positive and finite" if positive else "non-negative and finite"
        raise ValueError(f"{field} must be {qualifier}")
    return number


def _parse_integer(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is not an integer")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not an integer") from exc
    if not number.is_finite() or number != number.to_integral_value() or number < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return int(number)


def _alias_value(
    mapping: Mapping[str, Any],
    aliases: Sequence[str],
    *,
    field: str,
) -> Any:
    values = [mapping[name] for name in aliases if name in mapping and mapping[name] is not None]
    if not values:
        return _MISSING
    first = values[0]
    if any(str(item).strip() != str(first).strip() for item in values[1:]):
        raise ValueError(f"{field} is ambiguous")
    return first


def _normalize_max_age(value: timedelta | int | float) -> timedelta:
    if isinstance(value, timedelta):
        result = value
    elif isinstance(value, bool):
        raise ValueError("max_age must be positive")
    else:
        try:
            result = timedelta(seconds=float(value))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("max_age must be positive") from exc
    if result <= timedelta(0):
        raise ValueError("max_age must be positive")
    return result


@dataclass(frozen=True, slots=True)
class NormalizedStock:
    """One exact warehouse stock cell after semantic normalization."""

    warehouse_ref: str
    present: int
    reserved: int | None = None

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        del mode
        return {
            "warehouse_ref": self.warehouse_ref,
            "present": self.present,
            "reserved": self.reserved,
        }


@dataclass(frozen=True, slots=True)
class PriceStockQuality:
    """Independent quality state for seller price and warehouse stock."""

    price_state: QualityStateValue
    stock_state: QualityStateValue
    quality_state: QualityStateValue
    freshness: FreshnessState
    observed_at: datetime | None
    fresh_until: datetime | None
    price: Decimal | None
    currency_code: str | None
    stocks: tuple[NormalizedStock, ...]
    stock_total: int | None
    source_evidence_id: str | None
    source_evidence_sha256: str | None
    item_hash: str | None
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    snapshot_sha256: str

    @property
    def overall_state(self) -> QualityStateValue:
        return self.quality_state

    @property
    def quality_status(self) -> QualityStateValue:
        return self.quality_state

    @property
    def price_quality(self) -> QualityStateValue:
        """Alias matching transport field names used by data products."""

        return self.price_state

    @property
    def stock_quality(self) -> QualityStateValue:
        """Alias matching transport field names used by data products."""

        return self.stock_state

    @property
    def is_valid(self) -> bool:
        return self.quality_state == "VALID"

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        del mode
        return {
            "price_state": self.price_state,
            "stock_state": self.stock_state,
            "quality_state": self.quality_state,
            "freshness": self.freshness,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "fresh_until": self.fresh_until.isoformat() if self.fresh_until else None,
            "price": _decimal_text(self.price) if self.price is not None else None,
            "currency_code": self.currency_code,
            "stocks": [stock.model_dump() for stock in self.stocks],
            "stock_total": self.stock_total,
            "source_evidence_id": self.source_evidence_id,
            "source_evidence_sha256": self.source_evidence_sha256,
            "item_hash": self.item_hash,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "snapshot_sha256": self.snapshot_sha256,
        }


@dataclass(frozen=True, slots=True)
class PriceStockShadow:
    """A deterministic, non-executable price/stock change projection."""

    status: ShadowStatus
    scope: dict[str, str | None]
    target: dict[str, str]
    patch: dict[str, Any]
    rollback_patch: dict[str, Any] | None
    before_state_hash: str | None
    quality: PriceStockQuality
    economic_guard: dict[str, Any]
    experiment: dict[str, Any]
    lineage_refs: tuple[dict[str, Any], ...]
    blockers: tuple[str, ...]
    idempotency_key: str
    rollback_ref: str | None
    fingerprint: str
    external_write_allowed: bool = False
    permit_issued: bool = False
    approval_created: bool = False
    readback_required: bool = True
    readback_observed: bool = False
    rollback_required: bool = True
    execution_eligible: bool = False

    @property
    def shadow_ready(self) -> bool:
        return self.status == "shadow_ready"

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        del mode
        return {
            "status": self.status,
            "scope": dict(self.scope),
            "target": dict(self.target),
            "patch": _json_safe(self.patch),
            "rollback_patch": _json_safe(self.rollback_patch) if self.rollback_patch is not None else None,
            "before_state_hash": self.before_state_hash,
            "quality": self.quality.model_dump(),
            "economic_guard": _json_safe(self.economic_guard),
            "experiment": _json_safe(self.experiment),
            "lineage_refs": _json_safe(self.lineage_refs),
            "blockers": list(self.blockers),
            "idempotency_key": self.idempotency_key,
            "rollback_ref": self.rollback_ref,
            "fingerprint": self.fingerprint,
            "external_write_allowed": self.external_write_allowed,
            "permit_issued": self.permit_issued,
            "approval_created": self.approval_created,
            "readback_required": self.readback_required,
            "readback_observed": self.readback_observed,
            "rollback_required": self.rollback_required,
            "execution_eligible": self.execution_eligible,
        }


def _empty_quality(*, blockers: Sequence[str], warnings: Sequence[str] = ()) -> PriceStockQuality:
    unique_blockers = tuple(sorted(set(blockers)))
    unique_warnings = tuple(sorted(set(warnings)))
    canonical = {
        "contract_id": "kjds-ozon-price-stock-quality-v1",
        "price_state": "BLOCKED",
        "stock_state": "BLOCKED",
        "quality_state": "BLOCKED",
        "freshness": "unknown",
        "blockers": list(unique_blockers),
        "warnings": list(unique_warnings),
    }
    return PriceStockQuality(
        price_state="BLOCKED",
        stock_state="BLOCKED",
        quality_state="BLOCKED",
        freshness="unknown",
        observed_at=None,
        fresh_until=None,
        price=None,
        currency_code=None,
        stocks=(),
        stock_total=None,
        source_evidence_id=None,
        source_evidence_sha256=None,
        item_hash=None,
        blockers=unique_blockers,
        warnings=unique_warnings,
        snapshot_sha256=_hash(canonical),
    )


def _combine_quality(
    price_state: QualityStateValue,
    stock_state: QualityStateValue,
    *,
    explicit_state: QualityStateValue | None,
    shared_blocked: bool,
) -> QualityStateValue:
    if shared_blocked or "BLOCKED" in {price_state, stock_state}:
        return "BLOCKED"
    if "UNKNOWN_OUTCOME" in {price_state, stock_state}:
        return "UNKNOWN_OUTCOME"
    if "STALE" in {price_state, stock_state}:
        return "STALE"
    if explicit_state == "PARTIAL" or "PARTIAL" in {price_state, stock_state}:
        return "PARTIAL"
    if price_state == "NO_DATA" and stock_state == "NO_DATA":
        return "NO_DATA"
    if "NO_DATA" in {price_state, stock_state}:
        return "PARTIAL"
    return "VALID"


def validate_catalog_price_stock(
    item: Mapping[str, Any] | Any,
    *,
    observed_at: datetime | str | None = None,
    now: datetime | str | None = None,
    max_age: timedelta | int | float = DEFAULT_MAX_AGE,
) -> PriceStockQuality:
    """Validate one catalog item without performing any I/O.

    ``item`` is normally the output of
    :func:`marketplace_catalog.parse_ozon_product_bundle`.  Missing values are
    represented as quality states and blocker codes; callers do not need to
    catch a parser exception to decide whether a shadow action is safe.
    """

    if not isinstance(item, Mapping):
        return _empty_quality(blockers=("catalog_item_not_object",))
    try:
        age_limit = _normalize_max_age(max_age)
    except ValueError:
        raise

    blockers: list[str] = []
    warnings: list[str] = []
    source_evidence_id = _optional_text(
        item.get("source_evidence_id") or item.get("evidence_id"),
        max_length=300,
    )
    source_evidence_sha256 = _hash_or_none(item.get("source_evidence_sha256") or item.get("evidence_sha256"))
    raw_evidence_hash = item.get("source_evidence_sha256") or item.get("evidence_sha256")
    if not source_evidence_id:
        blockers.append("source_evidence_missing")
    if raw_evidence_hash is not None and source_evidence_sha256 is None:
        blockers.append("source_evidence_hash_invalid")
    item_hash = _hash_or_none(item.get("item_hash") or item.get("state_hash"))
    raw_item_hash = item.get("item_hash") or item.get("state_hash")
    if raw_item_hash is not None and item_hash is None:
        blockers.append("item_hash_invalid")

    observed_value = observed_at if observed_at is not None else item.get("observed_at")
    observed: datetime | None = None
    if observed_value is None:
        blockers.append("observed_at_missing")
    else:
        try:
            observed = _aware(observed_value, "observed_at")
        except ValueError:
            blockers.append("observed_at_invalid")

    current_time = _aware(now, "now") if now is not None else datetime.now(UTC)
    fresh_until: datetime | None = None
    if item.get("fresh_until") is not None:
        try:
            fresh_until = _aware(item["fresh_until"], "fresh_until")
        except ValueError:
            blockers.append("fresh_until_invalid")

    freshness: FreshnessState = "unknown"
    if observed is not None:
        if observed > current_time:
            blockers.append("observed_at_in_future")
        elif current_time - observed > age_limit:
            freshness = "stale"
        else:
            freshness = "fresh"
        if fresh_until is not None:
            if fresh_until < observed:
                blockers.append("fresh_until_before_observed_at")
            elif current_time > fresh_until:
                freshness = "stale"

    explicit_state = _quality_state(item.get("quality_state") or item.get("quality_status"))
    if (item.get("quality_state") or item.get("quality_status")) is not None and explicit_state is None:
        blockers.append("quality_state_invalid")

    prices = item.get("prices")
    price: Decimal | None = None
    currency_code = _optional_text(
        item.get("currency_code") or item.get("currency"),
        max_length=12,
    )
    price_state: QualityStateValue = "NO_DATA"
    if prices is None:
        blockers.append("price_data_missing")
    elif not isinstance(prices, Mapping):
        price_state = "BLOCKED"
        blockers.append("price_data_not_object")
    else:
        raw_price = _alias_value(prices, ("price",), field="price")
        if raw_price is _MISSING:
            price_state = "NO_DATA"
            blockers.append("price_missing")
        else:
            try:
                price = _parse_decimal(raw_price, field="price", positive=True)
                price_state = "VALID"
            except ValueError as exc:
                price_state = "BLOCKED"
                blockers.append(f"price_invalid:{str(exc).replace(' ', '_')}")
        nested_currency = None
        if raw_price is not _MISSING and isinstance(raw_price, Mapping):
            nested_currency = raw_price.get("currency_code") or raw_price.get("currency")
        if currency_code is None and nested_currency is not None:
            currency_code = _optional_text(nested_currency, max_length=12)
        if currency_code is None:
            if price is not None:
                price_state = "BLOCKED"
            blockers.append("price_currency_missing")
        else:
            currency_code = currency_code.upper()
            if len(currency_code) != 3 or not currency_code.isascii() or not currency_code.isalpha():
                price_state = "BLOCKED"
                blockers.append("price_currency_invalid")
        optional_values: dict[str, Decimal] = {}
        for field in _PRICE_FIELDS[1:]:
            if field not in prices or prices[field] is None:
                continue
            try:
                optional_values[field] = _parse_decimal(
                    prices[field],
                    field=field,
                    positive=False,
                )
            except ValueError as exc:
                price_state = "BLOCKED"
                blockers.append(f"{field}_invalid:{str(exc).replace(' ', '_')}")
        if price is not None:
            if "min_price" in optional_values and optional_values["min_price"] > price:
                price_state = "BLOCKED"
                blockers.append("price_min_above_current")
            if "old_price" in optional_values and optional_values["old_price"] < price:
                price_state = "BLOCKED"
                blockers.append("price_old_below_current")

    stock_state: QualityStateValue = "NO_DATA"
    stocks_raw = item.get("stocks")
    if isinstance(stocks_raw, Mapping):
        stocks_raw = stocks_raw.get("stocks")
    normalized_stocks: list[NormalizedStock] = []
    if stocks_raw is None:
        blockers.append("stock_breakdown_missing")
    elif not isinstance(stocks_raw, Sequence) or isinstance(stocks_raw, (str, bytes, bytearray)):
        stock_state = "BLOCKED"
        blockers.append("stock_breakdown_not_list")
    elif not stocks_raw:
        blockers.append("stock_breakdown_missing")
    else:
        seen_warehouses: set[str] = set()
        for index, raw_stock in enumerate(stocks_raw):
            if not isinstance(raw_stock, Mapping):
                stock_state = "BLOCKED"
                blockers.append(f"stock_row_not_object:{index}")
                continue
            try:
                warehouse_value = _alias_value(
                    raw_stock,
                    _WAREHOUSE_ALIASES,
                    field=f"stock[{index}].warehouse_ref",
                )
            except ValueError:
                warehouse_value = _MISSING
                stock_state = "BLOCKED"
                blockers.append(f"stock_warehouse_ambiguous:{index}")
            if warehouse_value is _MISSING or not str(warehouse_value).strip():
                stock_state = "BLOCKED"
                blockers.append(f"stock_warehouse_missing:{index}")
                continue
            warehouse_ref = str(warehouse_value).strip()
            if warehouse_ref in seen_warehouses:
                stock_state = "BLOCKED"
                blockers.append(f"stock_warehouse_duplicate:{warehouse_ref}")
                continue
            seen_warehouses.add(warehouse_ref)
            try:
                present_value = _alias_value(
                    raw_stock,
                    _STOCK_VALUE_ALIASES,
                    field=f"stock[{index}].present",
                )
            except ValueError:
                present_value = _MISSING
                stock_state = "BLOCKED"
                blockers.append(f"stock_quantity_ambiguous:{index}")
            if present_value is _MISSING:
                stock_state = "BLOCKED"
                blockers.append(f"stock_quantity_missing:{index}")
                continue
            try:
                present = _parse_integer(present_value, field=f"stock[{index}].present")
            except ValueError as exc:
                stock_state = "BLOCKED"
                blockers.append(f"stock_quantity_invalid:{index}:{str(exc).replace(' ', '_')}")
                continue
            reserved: int | None = None
            if "reserved" in raw_stock or "reserved_quantity" in raw_stock:
                try:
                    reserved_value = _alias_value(
                        raw_stock,
                        ("reserved", "reserved_quantity"),
                        field=f"stock[{index}].reserved",
                    )
                    if reserved_value is not _MISSING:
                        reserved = _parse_integer(
                            reserved_value,
                            field=f"stock[{index}].reserved",
                        )
                except ValueError as exc:
                    stock_state = "BLOCKED"
                    blockers.append(f"stock_reserved_invalid:{index}:{str(exc).replace(' ', '_')}")
            normalized_stocks.append(
                NormalizedStock(
                    warehouse_ref=warehouse_ref,
                    present=present,
                    reserved=reserved,
                )
            )
        if normalized_stocks and not any(reason.startswith("stock_") for reason in blockers):
            stock_state = "VALID"
        elif normalized_stocks and stock_state != "BLOCKED":
            stock_state = "BLOCKED"

    stock_total: int | None = None
    aggregate_value = item.get("available_stock")
    if aggregate_value is not None:
        try:
            stock_total = _parse_integer(aggregate_value, field="available_stock")
            if normalized_stocks and stock_total != sum(stock.present for stock in normalized_stocks):
                stock_state = "BLOCKED"
                blockers.append("stock_total_mismatch")
        except ValueError as exc:
            stock_state = "BLOCKED"
            blockers.append(f"stock_total_invalid:{str(exc).replace(' ', '_')}")
    elif normalized_stocks:
        stock_total = sum(stock.present for stock in normalized_stocks)

    # A field-specific quality marker may be supplied by an upstream adapter.
    # It can only reduce trust; it never upgrades malformed data.
    field_price_state = _quality_state(item.get("price_quality"))
    field_stock_state = _quality_state(item.get("stock_quality"))
    if item.get("price_quality") is not None and field_price_state is None:
        price_state = "BLOCKED"
        blockers.append("price_quality_invalid")
    elif field_price_state in {"BLOCKED", "UNKNOWN_OUTCOME", "STALE", "PARTIAL", "NO_DATA"}:
        price_state = field_price_state  # type: ignore[assignment]
    if item.get("stock_quality") is not None and field_stock_state is None:
        stock_state = "BLOCKED"
        blockers.append("stock_quality_invalid")
    elif field_stock_state in {"BLOCKED", "UNKNOWN_OUTCOME", "STALE", "PARTIAL", "NO_DATA"}:
        stock_state = field_stock_state  # type: ignore[assignment]

    if explicit_state in {"BLOCKED", "UNKNOWN_OUTCOME", "STALE", "PARTIAL", "NO_DATA"}:
        if explicit_state == "BLOCKED":
            price_state = stock_state = "BLOCKED"
        elif explicit_state == "UNKNOWN_OUTCOME":
            price_state = stock_state = "UNKNOWN_OUTCOME"
        elif explicit_state == "STALE":
            if price_state == "VALID":
                price_state = "STALE"
            if stock_state == "VALID":
                stock_state = "STALE"
        elif explicit_state == "PARTIAL":
            if price_state == "VALID":
                price_state = "PARTIAL"
            if stock_state == "VALID":
                stock_state = "PARTIAL"
        elif explicit_state == "NO_DATA":
            price_state = stock_state = "NO_DATA"

    if freshness == "stale":
        if price_state == "VALID":
            price_state = "STALE"
        if stock_state == "VALID":
            stock_state = "STALE"
    if freshness == "unknown" and observed is None:
        warnings.append("freshness_unknown")

    shared_blocked = any(
        reason
        in {
            "source_evidence_missing",
            "source_evidence_hash_invalid",
            "item_hash_invalid",
            "observed_at_invalid",
            "observed_at_in_future",
            "fresh_until_invalid",
            "fresh_until_before_observed_at",
            "quality_state_invalid",
        }
        for reason in blockers
    )
    quality_state = _combine_quality(
        price_state,
        stock_state,
        explicit_state=explicit_state,
        shared_blocked=shared_blocked,
    )
    canonical = {
        "contract_id": "kjds-ozon-price-stock-quality-v1",
        "price_state": price_state,
        "stock_state": stock_state,
        "quality_state": quality_state,
        "freshness": freshness,
        "observed_at": observed,
        "fresh_until": fresh_until,
        "price": price,
        "currency_code": currency_code,
        "stocks": [stock.model_dump() for stock in sorted(normalized_stocks, key=lambda value: value.warehouse_ref)],
        "stock_total": stock_total,
        "source_evidence_id": source_evidence_id,
        "source_evidence_sha256": source_evidence_sha256,
        "item_hash": item_hash,
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
    }
    return PriceStockQuality(
        price_state=price_state,
        stock_state=stock_state,
        quality_state=quality_state,
        freshness=freshness,
        observed_at=observed,
        fresh_until=fresh_until,
        price=price,
        currency_code=currency_code,
        stocks=tuple(sorted(normalized_stocks, key=lambda value: value.warehouse_ref)),
        stock_total=stock_total,
        source_evidence_id=source_evidence_id,
        source_evidence_sha256=source_evidence_sha256,
        item_hash=item_hash,
        blockers=tuple(sorted(set(blockers))),
        warnings=tuple(sorted(set(warnings))),
        snapshot_sha256=_hash(canonical),
    )


def _mapping_value(value: Any) -> Mapping[str, Any] | None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    return value if isinstance(value, Mapping) else None


def _normalize_scope(scope: Any) -> tuple[dict[str, str | None], list[str]]:
    mapping = _mapping_value(scope)
    if mapping is None:
        return {"tenant_ref": None, "entity_ref": None, "store_ref": None}, ["scope_not_object"]
    aliases = {
        "tenant_ref": ("tenant_ref", "tenant_id", "tenant"),
        "entity_ref": ("entity_ref", "entity_id", "entity"),
        "store_ref": ("store_ref", "store_id", "store"),
    }
    normalized: dict[str, str | None] = {}
    errors: list[str] = []
    for field, names in aliases.items():
        values = [mapping[name] for name in names if mapping.get(name) is not None]
        value = values[0] if values else None
        if values and any(str(candidate).strip() != str(value).strip() for candidate in values[1:]):
            errors.append(f"scope_{field}_ambiguous")
        text = _optional_text(value, max_length=160)
        normalized[field] = text
        if text is None:
            errors.append(f"scope_{field}_missing")
    return normalized, errors


def _extract_requested_patch(item: Mapping[str, Any], explicit: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if explicit is not None:
        return explicit
    for key in ("requested_patch", "proposed_patch", "desired_patch", "patch"):
        candidate = item.get(key)
        if isinstance(candidate, Mapping):
            return candidate
    derived: dict[str, Any] = {}
    if "proposed_price" in item:
        derived["price"] = item["proposed_price"]
    if "proposed_stock" in item:
        derived["stock"] = item["proposed_stock"]
    return derived


def _normalize_patch(
    raw_patch: Mapping[str, Any],
    *,
    quality: PriceStockQuality,
    offer_id: str | None,
    sku: str | None,
) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    patch: dict[str, Any] = {}
    if not isinstance(raw_patch, Mapping):
        return {}, ["requested_patch_not_object"]
    unknown = sorted(set(str(key) for key in raw_patch) - _PATCH_ALLOWED_KEYS)
    errors.extend(f"patch_key_unsupported:{key}" for key in unknown)
    for key, expected, label in (
        ("offer_id", offer_id, "offer_id"),
        ("sku", sku, "sku"),
        ("marketplace_sku", sku, "marketplace_sku"),
    ):
        if key in raw_patch and expected is not None and str(raw_patch[key]).strip() != expected:
            errors.append(f"patch_{label}_mismatch")

    raw_price = raw_patch.get("price", raw_patch.get("price_rub", _MISSING))
    if raw_price is not _MISSING:
        try:
            normalized_price = _parse_decimal(raw_price, field="patch.price", positive=True)
            currency = _optional_text(raw_patch.get("currency_code"), max_length=12) or quality.currency_code
            if currency is None:
                errors.append("patch_price_currency_missing")
            else:
                currency = currency.upper()
                if len(currency) != 3 or not currency.isascii() or not currency.isalpha():
                    errors.append("patch_price_currency_invalid")
                elif quality.currency_code and currency != quality.currency_code:
                    errors.append("patch_price_currency_mismatch")
                else:
                    patch["price"] = _decimal_text(normalized_price)
                    patch["currency_code"] = currency
        except ValueError as exc:
            errors.append(f"patch_price_invalid:{str(exc).replace(' ', '_')}")

    raw_stock = raw_patch.get("stock", raw_patch.get("available_stock", _MISSING))
    stock_mapping: Mapping[str, Any] | None = None
    if raw_stock is _MISSING and "stocks" in raw_patch:
        values = raw_patch["stocks"]
        if isinstance(values, Mapping):
            stock_mapping = values
            try:
                raw_stock = _alias_value(values, _STOCK_VALUE_ALIASES, field="patch.stock")
            except ValueError:
                raw_stock = _MISSING
                errors.append("patch_stock_ambiguous")
        elif (
            isinstance(values, Sequence)
            and not isinstance(values, (str, bytes, bytearray))
            and len(values) == 1
            and isinstance(values[0], Mapping)
        ):
            stock_mapping = values[0]
            try:
                raw_stock = _alias_value(values[0], _STOCK_VALUE_ALIASES, field="patch.stock")
            except ValueError:
                raw_stock = _MISSING
                errors.append("patch_stock_ambiguous")
        else:
            errors.append("patch_stock_shape_invalid")
    elif isinstance(raw_stock, Mapping):
        stock_mapping = raw_stock
        try:
            raw_stock = _alias_value(raw_stock, _STOCK_VALUE_ALIASES, field="patch.stock")
        except ValueError:
            raw_stock = _MISSING
            errors.append("patch_stock_ambiguous")
    if raw_stock is not _MISSING:
        try:
            warehouse_value = _alias_value(
                raw_patch,
                ("warehouse_ref", "warehouse_id"),
                field="patch.warehouse_ref",
            )
        except ValueError:
            warehouse_value = _MISSING
            errors.append("patch_warehouse_ambiguous")
        if warehouse_value is _MISSING and stock_mapping is not None:
            try:
                warehouse_value = _alias_value(
                    stock_mapping,
                    _WAREHOUSE_ALIASES,
                    field="patch.warehouse_ref",
                )
            except ValueError:
                warehouse_value = _MISSING
                errors.append("patch_warehouse_ambiguous")
        if warehouse_value is _MISSING or not str(warehouse_value).strip():
            errors.append("patch_warehouse_missing")
        else:
            warehouse_ref = str(warehouse_value).strip()
            try:
                present = _parse_integer(raw_stock, field="patch.stock")
                patch["stock"] = {"warehouse_ref": warehouse_ref, "present": present}
            except ValueError as exc:
                errors.append(f"patch_stock_invalid:{str(exc).replace(' ', '_')}")
    elif "warehouse_ref" in raw_patch or "warehouse_id" in raw_patch:
        errors.append("patch_warehouse_without_stock")
    if "currency_code" in raw_patch and raw_price is _MISSING:
        errors.append("patch_currency_without_price")
    return patch, errors


def _guard_projection(value: EconomicGuardResult | Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    if value is None:
        return {"status": "missing", "reasons": []}, ["economic_guard_missing"]
    if isinstance(value, EconomicGuardResult):
        payload = {
            "status": value.status,
            "reasons": list(value.reasons),
            "snapshot_sha256": value.snapshot_sha256,
        }
    elif isinstance(value, Mapping):
        raw_reasons = value.get("reasons", ())
        if isinstance(raw_reasons, str):
            raw_reasons = (raw_reasons,)
        elif not isinstance(raw_reasons, Sequence):
            raw_reasons = ()
        payload = {
            "status": str(value.get("status") or "").strip().lower(),
            "reasons": sorted({str(item) for item in raw_reasons if str(item).strip()}),
            "snapshot_sha256": _hash_or_none(value.get("snapshot_sha256")),
        }
    else:
        return {"status": "invalid", "reasons": []}, ["economic_guard_invalid"]
    reasons = list(payload["reasons"])
    blockers: list[str] = []
    if payload["status"] not in {"allowed", "blocked"}:
        blockers.append("economic_guard_status_invalid")
    elif payload["status"] == "blocked":
        blockers.append("economic_guard_blocked")
    blockers.extend(f"economic_guard:{reason}" for reason in reasons)
    if not payload.get("snapshot_sha256"):
        blockers.append("economic_guard_snapshot_missing")
    return payload, blockers


def _experiment_projection(value: Any) -> tuple[dict[str, Any], list[str]]:
    if value is None:
        return {"status": "unmarked", "blocked_reasons": [], "findings": []}, []
    contamination_inputs: Sequence[Mapping[str, Any]] = ()
    direct_context: Mapping[str, Any] | None = None
    invalid_context = False
    if isinstance(value, Mapping):
        raw_experiments = value.get("experiments") or value.get("active_experiments")
        if raw_experiments is not None:
            if isinstance(raw_experiments, Sequence) and not isinstance(raw_experiments, (str, bytes, bytearray)):
                if any(not isinstance(item, Mapping) for item in raw_experiments):
                    invalid_context = True
                contamination_inputs = tuple(item for item in raw_experiments if isinstance(item, Mapping))
            else:
                invalid_context = True
        marker_keys = {
            "experiment_id",
            "protocol_id",
            "review_eligible",
            "causal_evidence",
            "causal_evidence_refs",
            "stop_rule",
            "stop_rule_ref",
        }
        if marker_keys.intersection(value):
            direct_context = value
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if any(not isinstance(item, Mapping) for item in value):
            invalid_context = True
        contamination_inputs = tuple(item for item in value if isinstance(item, Mapping))
    else:
        return {"status": "blocked", "blocked_reasons": ["experiment_context_invalid"], "findings": []}, [
            "experiment_context_invalid"
        ]

    if invalid_context:
        return {
            "status": "blocked",
            "blocked_reasons": ["experiment_context_invalid"],
            "findings": [],
        }, ["experiment_blocked", "experiment:experiment_context_invalid"]

    statuses: list[str] = []
    blocked_reasons: list[str] = []
    findings: list[dict[str, Any]] = []
    if contamination_inputs:
        contamination = check_experiment_contamination(contamination_inputs)
        statuses.append(contamination.status)
        blocked_reasons.extend(contamination.blocked_reasons)
        findings.extend(contamination.findings)
    if direct_context is not None:
        admission = evaluate_experiment_fact_admission({"experiment_context": direct_context})
        statuses.append(admission.status)
        blocked_reasons.extend(admission.blocked_reasons)
    if any(status == "blocked" for status in statuses):
        status = "blocked"
    elif any(status == "clear" for status in statuses):
        status = "clear"
    elif any(status == "eligible" for status in statuses):
        status = "eligible"
    else:
        status = "unmarked"
    payload = {
        "status": status,
        "blocked_reasons": sorted(set(blocked_reasons)),
        "findings": findings,
    }
    blockers = []
    if status == "blocked":
        blockers.append("experiment_blocked")
        blockers.extend(f"experiment:{reason}" for reason in sorted(set(blocked_reasons)))
    return payload, blockers


def build_price_stock_shadow(
    item: Mapping[str, Any] | Any,
    *,
    scope: Mapping[str, Any] | Any,
    before_state_hash: str | None,
    economic_guard: EconomicGuardResult | Mapping[str, Any] | None,
    experiment_context: Any = None,
    requested_patch: Mapping[str, Any] | None = None,
    observed_at: datetime | str | None = None,
    now: datetime | str | None = None,
    max_age: timedelta | int | float = DEFAULT_MAX_AGE,
) -> PriceStockShadow:
    """Build an exact-scope shadow packet while keeping execution closed."""

    if not isinstance(item, Mapping):
        quality = _empty_quality(blockers=("catalog_item_not_object",))
        normalized_scope, scope_errors = _normalize_scope(scope)
        blockers = tuple(sorted(set((*quality.blockers, *scope_errors, "requested_patch_missing"))))
        key = _hash({"contract_id": "kjds-ozon-price-stock-shadow-v1", "scope": normalized_scope, "blockers": blockers})
        return PriceStockShadow(
            status="blocked",
            scope=normalized_scope,
            target={},
            patch={},
            rollback_patch=None,
            before_state_hash=None,
            quality=quality,
            economic_guard={"status": "missing", "reasons": []},
            experiment={"status": "unmarked", "blocked_reasons": [], "findings": []},
            lineage_refs=(),
            blockers=blockers,
            idempotency_key=key,
            rollback_ref=None,
            fingerprint=key,
        )

    quality = validate_catalog_price_stock(
        item,
        observed_at=observed_at,
        now=now,
        max_age=max_age,
    )
    normalized_scope, blockers = _normalize_scope(scope)
    all_blockers = list(quality.blockers) + blockers
    offer_id = _optional_text(item.get("offer_id") or item.get("external_offer_id"), max_length=160)
    sku = _optional_text(item.get("marketplace_sku") or item.get("sku") or item.get("seller_sku"), max_length=240)
    if offer_id is None:
        all_blockers.append("target_offer_id_missing")
    if sku is None:
        all_blockers.append("target_sku_missing")
    for field in ("tenant_ref", "entity_ref", "store_ref"):
        item_value = _optional_text(item.get(field), max_length=160)
        if item_value is not None and normalized_scope[field] is not None and item_value != normalized_scope[field]:
            all_blockers.append(f"target_{field}_mismatch")

    before_hash = _hash_or_none(before_state_hash)
    if before_state_hash is None:
        all_blockers.append("before_state_hash_missing")
    elif before_hash is None:
        all_blockers.append("before_state_hash_invalid")
    if quality.item_hash is None:
        all_blockers.append("item_hash_missing")
    elif before_hash is not None and before_hash != quality.item_hash:
        all_blockers.append("before_state_hash_mismatch")

    raw_patch = _extract_requested_patch(item, requested_patch)
    if not raw_patch:
        all_blockers.append("requested_patch_missing")
    elif not isinstance(raw_patch, Mapping):
        all_blockers.append("requested_patch_not_object")
        raw_patch = {}
    patch, patch_errors = _normalize_patch(
        raw_patch,
        quality=quality,
        offer_id=offer_id,
        sku=sku,
    )
    all_blockers.extend(patch_errors)
    if not patch or not any(key in patch for key in ("price", "stock")):
        all_blockers.append("requested_change_missing")

    target: dict[str, str] = {}
    if offer_id is not None:
        target["offer_id"] = offer_id
    if sku is not None:
        target["sku"] = sku
    if "stock" in patch:
        target["warehouse_ref"] = patch["stock"]["warehouse_ref"]
        current_cell = next(
            (stock for stock in quality.stocks if stock.warehouse_ref == target["warehouse_ref"]),
            None,
        )
        if current_cell is None:
            all_blockers.append("rollback_stock_state_missing")
    else:
        current_cell = None

    rollback_patch: dict[str, Any] = {}
    if "price" in patch:
        if quality.price is None or quality.currency_code is None:
            all_blockers.append("rollback_price_state_missing")
        else:
            rollback_patch["price"] = _decimal_text(quality.price)
            rollback_patch["currency_code"] = quality.currency_code
    if "stock" in patch and current_cell is not None:
        rollback_patch["stock"] = {
            "warehouse_ref": current_cell.warehouse_ref,
            "present": current_cell.present,
        }
    if not rollback_patch:
        all_blockers.append("rollback_patch_missing")
    elif _json_safe(patch) == _json_safe(rollback_patch):
        all_blockers.append("no_effective_change")

    guard_payload, guard_blockers = _guard_projection(economic_guard)
    all_blockers.extend(guard_blockers)
    experiment_payload, experiment_blockers = _experiment_projection(experiment_context)
    all_blockers.extend(experiment_blockers)

    lineage: list[dict[str, Any]] = []
    if quality.source_evidence_id:
        lineage.append(
            {
                "kind": "evidence",
                "id": quality.source_evidence_id,
                "sha256": quality.source_evidence_sha256,
                "relationship": "supports",
            }
        )
    if quality.item_hash and offer_id:
        lineage.append(
            {
                "kind": "catalog_item",
                "id": offer_id,
                "sha256": quality.item_hash,
                "relationship": "before_state",
            }
        )

    canonical_basis = {
        "contract_id": "kjds-ozon-price-stock-shadow-v1",
        "scope": normalized_scope,
        "target": target,
        "before_state_hash": before_hash,
        "patch": patch,
        "rollback_patch": rollback_patch or None,
        "quality_snapshot_sha256": quality.snapshot_sha256,
        "economic_guard": guard_payload,
        "experiment": experiment_payload,
    }
    idempotency_key = _hash(canonical_basis)
    requested_idempotency = raw_patch.get("idempotency_key") or item.get("idempotency_key")
    if requested_idempotency is not None and str(requested_idempotency).strip().lower() != idempotency_key:
        all_blockers.append("idempotency_key_mismatch")
    unique_blockers = tuple(sorted(set(all_blockers)))
    status: ShadowStatus = "shadow_ready" if not unique_blockers else "blocked"
    rollback_ref = f"shadow-rollback:{_hash(rollback_patch)[:32]}" if rollback_patch else None
    fingerprint = _hash({**canonical_basis, "blockers": list(unique_blockers)})
    return PriceStockShadow(
        status=status,
        scope=normalized_scope,
        target=target,
        patch=patch,
        rollback_patch=rollback_patch or None,
        before_state_hash=before_hash,
        quality=quality,
        economic_guard=guard_payload,
        experiment=experiment_payload,
        lineage_refs=tuple(lineage),
        blockers=unique_blockers,
        idempotency_key=idempotency_key,
        rollback_ref=rollback_ref,
        fingerprint=fingerprint,
    )


def _field(value: PriceStockShadow | Mapping[str, Any], name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def assert_shadow_idempotent(
    existing: PriceStockShadow | Mapping[str, Any],
    candidate: PriceStockShadow | Mapping[str, Any],
) -> None:
    """Raise on an idempotency conflict; identical packets are accepted."""

    existing_key = str(_field(existing, "idempotency_key") or "").strip()
    candidate_key = str(_field(candidate, "idempotency_key") or "").strip()
    if not existing_key or not candidate_key or existing_key != candidate_key:
        raise ValueError("price/stock shadow idempotency conflict")
    existing_fingerprint = str(_field(existing, "fingerprint") or "").strip()
    candidate_fingerprint = str(_field(candidate, "fingerprint") or "").strip()
    if existing_fingerprint and candidate_fingerprint and existing_fingerprint != candidate_fingerprint:
        raise ValueError("price/stock shadow content changed for the same idempotency key")


def check_shadow_idempotency(
    existing: PriceStockShadow | Mapping[str, Any],
    candidate: PriceStockShadow | Mapping[str, Any],
) -> bool:
    """Return ``True`` for an exact replay and raise for changed content."""

    assert_shadow_idempotent(existing, candidate)
    return True


# Friendly aliases for callers that use the shorter proposal terminology.
PriceStockProposal = PriceStockShadow
validate_price_stock = validate_catalog_price_stock
build_shadow = build_price_stock_shadow


__all__ = [
    "DEFAULT_MAX_AGE",
    "NormalizedStock",
    "PriceStockProposal",
    "PriceStockQuality",
    "PriceStockShadow",
    "assert_shadow_idempotent",
    "build_price_stock_shadow",
    "build_shadow",
    "check_shadow_idempotency",
    "validate_catalog_price_stock",
    "validate_price_stock",
]
