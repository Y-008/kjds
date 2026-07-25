from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.control_plane.logistics import (
    InMemoryLogisticsStore,
    LogisticsQuoteWorkspace,
    LogisticsRateCard,
)


def rate_card(**overrides):
    values = {
        "provider": "Carrier A",
        "route_code": "OZON-RFBS-MSK",
        "service_name": "Ozon rFBS Moscow",
        "origin_country": "CN",
        "destination_country": "RU",
        "marketplace": "OZON",
        "currency": "CNY",
        "declared_value_currency": "RUB",
        "price_per_kg": Decimal("20"),
        "base_charge_per_parcel": Decimal("5"),
        "minimum_charge_per_parcel": Decimal("12"),
        "volumetric_divisor_cm3_per_kg": Decimal("12000"),
        "weight_increment_kg": Decimal("0.1"),
        "min_weight_kg": Decimal("0.001"),
        "max_weight_kg": Decimal("30"),
        "max_length_cm": Decimal("150"),
        "max_width_cm": Decimal("80"),
        "max_height_cm": Decimal("80"),
        "max_dimensions_sum_cm": Decimal("310"),
        "min_declared_value": Decimal("0"),
        "max_declared_value": Decimal("250000"),
        "effective_at": "2026-07-20T00:00:00+00:00",
        "effective_until": "2026-08-20T00:00:00+00:00",
        "evidence_id": "evd-rate-card-1",
        "captured_by": "operator-1",
        "source_sheet": "realFBS calculator",
        "source_range": "D5:M24",
    }
    values.update(overrides)
    return LogisticsRateCard(**values)


def workspace():
    links = []
    store = InMemoryLogisticsStore()
    service = LogisticsQuoteWorkspace(
        store,
        evidence_validator=lambda evidence_ids: None,
        evidence_linker=lambda **values: links.append(values),
        evidence_resolver=lambda evidence_id: SimpleNamespace(
            source=(
                "fx_rate_snapshot" if evidence_id == "evd-fx-1" else "carrier_rate_card"
            ),
            grade="B",
            metadata=(
                {
                    "base_currency": "RUB",
                    "quote_currency": "CNY",
                    "rate": "0.09",
                }
                if evidence_id == "evd-fx-1"
                else {}
            ),
        ),
        fx_evidence_current_validator=lambda evidence_ids, as_of: None,
    )
    return service, store, links


def test_chargeable_weight_uses_volumetric_weight_and_rounds_up():
    service, _, links = workspace()
    card = service.capture_rate_card(rate_card())

    result = service.calculate(
        rate_card_id=card.id,
        physical_weight_kg=Decimal("0.5"),
        length_cm=Decimal("60"),
        width_cm=Decimal("40"),
        height_cm=Decimal("30"),
        declared_value=Decimal("2000"),
        quantity=1,
        currency_to_cny_rate=Decimal("1"),
        idempotency_key="quote-1",
        calculated_by="operator-1",
        evaluated_at="2026-07-26T00:00:00+00:00",
    )

    assert result.volumetric_weight_kg == Decimal("6.000")
    assert result.chargeable_weight_kg == Decimal("6.000")
    assert result.billable_weight_kg == Decimal("6.000")
    assert result.unit_charge_currency == Decimal("125.00")
    assert result.total_charge_cny == Decimal("125.00")
    assert result.state == "estimate"
    assert [item["target_type"] for item in links] == [
        "logistics_rate_card",
        "logistics_calculation",
    ]
    support = service.decision_support(result.id)
    assert support["alerts"][0]["code"] == "VOLUMETRIC_WEIGHT_DOMINATES"
    assert support["recommendations"][0]["action"] == "PACKAGING_REVIEW"
    assert support["ai_boundary"]["automatic_procurement"] is False


