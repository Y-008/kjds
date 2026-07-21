from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from apps.control_plane.database import create_database_engine, database_url
from apps.control_plane.outbox import OutboxService
from apps.control_plane.services import CommerceService
from apps.control_plane.sql_repository import EventRow, ProductRow, SqlAlchemyRepository

EXPECTED_DATABASE = "kjds_g1_smoke"


def main() -> None:
    url = database_url()
    if make_url(url).database != EXPECTED_DATABASE:
        raise RuntimeError(f"Outbox verification requires disposable database {EXPECTED_DATABASE!r}")

    engine = create_database_engine(url)
    repository = SqlAlchemyRepository(engine)
    commerce = CommerceService(repository, lambda _evidence: None)
    outbox = OutboxService(engine)

    rollback_sku = f"G1-OUTBOX-ROLLBACK-{uuid4().hex}"
    original_append = repository.append_event

    def fail_event(*_args, **_kwargs) -> None:
        raise RuntimeError("simulated outbox insert failure")

    repository.append_event = fail_event  # type: ignore[method-assign]
    try:
        try:
            commerce.create_product(sku=rollback_sku, name="must roll back")
        except RuntimeError as exc:
            if "simulated outbox insert failure" not in str(exc):
                raise
        else:
            raise AssertionError("Atomic rollback fault was not raised")
    finally:
        repository.append_event = original_append  # type: ignore[method-assign]

    with Session(engine) as session:
        leaked = session.scalar(select(func.count()).select_from(ProductRow).where(ProductRow.sku == rollback_sku))
        if leaked:
            raise AssertionError("Business row survived a failed outbox insert")

    product = commerce.create_product(
        sku=f"G1-OUTBOX-{uuid4().hex}",
        name="transactional outbox concurrency probe",
    )
    with Session(engine) as session:
        target = session.scalar(select(EventRow).where(EventRow.aggregate_id == product.id))
        if target is None:
            raise AssertionError("Committed business row has no outbox event")
        target_sequence = target.sequence
        target_event_id = target.event_id

    barrier = Barrier(2)

    def claim(worker_id: str):
        barrier.wait()
        return outbox.claim_batch(worker_id=worker_id, limit=1, lease_seconds=2)

    with ThreadPoolExecutor(max_workers=2) as pool:
        batches = list(pool.map(claim, ("g1-outbox-a", "g1-outbox-b")))

    claimed = [event for batch in batches for event in batch if event.sequence == target_sequence]
    if len(claimed) != 1:
        raise AssertionError(f"Expected one exclusive claim, got {len(claimed)}")

    recovery_at = datetime.now(UTC) + timedelta(seconds=3)
    recovered = outbox.claim_batch(
        worker_id="g1-outbox-recovery",
        limit=100,
        lease_seconds=30,
        as_of=recovery_at,
    )
    recovered_target = next((event for event in recovered if event.sequence == target_sequence), None)
    if recovered_target is None or recovered_target.event_id != target_event_id:
        raise AssertionError("Expired outbox lease was not recovered with the stable event ID")
    if recovered_target.attempt_count != 2:
        raise AssertionError("Recovered outbox event did not preserve its delivery attempt count")

    delivered: list[str] = []
    outbox.mark_failed(
        sequence=target_sequence,
        worker_id="g1-outbox-recovery",
        error="synthetic downstream outage",
        retry_after_seconds=0,
        failed_at=recovery_at,
    )
    result = outbox.publish_batch(
        worker_id="g1-outbox-publisher",
        deliver=lambda event: delivered.append(event["event_id"]),
        limit=100,
        as_of=recovery_at,
    )
    if target_event_id not in result["published"] or delivered.count(target_event_id) != 1:
        raise AssertionError("Recovered outbox event was not published exactly once in this delivery attempt")

    print(
        json.dumps(
            {
                "status": "PASS",
                "atomic_rollback": True,
                "exclusive_claim": True,
                "lease_recovery": True,
                "stable_event_id": target_event_id,
                "attempt_count": 3,
                "delivery_semantics": "at-least-once; sink deduplicates by event_id",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
