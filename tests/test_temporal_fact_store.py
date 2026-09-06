from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from apps.control_plane.data_fabric_contracts import ScopeRef
from apps.control_plane.temporal_fact_store import (
    FactNotFoundError,
    QualityState,
    RevisionConflictError,
    TemporalFactRevision,
    TemporalFactStore,
    TemporalFactTimes,
)

T0 = datetime(2026, 9, 1, 8, tzinfo=UTC)


def scope(tenant: str = "tenant-a") -> ScopeRef:
    return ScopeRef(tenant_id=tenant, entity_id="entity-a", store_ids=("store-a",))


def fact_values(**overrides):
    values = {
        "fact_id": "fact-order-1",
        "fact_type": "order",
        "natural_key": "order-1",
        "payload": {"amount": 0, "currency": "RUB"},
        "scope": scope(),
        "event_time": T0,
        "observed_time": T0 + timedelta(hours=1),
        "effective_time": T0,
        "source_system": "ozon-export",
        "source_record_id": "order-1",
        "idempotency_key": "import-1",
        "lineage": [{"kind": "evidence", "id": "ev-order-1", "sha256": "a" * 64}],
    }
    values.update(overrides)
    return values


def test_four_times_are_required_aware_and_normalized_to_utc() -> None:
    times = TemporalFactTimes(
        event_time="2026-09-01T10:00:00+02:00",
        observed_time="2026-09-01T11:00:00+02:00",
        effective_time="2026-09-01T10:00:00+02:00",
    )

    assert times.event_time == datetime(2026, 9, 1, 8, tzinfo=UTC)
    assert times.observed_time == datetime(2026, 9, 1, 9, tzinfo=UTC)

    with pytest.raises(ValueError, match="timezone"):
        TemporalFactTimes(
            event_time=datetime(2026, 9, 1, 8),
            observed_time=T0,
            effective_time=T0,
        )
    with pytest.raises(ValueError, match="after observed_time"):
        TemporalFactTimes(
            event_time=T0 + timedelta(hours=2),
            observed_time=T0 + timedelta(hours=1),
            effective_time=T0,
        )


def test_effective_time_may_be_scheduled_and_late_freshness_is_preserved() -> None:
    times = TemporalFactTimes(
        event_time=T0,
        observed_time=T0 + timedelta(hours=1),
        effective_time=T0 + timedelta(days=1),
        settled_time=T0 + timedelta(hours=2),
    )
    assert times.effective_time == T0 + timedelta(days=1)

    # A late import can arrive after its freshness horizon.  It remains a
    # valid immutable source revision whose read projection can become STALE.
    fact = TemporalFactRevision.model_validate(
        fact_values(
            fresh_until=T0 - timedelta(minutes=1),
            effective_time=T0 + timedelta(days=1),
            settled_time=T0 + timedelta(hours=2),
        )
    )
    assert fact.fresh_until == T0 - timedelta(minutes=1)

    with pytest.raises(ValidationError, match="settled_time cannot precede event_time"):
        TemporalFactTimes(
            event_time=T0,
            observed_time=T0 + timedelta(hours=1),
            effective_time=T0,
            settled_time=T0 - timedelta(minutes=1),
        )


def test_append_restate_and_as_of_preserve_historical_truth() -> None:
    store = TemporalFactStore()
    first = store.append(fact_values())
    corrected = store.restate(
        first.fact_id,
        {"amount": 5, "currency": "RUB"},
        correction_reason="late settlement correction",
        observed_time=T0 + timedelta(hours=3),
        idempotency_key="correction-1",
        lineage=[{"kind": "evidence", "id": "ev-correction", "sha256": "b" * 64}],
    )

    assert first.revision == 1
    assert corrected.revision == 2
    assert corrected.supersedes_revision == 1
    assert store.get(first.fact_id, revision=1).payload["amount"] == 0
    assert store.as_of(T0 + timedelta(hours=2))[0].payload["amount"] == 0
    assert store.as_of(T0 + timedelta(hours=4))[0].payload["amount"] == 5
    assert store.get_as_of(first.fact_id, as_of=T0 + timedelta(hours=2)).revision == 1
    assert store.get_as_of(first.fact_id, as_of=T0 + timedelta(hours=4)).revision == 2
    assert len(store.history(first.fact_id)) == 2


