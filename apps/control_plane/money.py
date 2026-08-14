from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def _finite_decimal(value: Decimal | str | int, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, (bool, float)):
        raise ValueError(f"{field} must not use binary floating point")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be a finite decimal")
    if positive and parsed <= 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def _currency(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 3 or not value.isascii() or not value.isalpha():
        raise ValueError(f"{field} must be a three-letter ASCII currency")
    if value != value.upper():
        raise ValueError(f"{field} must be uppercase")
    return value


def _aware_timestamp(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value


def _evidence_ref(value: str, field: str = "evidence_id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True, slots=True)
class MoneyAmount:
    """A monetary observation that cannot lose currency, time, or evidence lineage."""

    amount: Decimal
    currency: str
    occurred_at: datetime
    evidence_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", _finite_decimal(self.amount, "amount"))
        object.__setattr__(self, "currency", _currency(self.currency, "currency"))
        object.__setattr__(self, "occurred_at", _aware_timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "evidence_id", _evidence_ref(self.evidence_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "amount": _decimal_text(self.amount),
            "currency": self.currency,
            "occurred_at": self.occurred_at.isoformat(),
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True, slots=True)
class FxBasis:
    """Evidence-bound quote: one source currency unit equals `rate` target units."""

    source_currency: str
    target_currency: str
    rate: Decimal
    effective_at: datetime
    evidence_id: str

    def __post_init__(self) -> None:
        source = _currency(self.source_currency, "source_currency")
        target = _currency(self.target_currency, "target_currency")
        if source == target:
            raise ValueError("FX basis requires different source and target currencies")
        object.__setattr__(self, "source_currency", source)
        object.__setattr__(self, "target_currency", target)
        object.__setattr__(self, "rate", _finite_decimal(self.rate, "rate", positive=True))
        object.__setattr__(self, "effective_at", _aware_timestamp(self.effective_at, "effective_at"))
        object.__setattr__(self, "evidence_id", _evidence_ref(self.evidence_id))

    def convert(self, money: MoneyAmount) -> MoneyAmount:
        if money.currency != self.source_currency:
            raise ValueError(
                f"money currency {money.currency} does not match FX source currency {self.source_currency}"
            )
        return MoneyAmount(
            amount=money.amount * self.rate,
            currency=self.target_currency,
            occurred_at=money.occurred_at,
            evidence_id=self.evidence_id,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rate"] = _decimal_text(self.rate)
        payload["effective_at"] = self.effective_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class MoneyConversion:
    """Keeps both source and FX evidence visible when presenting a conversion."""

    source: MoneyAmount
    basis: FxBasis
    converted: MoneyAmount

    @classmethod
    def apply(cls, source: MoneyAmount, basis: FxBasis) -> MoneyConversion:
        return cls(source=source, basis=basis, converted=basis.convert(source))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "fx_basis": self.basis.to_dict(),
            "converted": self.converted.to_dict(),
        }
