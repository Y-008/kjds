from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine

from apps.control_plane.sql_repository import Base
from apps.control_plane.temporal_fact_sql import SqlTemporalFactStore, TemporalFactRow
from apps.control_plane.temporal_fact_store import (
    QualityState,
    RevisionConflictError,
    ScopeRef,
    TemporalFactRevision,
)


def _fact(
    *,
    revision: int = 1,
    observed: datetime | None = None,
    fact_id: str = "f-1",
    idempotency_key: str = "",
) -> TemporalFactRevision:
    observed = observed or datetime(2026, 9, 1, tzinfo=UTC)
    return TemporalFactRevision(
        fact_id=fact_id,
        revision_id=f"r-{revision}",
        revision=revision,
        fact_type="order",
        natural_key="o-1",
        scope=ScopeRef(tenant_id="t1", entity_id="e1", store_ids=("s1",)),
        payload={"amount": revision},
        event_time=observed - timedelta(minutes=1),
        observed_time=observed,
        effective_time=observed,
        source_system="test",
        source_record_id="o-1",
        idempotency_key=idempotency_key,
    )


def test_sql_adapter_preserves_revisions_and_as_of():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TemporalFactRow.__table__])
    store = SqlTemporalFactStore(engine)
    first = store.append(_fact())
    store.append(_fact(revision=2, observed=datetime(2026, 9, 2, tzinfo=UTC)))
    assert store.get(first.fact_id).revision == 2
    assert len(store.history(first.fact_id)) == 2
    assert store.as_of(datetime(2026, 9, 1, 12, tzinfo=UTC))[0].payload["amount"] == 1


def test_sql_restate_is_a_new_immutable_revision():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TemporalFactRow.__table__])
    store = SqlTemporalFactStore(engine)
    first = store.append(_fact())
    corrected = store.restate(first.fact_id, {"amount": 99}, correction_reason="platform correction")
    assert corrected.revision == 2
    assert store.get(first.fact_id, revision=1).payload["amount"] == 1
    assert corrected.payload["amount"] == 99


def test_sql_append_reassigns_revision_id_when_first_revision_object_is_reused():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TemporalFactRow.__table__])
    store = SqlTemporalFactStore(engine)
    first_input = _fact()
    first = store.append(first_input)
    reused = first_input.model_copy(
        update={
            "payload": {"amount": 7},
            "payload_hash": None,
            "observed_time": datetime(2026, 9, 1, 1, tzinfo=UTC),
        },
        deep=True,
    )
    corrected = store.append(reused)
    assert corrected.revision == 2
    assert corrected.revision_id != first.revision_id
    assert store.get(first.fact_id, revision=1).revision_id == first.revision_id


def test_sql_as_of_requires_exact_store_and_warehouse_scope():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TemporalFactRow.__table__])
    store = SqlTemporalFactStore(engine)
    first = _fact()
    second = _fact(
        fact_id="f-2",
        observed=datetime(2026, 9, 1, 1, tzinfo=UTC),
    ).model_copy(
        update={
            "revision_id": "r-2",
            "natural_key": "o-2",
            "source_record_id": "o-2",
            "scope": ScopeRef(
                tenant_id="t1",
                entity_id="e1",
                store_ids=("s2",),
                warehouse_ids=("w2",),
            ),
        },
        deep=True,
    )
    store.append(first)
    store.append(second)

    requested = ScopeRef(tenant_id="t1", entity_id="e1", store_ids=("s1",))
    assert [item.fact_id for item in store.as_of(datetime(2026, 9, 2, tzinfo=UTC), scope=requested)] == ["f-1"]


def test_sql_idempotency_compares_full_request_fingerprint():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TemporalFactRow.__table__])
    store = SqlTemporalFactStore(engine)
    store.append(_fact(idempotency_key="import-1"))

    conflicting_values = _fact().model_dump(mode="python")
    conflicting_values.update(
        {
            "payload": {"amount": 1},
            "metadata": {"source_revision": "changed"},
            "payload_hash": None,
            "idempotency_key": "import-1",
        }
    )
    conflicting = TemporalFactRevision.model_validate(conflicting_values)
    with pytest.raises(RevisionConflictError, match="idempotency key"):
        store.append(conflicting)


def test_sql_as_of_projects_stale_and_can_exclude_it_without_mutation():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[TemporalFactRow.__table__])
    store = SqlTemporalFactStore(engine)
    first = _fact().model_copy(
        update={"fresh_until": datetime(2026, 9, 1, 0, 30, tzinfo=UTC)},
        deep=True,
    )
    # The fixture's observed time is exactly 00:00 UTC.
    store.append(first)
    cutoff = datetime(2026, 9, 1, 1, tzinfo=UTC)
    assert store.as_of(cutoff)[0].quality_state is QualityState.STALE
    assert store.as_of(cutoff, include_stale=False) == ()
    assert store.get(first.fact_id).quality_state is QualityState.VALID