def test_source_correction_keeps_the_same_canonical_identity() -> None:
    store = TemporalFactStore()
    first = store.append(fact_values())
    corrected = store.append(
        fact_values(
            source_system="ozon-api",
            source_record_id="ozon-api-order-1",
            idempotency_key="import-api-1",
            payload={"amount": 7, "currency": "RUB"},
            observed_time=T0 + timedelta(hours=2),
            revision=2,
            revision_reason="platform correction",
        )
    )

    assert corrected.fact_id == first.fact_id
    assert corrected.revision == 2
    assert len(store.history(first.fact_id)) == 2


def test_idempotency_is_exact_and_conflicting_reuse_fails_closed() -> None:
    store = TemporalFactStore()
    first = store.append(fact_values())
    replay = store.append(fact_values())

    assert replay.revision_id == first.revision_id
    assert len(store.history(first.fact_id)) == 1

    with pytest.raises(RevisionConflictError, match="idempotency key"):
        store.append(fact_values(payload={"amount": 9, "currency": "RUB"}))


def test_quality_state_does_not_turn_zero_into_no_data() -> None:
    valid = TemporalFactRevision.model_validate(fact_values())
    assert valid.payload["amount"] == 0
    assert valid.quality_state is QualityState.VALID

    with pytest.raises(ValidationError, match="NO_DATA"):
        TemporalFactRevision.model_validate(fact_values(quality_state="NO_DATA", payload={"amount": 0}))


def test_as_of_is_scope_bound_and_late_events_can_be_filtered() -> None:
    store = TemporalFactStore()
    store.append(fact_values())
    store.append(
        fact_values(
            fact_id="fact-order-2",
            natural_key="order-2",
            source_record_id="order-2",
            idempotency_key="import-2",
            event_time=T0 + timedelta(days=2),
            observed_time=T0 + timedelta(days=2, hours=1),
        )
    )
    store.append(
        fact_values(
            fact_id="fact-other-tenant",
            natural_key="order-other",
            source_record_id="order-other",
            idempotency_key="import-other",
            scope=scope("tenant-b"),
        )
    )

    assert len(store.as_of(T0 + timedelta(hours=2), scope=scope())) == 1
    assert len(store.as_of(T0 + timedelta(days=3), scope=scope())) == 2
    assert (
        len(
            store.as_of(
                T0 + timedelta(days=3),
                scope=scope(),
                event_start=T0 + timedelta(days=1),
            )
        )
        == 1
    )
    assert store.as_of(T0 + timedelta(days=3), scope=scope("tenant-b"))[0].natural_key == "order-other"


def test_as_of_projects_expired_freshness_as_stale_without_mutating_history() -> None:
    store = TemporalFactStore()
    first = store.append(fact_values(fresh_until=T0 + timedelta(hours=2)))

    current = store.get(first.fact_id)
    projected = store.get_as_of(first.fact_id, as_of=T0 + timedelta(hours=3))

    assert current.quality_state is QualityState.VALID
    assert projected.quality_state is QualityState.STALE
    assert store.get(first.fact_id).quality_state is QualityState.VALID


def test_missing_fact_and_empty_correction_reason_are_rejected() -> None:
    store = TemporalFactStore()
    with pytest.raises(FactNotFoundError):
        store.get("missing")
    first = store.append(fact_values())
    with pytest.raises(ValueError, match="correction_reason"):
        store.restate(first.fact_id, {"amount": 1}, correction_reason=" ")


def test_empty_query_envelope_is_explicit_no_data_with_zero_completeness() -> None:
    query = TemporalFactStore().query_as_of(T0)
    envelope = query.to_data_envelope(
        dataset="orders.v1",
        scope=scope(),
    )
    assert query.quality_state is QualityState.NO_DATA
    assert envelope.status == "no_data"
    assert envelope.quality.completeness == 0


def test_lineage_edge_ids_are_stable_across_reads() -> None:
    store = TemporalFactStore()
    store.append(fact_values())
    first = store.lineage_edges("fact-order-1")[0].id
    second = store.lineage_edges("fact-order-1")[0].id
    assert first == second
