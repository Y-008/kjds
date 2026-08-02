from datetime import UTC, datetime
from decimal import Decimal

import pytest

from apps.control_plane.money import FxBasis, MoneyAmount, MoneyConversion


def test_money_amount_requires_currency_time_and_evidence() -> None:
    observed = datetime(2026, 8, 2, 4, 30, tzinfo=UTC)
    money = MoneyAmount(Decimal("320.00"), "CNY", observed, "evd-own-price")

    assert money.to_dict() == {
        "amount": "320.00",
        "currency": "CNY",
        "occurred_at": "2026-08-02T04:30:00+00:00",
        "evidence_id": "evd-own-price",
    }

    with pytest.raises(ValueError, match="binary floating point"):
        MoneyAmount(320.0, "CNY", observed, "evd-own-price")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="uppercase"):
        MoneyAmount(Decimal("320"), "cny", observed, "evd-own-price")
    with pytest.raises(ValueError, match="timezone-aware"):
        MoneyAmount(Decimal("320"), "CNY", datetime(2026, 8, 2), "evd-own-price")
    with pytest.raises(ValueError, match="required"):
        MoneyAmount(Decimal("320"), "CNY", observed, "")


def test_fx_conversion_preserves_source_and_fx_lineage() -> None:
    observed = datetime(2026, 8, 2, 4, 30, tzinfo=UTC)
    source = MoneyAmount(Decimal("100.00"), "CNY", observed, "evd-own-price")
    basis = FxBasis("CNY", "RUB", Decimal("12.5000"), observed, "evd-official-fx")

    conversion = MoneyConversion.apply(source, basis)

    assert conversion.converted.amount == Decimal("1250.000000")
    assert conversion.converted.currency == "RUB"
    assert conversion.to_dict()["source"]["evidence_id"] == "evd-own-price"
    assert conversion.to_dict()["fx_basis"]["evidence_id"] == "evd-official-fx"
    assert conversion.to_dict()["converted"]["evidence_id"] == "evd-official-fx"

    with pytest.raises(ValueError, match="does not match"):
        FxBasis("USD", "RUB", Decimal("90"), observed, "evd-usd-rub").convert(source)
    with pytest.raises(ValueError, match="different"):
        FxBasis("CNY", "CNY", Decimal("1"), observed, "evd-invalid")