def test_calculation_is_idempotent_and_rejects_conflicting_reuse():
    service, _, _ = workspace()
    card = service.capture_rate_card(rate_card())
    inputs = {
        "rate_card_id": card.id,
        "physical_weight_kg": Decimal("0.51"),
        "length_cm": Decimal("10"),
        "width_cm": Decimal("10"),
        "height_cm": Decimal("10"),
        "declared_value": Decimal("1000"),
        "quantity": 1,
        "currency_to_cny_rate": Decimal("1"),
        "idempotency_key": "quote-idempotent",
        "calculated_by": "operator-1",
        "evaluated_at": "2026-07-26T00:00:00+00:00",
    }

    first = service.calculate(**inputs)
    replay = service.calculate(
        **{
            **inputs,
            "physical_weight_kg": Decimal("0.5100"),
            "length_cm": Decimal("10.00"),
            "currency_to_cny_rate": Decimal("1.0000"),
        }
    )

    assert replay.id == first.id
    assert first.billable_weight_kg == Decimal("0.600")
    with pytest.raises(ValueError, match="different inputs"):
        service.calculate(**{**inputs, "length_cm": Decimal("11")})


def test_rate_card_constraints_and_validity_fail_closed():
    service, _, _ = workspace()
    card = service.capture_rate_card(rate_card())
    inputs = {
        "rate_card_id": card.id,
        "physical_weight_kg": Decimal("1"),
        "length_cm": Decimal("151"),
        "width_cm": Decimal("10"),
        "height_cm": Decimal("10"),
        "declared_value": Decimal("1000"),
        "quantity": 1,
        "currency_to_cny_rate": Decimal("1"),
        "idempotency_key": "too-long",
        "calculated_by": "operator-1",
        "evaluated_at": "2026-07-26T00:00:00+00:00",
    }

    with pytest.raises(ValueError, match="length exceeds"):
        service.calculate(**inputs)
    with pytest.raises(ValueError, match="expired"):
        service.calculate(
            **{
                **inputs,
                "length_cm": Decimal("10"),
                "idempotency_key": "expired",
                "evaluated_at": "2026-08-20T00:00:00+00:00",
            }
        )
    value_tier = service.capture_rate_card(
        rate_card(
            route_code="VALUE-TIER",
            min_declared_value=Decimal("1501"),
            max_declared_value=Decimal("7000"),
        )
    )
    with pytest.raises(ValueError, match="below"):
        service.calculate(
            **{
                **inputs,
                "rate_card_id": value_tier.id,
                "length_cm": Decimal("10"),
                "declared_value": Decimal("1500"),
                "idempotency_key": "below-value-tier",
            }
        )


def test_physical_only_route_and_minimum_charge_are_explicit():
    service, _, _ = workspace()
    card = service.capture_rate_card(
        rate_card(
            volumetric_divisor_cm3_per_kg=Decimal("0"),
            price_per_kg=Decimal("3"),
            base_charge_per_parcel=Decimal("1"),
            minimum_charge_per_parcel=Decimal("10"),
        )
    )

    result = service.calculate(
        rate_card_id=card.id,
        physical_weight_kg=Decimal("0.4"),
        length_cm=Decimal("60"),
        width_cm=Decimal("40"),
        height_cm=Decimal("30"),
        declared_value=Decimal("1000"),
        quantity=2,
        currency_to_cny_rate=Decimal("1"),
        idempotency_key="physical-only",
        calculated_by="operator-1",
        evaluated_at="2026-07-26T00:00:00+00:00",
    )

    assert result.volumetric_weight_kg == Decimal("0.000")
    assert result.unit_charge_currency == Decimal("10.00")
    assert result.total_charge_cny == Decimal("20.00")


def test_volumetric_weight_rounds_only_after_billable_weight_ceiling():
    service, _, _ = workspace()
    card = service.capture_rate_card(rate_card(weight_increment_kg=Decimal("0.1")))

    result = service.calculate(
        rate_card_id=card.id,
        physical_weight_kg=Decimal("1"),
        length_cm=Decimal("100"),
        width_cm=Decimal("30"),
        height_cm=Decimal("10.0004"),
        declared_value=Decimal("2000"),
        quantity=1,
        currency_to_cny_rate=Decimal("1"),
        idempotency_key="volumetric-boundary",
        calculated_by="operator-1",
        evaluated_at="2026-07-26T00:00:00+00:00",
    )

    assert result.volumetric_weight_kg == Decimal("2.5001")
    assert result.billable_weight_kg == Decimal("2.6")


