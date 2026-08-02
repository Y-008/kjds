from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.evidence_scope import DIRECT_CONTRACT, ScopedEvidenceAuthority
from apps.control_plane.logistics import (
    InMemoryLogisticsStore,
    LogisticsQuoteWorkspace,
    LogisticsRateCard,
    LogisticsScope,
    LogisticsScopeContext,
    SqlLogisticsStore,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

SCOPE_TIME = datetime(2026, 7, 26, 0, 0, tzinfo=UTC)


class ScopedEvidenceStub:
    def __init__(self):
        self.status = "ready"
        self.blocked_ids = set()
        self.allowed_scopes = {
            "evd-rate-card-1": {("tenant-a", "entity-a", "store-a")},
            "evd-rate-card-2": {("tenant-b", "entity-b", "store-b")},
            "evd-fx-1": {("tenant-a", "entity-a", "store-a")},
        }

    def project_targets(
        self,
        *,
        evidence_ids,
        principal,
        entity_scope,
        store_ref,
        as_of,
    ):
        del as_of
        requested_scope = (
            principal.tenant_ref,
            entity_scope.get("entity_ref"),
            store_ref,
        )
        records = [
            {
                "evidence_id": evidence_id,
                "scope_binding": {
                    "status": (
                        "ready"
                        if self.status == "ready"
                        and evidence_id not in self.blocked_ids
                        and requested_scope
                        in self.allowed_scopes.get(evidence_id, set())
                        else "blocked"
                    )
                },
            }
            for evidence_id in evidence_ids
        ]
        return {
            "status": (
                "ready"
                if records
                and all(
                    item["scope_binding"]["status"] == "ready"
                    for item in records
                )
                else "blocked"
            ),
            "records": records,
        }


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


def workspace(store=None):
    links = []
    store = store if store is not None else InMemoryLogisticsStore()
    scoped_evidence = ScopedEvidenceStub()
    records = {
        "evd-rate-card-1": SimpleNamespace(
            source="carrier_rate_card",
            grade="B",
            metadata={},
        ),
        "evd-rate-card-2": SimpleNamespace(
            source="carrier_rate_card",
            grade="B",
            metadata={},
        ),
        "evd-fx-1": SimpleNamespace(
            source="fx_rate_snapshot",
            grade="B",
            metadata={
                "base_currency": "RUB",
                "quote_currency": "CNY",
                "rate": "0.09",
            },
        ),
    }
    service = LogisticsQuoteWorkspace(
        store,
        evidence_validator=lambda evidence_ids: None,
        evidence_linker=lambda **values: links.append(values),
        evidence_resolver=records.__getitem__,
        fx_evidence_current_validator=lambda evidence_ids, as_of: None,
        scoped_evidence=scoped_evidence,
    )
    context = scope_context(service)
    return service, store, links, context, scoped_evidence


def scope_context(
    service,
    *,
    tenant_ref="tenant-a",
    entity_ref="entity-a",
    store_ref="store-a",
    authority="a" * 64,
):
    principal = Principal(
        actor_id="operator-1",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=frozenset({store_ref}),
    )
    return service.context(
        principal=principal,
        entity_scope={
            "status": "ready",
            "tenant_ref": tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "authority_sha256": authority,
        },
        store_ref=store_ref,
        as_of=SCOPE_TIME,
    )


def sqlite_logistics_store():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    rate_columns = """
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        route_code TEXT NOT NULL,
        service_name TEXT NOT NULL,
        origin_country TEXT NOT NULL,
        destination_country TEXT NOT NULL,
        marketplace TEXT NOT NULL,
        currency TEXT NOT NULL,
        declared_value_currency TEXT NOT NULL,
        price_per_kg NUMERIC NOT NULL,
        base_charge_per_parcel NUMERIC NOT NULL,
        minimum_charge_per_parcel NUMERIC NOT NULL,
        volumetric_divisor_cm3_per_kg NUMERIC NOT NULL,
        weight_increment_kg NUMERIC NOT NULL,
        min_weight_kg NUMERIC NOT NULL,
        max_weight_kg NUMERIC NOT NULL,
        max_length_cm NUMERIC NOT NULL,
        max_width_cm NUMERIC NOT NULL,
        max_height_cm NUMERIC NOT NULL,
        max_dimensions_sum_cm NUMERIC NOT NULL,
        min_declared_value NUMERIC NOT NULL,
        max_declared_value NUMERIC NOT NULL,
        effective_at TEXT NOT NULL,
        effective_until TEXT,
        evidence_id TEXT NOT NULL,
        captured_by TEXT NOT NULL,
        source_sheet TEXT NOT NULL,
        source_range TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        tenant_ref TEXT,
        entity_ref TEXT,
        store_ref TEXT,
        scope_grant_authority_sha256 TEXT,
        scope_as_of TEXT,
        scope_status TEXT NOT NULL DEFAULT 'legacy_unbound',
        rate_card_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        CONSTRAINT uq_logistics_rate_card_scope_identity UNIQUE (
            id, tenant_ref, entity_ref, store_ref,
            scope_grant_authority_sha256
        ),
        CONSTRAINT uq_logistics_rate_card_exact_scope_hash UNIQUE (
            tenant_ref, entity_ref, store_ref,
            scope_grant_authority_sha256, rate_card_hash
        ),
        CHECK (
            (scope_status = 'legacy_unbound' AND tenant_ref IS NULL
             AND entity_ref IS NULL AND store_ref IS NULL
             AND scope_grant_authority_sha256 IS NULL AND scope_as_of IS NULL)
            OR
            (scope_status = 'ready' AND tenant_ref IS NOT NULL
             AND entity_ref IS NOT NULL AND store_ref IS NOT NULL
             AND length(scope_grant_authority_sha256) = 64
             AND scope_as_of IS NOT NULL)
        )
    """
    calculation_columns = """
        id TEXT PRIMARY KEY,
        rate_card_id TEXT NOT NULL,
        physical_weight_kg NUMERIC NOT NULL,
        length_cm NUMERIC NOT NULL,
        width_cm NUMERIC NOT NULL,
        height_cm NUMERIC NOT NULL,
        declared_value NUMERIC NOT NULL,
        quantity INTEGER NOT NULL,
        currency_to_cny_rate NUMERIC NOT NULL,
        volumetric_weight_kg NUMERIC NOT NULL,
        chargeable_weight_kg NUMERIC NOT NULL,
        billable_weight_kg NUMERIC NOT NULL,
        unit_charge_currency NUMERIC NOT NULL,
        total_charge_currency NUMERIC NOT NULL,
        total_charge_cny NUMERIC NOT NULL,
        evidence_id TEXT NOT NULL,
        fx_evidence_id TEXT,
        idempotency_key TEXT NOT NULL,
        input_hash TEXT NOT NULL,
        calculated_by TEXT NOT NULL,
        state TEXT NOT NULL,
        tenant_ref TEXT,
        entity_ref TEXT,
        store_ref TEXT,
        scope_grant_authority_sha256 TEXT,
        scope_as_of TEXT,
        scope_status TEXT NOT NULL DEFAULT 'legacy_unbound',
        calculated_at TEXT NOT NULL,
        CONSTRAINT uq_logistics_calculation_exact_scope_idempotency UNIQUE (
            tenant_ref, entity_ref, store_ref,
            scope_grant_authority_sha256, rate_card_id, idempotency_key
        ),
        CONSTRAINT fk_logistics_calculation_exact_scope_rate_card
            FOREIGN KEY (
                rate_card_id, tenant_ref, entity_ref, store_ref,
                scope_grant_authority_sha256
            ) REFERENCES logistics_rate_cards (
                id, tenant_ref, entity_ref, store_ref,
                scope_grant_authority_sha256
            )
    """
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql(
            f"CREATE TABLE logistics_rate_cards ({rate_columns})"
        )
        connection.exec_driver_sql(
            f"CREATE TABLE logistics_calculations ({calculation_columns})"
        )
    return engine, SqlLogisticsStore(engine)


def test_chargeable_weight_uses_volumetric_weight_and_rounds_up():
    service, _, links, context, _ = workspace()
    card = service.capture_rate_card(context, rate_card())

    result = service.calculate(
        context,
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
    support = service.decision_support(context, result.id)
    assert support["alerts"][0]["code"] == "VOLUMETRIC_WEIGHT_DOMINATES"
    assert support["recommendations"][0]["action"] == "PACKAGING_REVIEW"
    assert support["ai_boundary"]["automatic_procurement"] is False


def test_calculation_is_idempotent_and_rejects_conflicting_reuse():
    service, _, _, context, _ = workspace()
    card = service.capture_rate_card(context, rate_card())
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

    first = service.calculate(context, **inputs)
    replay = service.calculate(
        context,
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
        service.calculate(context, **{**inputs, "length_cm": Decimal("11")})


def test_rate_card_constraints_and_validity_fail_closed():
    service, _, _, context, _ = workspace()
    card = service.capture_rate_card(context, rate_card())
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
        service.calculate(context, **inputs)
    with pytest.raises(ValueError, match="expired"):
        service.calculate(
            context,
            **{
                **inputs,
                "length_cm": Decimal("10"),
                "idempotency_key": "expired",
                "evaluated_at": "2026-08-20T00:00:00+00:00",
            }
        )
    value_tier = service.capture_rate_card(
        context,
        rate_card(
            route_code="VALUE-TIER",
            min_declared_value=Decimal("1501"),
            max_declared_value=Decimal("7000"),
        )
    )
    with pytest.raises(ValueError, match="below"):
        service.calculate(
            context,
            **{
                **inputs,
                "rate_card_id": value_tier.id,
                "length_cm": Decimal("10"),
                "declared_value": Decimal("1500"),
                "idempotency_key": "below-value-tier",
            }
        )


def test_physical_only_route_and_minimum_charge_are_explicit():
    service, _, _, context, _ = workspace()
    card = service.capture_rate_card(
        context,
        rate_card(
            volumetric_divisor_cm3_per_kg=Decimal("0"),
            price_per_kg=Decimal("3"),
            base_charge_per_parcel=Decimal("1"),
            minimum_charge_per_parcel=Decimal("10"),
        )
    )

    result = service.calculate(
        context,
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
    service, _, _, context, _ = workspace()
    card = service.capture_rate_card(
        context,
        rate_card(weight_increment_kg=Decimal("0.1")),
    )

    result = service.calculate(
        context,
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
    service, _, links, context, _ = workspace()
    rub_card = service.capture_rate_card(
        context,
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
        service.calculate(context, **values)
    result = service.calculate(context, **values, fx_evidence_id="evd-fx-1")

    assert result.fx_evidence_id == "evd-fx-1"
    assert links[-1]["relationship"] == "fx_source_for"
    with pytest.raises(ValueError, match="does not match currency_to_cny_rate"):
        service.calculate(
            context,
            **{
                **values,
                "currency_to_cny_rate": Decimal("0.10"),
                "idempotency_key": "rub-route-wrong-rate",
            },
            fx_evidence_id="evd-fx-1",
        )
    cny_card = service.capture_rate_card(
        context,
        rate_card(route_code="CNY-PARITY"),
    )
    with pytest.raises(ValueError, match="1:1"):
        service.calculate(
            context,
            **{
                **values,
                "rate_card_id": cny_card.id,
                "currency_to_cny_rate": Decimal("0.99"),
                "idempotency_key": "bad-cny-rate",
            }
        )


def test_profit_cost_resolution_requires_exact_ozon_ru_shipment_scope():
    service, _, _, context, _ = workspace()
    card = service.capture_rate_card(context, rate_card())
    calculation = service.calculate(
        context,
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

    assert (
        service.resolve_profit_cost(context, calculation.id, **expected)
        == calculation
    )
    with pytest.raises(ValueError, match="shipment inputs"):
        service.resolve_profit_cost(
            context,
            calculation.id,
            **{**expected, "declared_value": Decimal("2000")},
        )
    with pytest.raises(ValueError, match="scope"):
        service.resolve_profit_cost(
            context,
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
    service, _, _, context, scoped_evidence = workspace()
    scoped_evidence.allowed_scopes["evd-catalog"] = {
        ("tenant-a", "entity-a", "store-a")
    }
    service.evidence_resolver = lambda evidence_id: SimpleNamespace(
        source="ozon_export",
        grade="A",
        metadata={},
    )

    with pytest.raises(ValueError, match="carrier quote"):
        service.capture_rate_card(
            context,
            rate_card(evidence_id="evd-catalog"),
        )


def test_exact_scope_isolates_all_reads_calculations_and_decisions():
    service, _, _, context_a, scoped_evidence = workspace()
    context_b = scope_context(
        service,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        authority="b" * 64,
    )
    card_a = service.capture_rate_card(context_a, rate_card())
    card_b = service.capture_rate_card(
        context_b,
        rate_card(
            evidence_id="evd-rate-card-2",
            route_code="OZON-RFBS-SPB",
        ),
    )
    calculation_a = service.calculate(
        context_a,
        rate_card_id=card_a.id,
        physical_weight_kg=Decimal("0.5"),
        length_cm=Decimal("30"),
        width_cm=Decimal("20"),
        height_cm=Decimal("10"),
        declared_value=Decimal("1800"),
        quantity=1,
        currency_to_cny_rate=Decimal("1"),
        idempotency_key="scope-a",
        calculated_by="operator-1",
        evaluated_at="2026-07-26T00:00:00+00:00",
    )

    assert [item.id for item in service.list_rate_cards(context_a)] == [card_a.id]
    assert [item.id for item in service.list_rate_cards(context_b)] == [card_b.id]
    assert service.list_calculations(context_b) == []
    with pytest.raises(KeyError, match="Unknown logistics rate card"):
        service.get_rate_card(context_b, card_a.id)
    with pytest.raises(KeyError, match="Unknown logistics rate card"):
        service.calculate(
            context_b,
            rate_card_id=card_a.id,
            physical_weight_kg=Decimal("0.5"),
            length_cm=Decimal("30"),
            width_cm=Decimal("20"),
            height_cm=Decimal("10"),
            declared_value=Decimal("1800"),
            quantity=1,
            currency_to_cny_rate=Decimal("1"),
            idempotency_key="cross-scope",
            calculated_by="operator-1",
            evaluated_at="2026-07-26T00:00:00+00:00",
        )
    with pytest.raises(KeyError, match="Unknown logistics calculation"):
        service.decision_support(context_b, calculation_a.id)
    with pytest.raises(KeyError, match="Unknown logistics calculation"):
        service.resolve_profit_cost(
            context_b,
            calculation_a.id,
            marketplace="OZON",
            destination_country="RU",
            declared_value_currency="RUB",
            declared_value=Decimal("1800"),
            physical_weight_kg=Decimal("0.5"),
            length_cm=Decimal("30"),
            width_cm=Decimal("20"),
            height_cm=Decimal("10"),
        )

    drifted = scope_context(service, authority="c" * 64)
    assert service.list_rate_cards(drifted) == []
    assert service.list_calculations(drifted) == []
    with pytest.raises(KeyError, match="Unknown logistics rate card"):
        service.get_rate_card(drifted, card_a.id)
    assert scoped_evidence.status == "ready"


def test_hash_and_idempotency_are_exact_scope_unique():
    service, _, _, context_a, scoped_evidence = workspace()
    context_b = scope_context(
        service,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        authority="b" * 64,
    )
    scoped_evidence.allowed_scopes["evd-rate-card-1"].add(
        ("tenant-b", "entity-b", "store-b")
    )
    card_a = service.capture_rate_card(context_a, rate_card())
    card_b = service.capture_rate_card(context_b, rate_card())

    assert card_a.rate_card_hash == card_b.rate_card_hash
    assert card_a.id != card_b.id

    inputs = {
        "physical_weight_kg": Decimal("0.5"),
        "length_cm": Decimal("10"),
        "width_cm": Decimal("10"),
        "height_cm": Decimal("10"),
        "declared_value": Decimal("1000"),
        "quantity": 1,
        "currency_to_cny_rate": Decimal("1"),
        "idempotency_key": "same-key",
        "calculated_by": "operator-1",
        "evaluated_at": "2026-07-26T00:00:00+00:00",
    }
    calculation_a = service.calculate(
        context_a,
        rate_card_id=card_a.id,
        **inputs,
    )
    calculation_b = service.calculate(
        context_b,
        rate_card_id=card_b.id,
        **inputs,
    )

    assert calculation_a.id != calculation_b.id
    assert (
        service.calculate(context_a, rate_card_id=card_a.id, **inputs).id
        == calculation_a.id
    )
    with pytest.raises(ValueError, match="different inputs"):
        service.calculate(
            context_a,
            rate_card_id=card_a.id,
            **{**inputs, "length_cm": Decimal("11")},
        )
    with pytest.raises(ValueError, match="rate_card_hash"):
        replace(card_a, route_code="CONTENT-DRIFT")


def test_legacy_unbound_rows_remain_auditable_but_are_not_operational():
    service, store, _, context, _ = workspace()
    legacy_card = rate_card()
    store.rate_cards[legacy_card.id] = legacy_card

    assert service.list_rate_cards(context) == []
    with pytest.raises(KeyError, match="Unknown logistics rate card"):
        service.get_rate_card(context, legacy_card.id)
    with pytest.raises(ValueError, match="read-only"):
        store.save_rate_card(legacy_card)

    scoped_card = service.capture_rate_card(
        context,
        rate_card(route_code="SCOPED"),
    )
    scoped_calculation = service.calculate(
        context,
        rate_card_id=scoped_card.id,
        physical_weight_kg=Decimal("1"),
        length_cm=Decimal("10"),
        width_cm=Decimal("10"),
        height_cm=Decimal("10"),
        declared_value=Decimal("1000"),
        quantity=1,
        currency_to_cny_rate=Decimal("1"),
        idempotency_key="scoped",
        calculated_by="operator-1",
        evaluated_at="2026-07-26T00:00:00+00:00",
    )
    legacy_calculation = replace(
        scoped_calculation,
        id="lgc-legacy",
        tenant_ref=None,
        entity_ref=None,
        store_ref=None,
        scope_grant_authority_sha256=None,
        scope_as_of=None,
        scope_status="legacy_unbound",
    )
    store.calculations[legacy_calculation.id] = legacy_calculation

    assert [item.id for item in service.list_calculations(context)] == [
        scoped_calculation.id
    ]
    with pytest.raises(KeyError, match="Unknown logistics calculation"):
        service.get_calculation(context, legacy_calculation.id)
    with pytest.raises(ValueError, match="read-only"):
        store.save_calculation(legacy_calculation)


def test_evidence_scope_staleness_or_integrity_failure_blocks_reuse():
    service, _, _, context, scoped_evidence = workspace()
    card = service.capture_rate_card(context, rate_card())
    scoped_evidence.status = "blocked"

    with pytest.raises(ValueError, match="current, intact, and bound"):
        service.get_rate_card(context, card.id)
    with pytest.raises(ValueError, match="current, intact, and bound"):
        service.calculate(
            context,
            rate_card_id=card.id,
            physical_weight_kg=Decimal("1"),
            length_cm=Decimal("10"),
            width_cm=Decimal("10"),
            height_cm=Decimal("10"),
            declared_value=Decimal("1000"),
            quantity=1,
            currency_to_cny_rate=Decimal("1"),
            idempotency_key="blocked-evidence",
            calculated_by="operator-1",
            evaluated_at="2026-07-26T00:00:00+00:00",
        )


def test_fx_evidence_requires_exact_scope_and_is_revalidated_on_read():
    service, _, _, context_a, scoped_evidence = workspace()
    context_b = scope_context(
        service,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        authority="b" * 64,
    )
    card_b = service.capture_rate_card(
        context_b,
        rate_card(
            currency="RUB",
            evidence_id="evd-rate-card-2",
            route_code="RUB-B",
        ),
    )
    common = {
        "physical_weight_kg": Decimal("1"),
        "length_cm": Decimal("10"),
        "width_cm": Decimal("10"),
        "height_cm": Decimal("10"),
        "declared_value": Decimal("1000"),
        "quantity": 1,
        "currency_to_cny_rate": Decimal("0.09"),
        "calculated_by": "operator-1",
        "evaluated_at": "2026-07-26T00:00:00+00:00",
        "fx_evidence_id": "evd-fx-1",
    }
    with pytest.raises(ValueError, match="current, intact, and bound"):
        service.calculate(
            context_b,
            rate_card_id=card_b.id,
            idempotency_key="fx-wrong-scope",
            **common,
        )

    card_a = service.capture_rate_card(
        context_a,
        rate_card(currency="RUB", route_code="RUB-A"),
    )
    calculation = service.calculate(
        context_a,
        rate_card_id=card_a.id,
        idempotency_key="fx-current",
        **common,
    )
    scoped_evidence.blocked_ids.add("evd-fx-1")
    with pytest.raises(ValueError, match="current, intact, and bound"):
        service.get_calculation(context_a, calculation.id)


def test_store_rejects_calculation_whose_scope_does_not_match_rate_card():
    service, store, _, context, _ = workspace()
    card = service.capture_rate_card(context, rate_card())
    calculation = service.calculate(
        context,
        rate_card_id=card.id,
        physical_weight_kg=Decimal("1"),
        length_cm=Decimal("10"),
        width_cm=Decimal("10"),
        height_cm=Decimal("10"),
        declared_value=Decimal("1000"),
        quantity=1,
        currency_to_cny_rate=Decimal("1"),
        idempotency_key="valid-scope",
        calculated_by="operator-1",
        evaluated_at="2026-07-26T00:00:00+00:00",
    )
    mismatched = replace(
        calculation,
        id="lgc-mismatch",
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        scope_grant_authority_sha256="b" * 64,
    )

    with pytest.raises(KeyError, match="Unknown logistics rate card"):
        store.save_calculation(mismatched)


def test_context_rejects_principal_or_timestamp_scope_drift():
    service, _, _, context, _ = workspace()
    with pytest.raises(ValueError, match="tenant does not match"):
        LogisticsScopeContext(
            principal=context.principal,
            scope=LogisticsScope(
                tenant_ref="tenant-b",
                entity_ref="entity-a",
                store_ref="store-a",
                scope_grant_authority_sha256="a" * 64,
                scope_as_of=SCOPE_TIME.isoformat(),
            ),
            as_of=SCOPE_TIME,
        )
    with pytest.raises(ValueError, match="timestamp does not match"):
        LogisticsScopeContext(
            principal=context.principal,
            scope=context.scope,
            as_of=datetime(2026, 7, 27, 0, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("missing_field", "message"),
    (
        ("tenant_ref", "tenant does not match"),
        ("store_ref", "store does not match"),
    ),
)
def test_context_rejects_incomplete_exact_scope_authority(
    missing_field,
    message,
):
    service, _, _, context, _ = workspace()
    entity_scope = context.entity_scope()
    entity_scope.pop(missing_field)

    with pytest.raises(ValueError, match=message):
        service.context(
            principal=context.principal,
            entity_scope=entity_scope,
            store_ref=context.scope.store_ref,
            as_of=context.as_of,
        )


def test_real_scoped_evidence_authority_rejects_scope_stale_and_integrity():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    scope_metadata = {
        "evidence_scope_contract_id": DIRECT_CONTRACT,
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "store-a",
        "reviewed_by": "reviewer-1",
    }
    current = evidence.capture(
        content=b"immutable carrier rate card",
        filename="rate-card.txt",
        content_type="text/plain",
        source="carrier_rate_card",
        source_ref="carrier://exact-scope/current",
        grade=EvidenceGrade.B,
        effective_at="2026-07-20T00:00:00+00:00",
        effective_until="2026-08-20T00:00:00+00:00",
        created_by="operator-1",
        metadata=scope_metadata,
    )
    stale = evidence.capture(
        content=b"expired carrier rate card",
        filename="expired-rate-card.txt",
        content_type="text/plain",
        source="carrier_rate_card",
        source_ref="carrier://exact-scope/expired",
        grade=EvidenceGrade.B,
        effective_at="2026-07-01T00:00:00+00:00",
        effective_until="2026-07-25T00:00:00+00:00",
        created_by="operator-1",
        metadata=scope_metadata,
    )
    service = LogisticsQuoteWorkspace(
        InMemoryLogisticsStore(),
        evidence_validator=evidence.require_valid,
        evidence_resolver=evidence.get,
        fx_evidence_current_validator=evidence.require_current,
        scoped_evidence=ScopedEvidenceAuthority(evidence=evidence),
    )
    context_a = scope_context(service)
    card = service.capture_rate_card(
        context_a,
        rate_card(evidence_id=current.id),
    )
    context_b = scope_context(
        service,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        authority="b" * 64,
    )
    with pytest.raises(ValueError, match="current, intact, and bound"):
        service.capture_rate_card(
            context_b,
            rate_card(evidence_id=current.id, route_code="WRONG-SCOPE"),
        )
    with pytest.raises(ValueError, match="current, intact, and bound"):
        service.capture_rate_card(
            context_a,
            rate_card(evidence_id=stale.id, route_code="STALE"),
        )

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE evidence_blobs SET content_bytes=:content "
                "WHERE sha256=:sha256"
            ),
            {"content": b"tampered carrier rate card", "sha256": current.sha256},
        )
    with pytest.raises(ValueError, match="hash verification"):
        service.get_rate_card(context_a, card.id)


def test_sqlite_adapter_enforces_exact_scope_and_composite_rate_card_fk():
    engine, sql_store = sqlite_logistics_store()
    service, _, _, context_a, scoped_evidence = workspace(sql_store)
    context_b = scope_context(
        service,
        tenant_ref="tenant-b",
        entity_ref="entity-b",
        store_ref="store-b",
        authority="b" * 64,
    )
    scoped_evidence.allowed_scopes["evd-rate-card-1"].add(
        ("tenant-b", "entity-b", "store-b")
    )
    card_a = service.capture_rate_card(context_a, rate_card())
    card_b = service.capture_rate_card(context_b, rate_card())
    assert card_a.rate_card_hash == card_b.rate_card_hash
    assert [item.id for item in service.list_rate_cards(context_a)] == [card_a.id]
    assert [item.id for item in service.list_rate_cards(context_b)] == [card_b.id]

    calculation_a = service.calculate(
        context_a,
        rate_card_id=card_a.id,
        physical_weight_kg=Decimal("1"),
        length_cm=Decimal("10"),
        width_cm=Decimal("10"),
        height_cm=Decimal("10"),
        declared_value=Decimal("1000"),
        quantity=1,
        currency_to_cny_rate=Decimal("1"),
        idempotency_key="sqlite-key",
        calculated_by="operator-1",
        evaluated_at="2026-07-26T00:00:00+00:00",
    )
    assert service.get_calculation(context_a, calculation_a.id).state == "estimate"
    with pytest.raises(KeyError, match="Unknown logistics calculation"):
        service.get_calculation(context_b, calculation_a.id)
    with pytest.raises(ValueError, match="different inputs"):
        service.calculate(
            context_a,
            rate_card_id=card_a.id,
            physical_weight_kg=Decimal("1"),
            length_cm=Decimal("11"),
            width_cm=Decimal("10"),
            height_cm=Decimal("10"),
            declared_value=Decimal("1000"),
            quantity=1,
            currency_to_cny_rate=Decimal("1"),
            idempotency_key="sqlite-key",
            calculated_by="operator-1",
            evaluated_at="2026-07-26T00:00:00+00:00",
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE logistics_calculations SET tenant_ref='tenant-b' "
                "WHERE id=:id"
            ),
            {"id": calculation_a.id},
        )

    legacy_card = service.capture_rate_card(
        context_a,
        rate_card(route_code="LEGACY-AUDIT"),
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE logistics_rate_cards SET scope_status='legacy_unbound', "
                "tenant_ref=NULL, entity_ref=NULL, store_ref=NULL, "
                "scope_grant_authority_sha256=NULL, scope_as_of=NULL "
                "WHERE id=:id"
            ),
            {"id": legacy_card.id},
        )
    with pytest.raises(KeyError, match="Unknown logistics rate card"):
        service.get_rate_card(context_a, legacy_card.id)
    with engine.connect() as connection:
        retained = connection.execute(
            text(
                "SELECT count(*) FROM logistics_rate_cards "
                "WHERE id=:id AND scope_status='legacy_unbound'"
            ),
            {"id": legacy_card.id},
        ).scalar_one()
    assert retained == 1
