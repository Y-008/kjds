from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def finite_decimal(value: Any, name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{name} must be finite")
    return parsed


def ascii_currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or any(character < "A" or character > "Z" for character in normalized):
        raise ValueError("Currency must be a three-letter ASCII code")
    return normalized