def test_non_cny_route_requires_fx_evidence_and_cny_route_requires_parity():
    service, _, links = workspace()
    rub_card = service.capture_rate_card(
        rate_card(route_code="RUB-ROUTE", currency="RUB")
    )
    values = {
        "rate_card_id": rub_card.id,
        "physical_weight_kg": Decimal("1"),
        "length_cm": Decimal("10"),
        "width_cm": Decimal("10"),
        "height_cm": Decimal("10"),
        "declared_value": Decimal("2000"),
        "quantity": 1,
        "currency_to_cny_rate": Decimal("0.09"),
        "idempotency_key": "rub-route",
        "calculated_by": "operator-1",
        "evaluated_at": "2026-07-26T00:00:00+00:00",
    }

    with pytest.raises(ValueError, match="require FX evidence"):
        service.calculate(**values)
    result = service.calculate(**values, fx_evidence_id="evd-fx-1")

    assert result.fx_evidence_id == "evd-fx-1"
    assert links[-1]["relationship"] == "fx_source_for"
    with pytest.raises(ValueError, match="does not match currency_to_cny_rate"):
        service.calculate(
            **{
                **values,
                "currency_to_cny_rate": Decimal("0.10"),
                "idempotency_key": "rub-route-wrong-rate",
            },
            fx_evidence_id="evd-fx-1",
        )
    cny_card = service.capture_rate_card(rate_card(route_code="CNY-PARITY"))
    with pytest.raises(ValueError, match="1:1"):
        service.calculate(
            **{
                **values,
                "rate_card_id": cny_card.id,
                "currency_to_cny_rate": Decimal("0.99"),
                "idempotency_key": "bad-cny-rate",
            }
        )


def test_profit_cost_resolution_requires_exact_ozon_ru_shipment_scope():
    service, _, _ = workspace()
    card = service.capture_rate_card(rate_card())
    calculation = service.calculate(
        rate_card_id=card.id,
        physical_weight_kg=Decimal("0.5"),
        length_cm=Decimal("30"),
        width_cm=Decimal("20"),
        height_cm=Decimal("10"),
        declared_value=Decimal("1800"),
        quantity=1,
        currency_to_cny_rate=Decimal("1"),
        idempotency_key="profit-compatible",
        calculated_by="operator-1",
        evaluated_at="2026-07-26T00:00:00+00:00",
    )
    expected = {
        "marketplace": "OZON",
        "destination_country": "RU",
        "declared_value_currency": "RUB",
        "declared_value": Decimal("1800"),
        "physical_weight_kg": Decimal("0.5"),
        "length_cm": Decimal("30"),
        "width_cm": Decimal("20"),
        "height_cm": Decimal("10"),
    }

    assert service.resolve_profit_cost(calculation.id, **expected) == calculation
    with pytest.raises(ValueError, match="shipment inputs"):
        service.resolve_profit_cost(
            calculation.id,
            **{**expected, "declared_value": Decimal("2000")},
        )
    with pytest.raises(ValueError, match="scope"):
        service.resolve_profit_cost(
            calculation.id,
            **{**expected, "declared_value_currency": "EUR"},
        )


def test_rate_card_rejects_a_zero_charge_schedule():
    with pytest.raises(ValueError, match="at least one positive charge"):
        rate_card(
            price_per_kg=Decimal("0"),
            base_charge_per_parcel=Decimal("0"),
            minimum_charge_per_parcel=Decimal("0"),
        )


def test_rate_card_rejects_semantically_unrelated_evidence():
    service, _, _ = workspace()
    service.evidence_resolver = lambda evidence_id: SimpleNamespace(
        source="ozon_export",
        grade="A",
        metadata={},
    )

    with pytest.raises(ValueError, match="carrier quote"):
        service.capture_rate_card(rate_card(evidence_id="evd-catalog"))
