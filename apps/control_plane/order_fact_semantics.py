from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def order_timestamp(value: Any) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("order fact effective_at must include a timezone")
    return parsed.astimezone(UTC)


def database_order_timestamp(value: datetime) -> datetime:
    """Normalize DB timestamptz without weakening external timestamp rules."""
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return order_timestamp(normalized)


def is_positive_decimal(value: Any) -> bool:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return parsed.is_finite() and parsed > 0


def is_positive_integer(value: Any) -> bool:
    if not is_positive_decimal(value):
        return False
    parsed = Decimal(str(value))
    return parsed == parsed.to_integral_value()


def is_non_negative_integer(value: Any) -> bool:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    return (
        parsed.is_finite()
        and parsed >= 0
        and parsed == parsed.to_integral_value()
    )


def is_explicit_currency(value: Any) -> bool:
    normalized = str(value or "").strip()
    return (
        len(normalized) == 3
        and normalized == normalized.upper()
        and normalized.isascii()
        and normalized.isalpha()
    )
