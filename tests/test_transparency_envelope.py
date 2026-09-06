from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.control_plane.data_fabric_contracts import DataEnvelope, QualitySummary, ScopeRef
from apps.control_plane.temporal_fact_store import QualityState, TemporalFactStore
from apps.control_plane.transparency_envelope import (
    LineageEdge,
    LineageRef,
    TransparencyEnvelope,
    TransparencyQuality,
)

T0 = datetime(2026, 9, 1, 8, tzinfo=UTC)
SCOPE = ScopeRef(tenant_id="tenant-a", entity_id="entity-a", store_ids=("store-a",))


def test_transparency_envelope_keeps_zero_values_and_exposes_lineage() -> None:
    envelope = TransparencyEnvelope(
        dataset="orders.v1",
        scope=SCOPE,
        as_of=T0,
        status="ready",
        data=({"sku": "SKU-1", "quantity": 0},),
        lineage=(LineageRef(kind="evidence", id="ev-1", sha256="a" * 64),),
        formula_version="cm3/1.0",
        rule_version="rules/1.0",
        source_watermarks={"ozon": "2026-09-01T08:00:00Z"},
    )

    assert envelope.quality_status is QualityState.VALID
    assert envelope.data[0]["quantity"] == 0
    assert envelope.drilldown()[0]["id"] == "ev-1"
    assert len(envelope.content_hash) == 64
    transport = envelope.to_data_envelope()
    assert isinstance(transport, DataEnvelope)
    assert transport.data[0]["quantity"] == 0


def test_transparency_round_trip_preserves_data_contract_state() -> None:
    source = DataEnvelope(
        dataset="orders.v1",
        scope=SCOPE,
        as_of=T0,
        fresh_until=T0 + timedelta(hours=1),
        status="partial",
        data=({"order_id": "o1"},),
        quality=QualitySummary(
            completeness=0.5,
            freshness="fresh",
            excluded_count=1,
            reasons=("late_page",),
        ),
        lineage=({"kind": "evidence", "id": "ev-1", "sha256": "a" * 64},),
        schema_version="1.0",
        authority_hash="authority-1",
    )
    transparent = TransparencyEnvelope.from_data_envelope(source, formula_version="f/1")
    restored = transparent.to_data_envelope()

    assert transparent.quality_status is QualityState.PARTIAL
    assert transparent.formula_version == "f/1"
    assert restored.status == source.status
    assert restored.data == source.data
    assert restored.quality.completeness == source.quality.completeness


def test_transparency_accepts_compact_quality_summary_input() -> None:
    envelope = TransparencyEnvelope(
        dataset="orders.v1",
        scope=SCOPE,
        as_of=T0,
        status="partial",
        data=({"order_id": "o1"},),
        quality=QualitySummary(
            completeness=0.5,
            freshness="unknown",
            excluded_count=1,
            reasons=("late_page",),
        ),
    )

    assert envelope.quality_state is QualityState.PARTIAL
    assert envelope.quality.completeness == 0.5


@pytest.mark.parametrize(
    ("status", "quality_state"),
    [("blocked", "BLOCKED"), ("unknown_outcome", "UNKNOWN_OUTCOME"), ("no_data", "NO_DATA")],
)
def test_terminal_quality_states_are_fail_closed(status: str, quality_state: str) -> None:
    envelope = TransparencyEnvelope(
        dataset="orders.v1",
        scope=SCOPE,
        as_of=T0,
        status=status,
        quality_state=quality_state,
    )
    assert envelope.data == ()
    assert envelope.to_data_envelope().data == ()

    with pytest.raises(ValidationError, match="cannot contain data rows"):
        TransparencyEnvelope(
            dataset="orders.v1",
            scope=SCOPE,
            as_of=T0,
            status=status,
            quality_state=quality_state,
            data=({"amount": 0},),
        )


def test_status_quality_and_freshness_cannot_disagree() -> None:
    with pytest.raises(ValidationError, match="disagree"):
        TransparencyEnvelope(
            dataset="orders.v1",
            scope=SCOPE,
            as_of=T0,
            status="ready",
            quality_state="STALE",
        )
    with pytest.raises(ValidationError, match="fresh_until"):
        TransparencyEnvelope(
            dataset="orders.v1",
            scope=SCOPE,
            as_of=T0,
            fresh_until=T0 - timedelta(seconds=1),
            status="ready",
        )


def test_query_result_can_be_projected_to_transparency_envelope() -> None:
    store = TemporalFactStore()
    store.append(
        fact_id="fact-1",
        fact_type="inventory",
        natural_key="sku-1",
        payload={"available": 0},
        scope=SCOPE,
        event_time=T0,
        observed_time=T0 + timedelta(minutes=1),
        effective_time=T0,
        source_system="ozon",
        source_record_id="sku-1",
        idempotency_key="inventory-1",
        lineage=[{"kind": "evidence", "id": "ev-inventory", "sha256": "b" * 64}],
    )
    result = store.query_as_of(T0 + timedelta(hours=1))
    envelope = TransparencyEnvelope.from_query_result(
        result,
        dataset="inventory.v1",
        scope=SCOPE,
    )

    assert envelope.status == "ready"
    assert envelope.data[0]["available"] == 0
    assert envelope.lineage[0].id == "ev-inventory"


def test_lineage_edge_rejects_self_reference_and_invalid_hash() -> None:
    with pytest.raises(ValidationError):
        LineageEdge(
            from_type="fact",
            from_id="f1",
            to_type="fact",
            to_id="f1",
            relationship="supports",
        )
    with pytest.raises(ValidationError):
        LineageEdge(
            from_type="evidence",
            from_id="e1",
            to_type="fact",
            to_id="f1",
            relationship="supports",
            from_sha256="bad",
        )


def test_transparency_quality_has_explicit_dimensions() -> None:
    quality = TransparencyQuality(
        state="PARTIAL",
        completeness=0.8,
        freshness="unknown",
        validity=0.9,
        uniqueness=1,
        referential_integrity=0.95,
        cross_source_consistency=0.7,
        reconciliation=0.8,
        lineage_coverage=0.6,
        excluded_count=2,
        reasons=("missing_settlement",),
    )
    assert quality.to_quality_summary().completeness == 0.8
