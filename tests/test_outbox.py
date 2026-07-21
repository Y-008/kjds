from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.outbox import OutboxService
from apps.control_plane.services import CommerceService
from apps.control_plane.sql_repository import Base, SqlAlchemyRepository


def make_services():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    repository = SqlAlchemyRepository(engine)
    return repository, CommerceService(repository, lambda _: None), OutboxService(engine)


def test_business_write_and_event_commit_or_rollback_together(monkeypatch):
    repository, commerce, _ = make_services()
    created = commerce.create_product(sku="atomic-1", name="Atomic")
    assert repository.get_product(created.id).sku == "atomic-1"
    assert repository.event_count() == 1

    def fail_event(*_args, **_kwargs):
        raise RuntimeError("simulated outbox insert failure")

    monkeypatch.setattr(repository, "append_event", fail_event)
    with pytest.raises(RuntimeError, match="outbox insert failure"):
        commerce.create_product(sku="atomic-rollback", name="Must roll back")
    assert [item.sku for item in repository.list_products()] == ["atomic-1"]
    assert repository.event_count() == 1


def test_claim_is_exclusive_and_expired_lease_is_recoverable():
    _, commerce, outbox = make_services()
    commerce.create_product(sku="lease-1", name="Lease")
    now = datetime.now(UTC) + timedelta(seconds=1)

    first = outbox.claim_batch(worker_id="worker-1", lease_seconds=10, as_of=now)
    assert len(first) == 1
    assert outbox.payload_valid(first[0]) is True
    assert outbox.claim_batch(worker_id="worker-2", as_of=now) == []

    recovered = outbox.claim_batch(worker_id="worker-2", as_of=now + timedelta(seconds=11))
    assert [event.event_id for event in recovered] == [first[0].event_id]
    assert recovered[0].attempt_count == 2


def test_failed_delivery_is_retried_and_published_once_marked():
    _, commerce, outbox = make_services()
    commerce.create_product(sku="retry-1", name="Retry")
    now = datetime.now(UTC) + timedelta(seconds=1)

    def fail(_event):
        raise RuntimeError("sink offline\nsecret omitted")

    failed = outbox.publish_batch(worker_id="publisher", as_of=now, deliver=fail)
    assert failed["claimed"] == 1
    assert len(failed["failed"]) == 1
    assert outbox.status(as_of=now)["failed_waiting"] == 1

    delivered = []
    retried = outbox.publish_batch(
        worker_id="publisher-restarted",
        as_of=now + timedelta(seconds=3),
        deliver=delivered.append,
    )
    assert retried["published"] == failed["failed"]
    assert delivered[0]["attempt_count"] == 2
    assert outbox.status(as_of=now + timedelta(seconds=3)) == {
        "total": 1,
        "published": 1,
        "ready": 0,
        "claimed": 0,
        "failed_waiting": 0,
    }


def test_published_event_cannot_be_requeued_as_failed():
    _, commerce, outbox = make_services()
    commerce.create_product(sku="immutable-1", name="Immutable")
    event = outbox.claim_batch(worker_id="publisher")[0]
    outbox.mark_published(sequence=event.sequence, worker_id="publisher")

    with pytest.raises(ValueError, match="Published outbox events"):
        outbox.mark_failed(
            sequence=event.sequence,
            worker_id="publisher",
            error="late failure",
            retry_after_seconds=0,
        )
