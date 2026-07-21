from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .sql_repository import EventRow


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    sequence: int
    event_id: str
    event_type: str
    aggregate_id: str
    payload: dict[str, Any]
    payload_hash: str
    occurred_at: str
    recorded_at: str
    actor_id: str
    source_evidence_id: str | None
    schema_version: str
    attempt_count: int


class OutboxService:
    def __init__(self, engine) -> None:
        self.engine = engine

    def claim_batch(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        lease_seconds: int = 60,
        as_of: datetime | None = None,
    ) -> list[OutboxEvent]:
        worker_id = worker_id.strip()
        if not worker_id:
            raise ValueError("Outbox worker_id is required")
        if limit < 1 or limit > 100:
            raise ValueError("Outbox claim limit must be between 1 and 100")
        if lease_seconds < 1 or lease_seconds > 900:
            raise ValueError("Outbox lease must be between 1 and 900 seconds")
        now = self._utc(as_of)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            rows = session.scalars(
                select(EventRow)
                .where(
                    EventRow.published_at.is_(None),
                    EventRow.available_at <= now,
                    or_(EventRow.claimed_until.is_(None), EventRow.claimed_until <= now),
                )
                .order_by(EventRow.sequence)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for row in rows:
                row.claimed_by = worker_id
                row.claimed_until = now + timedelta(seconds=lease_seconds)
                row.attempt_count += 1
            session.flush()
            return [self._event(row) for row in rows]

    def mark_published(
        self, *, sequence: int, worker_id: str, published_at: datetime | None = None
    ) -> OutboxEvent:
        now = self._utc(published_at)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            row = session.scalar(select(EventRow).where(EventRow.sequence == sequence).with_for_update())
            if row is None:
                raise KeyError(f"Unknown outbox sequence: {sequence}")
            if row.published_at is not None:
                return self._event(row)
            self._require_claim(row, worker_id)
            row.published_at = now
            row.claimed_by = None
            row.claimed_until = None
            row.last_error = None
            session.flush()
            return self._event(row)

    def mark_failed(
        self,
        *,
        sequence: int,
        worker_id: str,
        error: str,
        retry_after_seconds: int,
        failed_at: datetime | None = None,
    ) -> OutboxEvent:
        if retry_after_seconds < 0 or retry_after_seconds > 3600:
            raise ValueError("Outbox retry delay must be between 0 and 3600 seconds")
        now = self._utc(failed_at)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            row = session.scalar(select(EventRow).where(EventRow.sequence == sequence).with_for_update())
            if row is None:
                raise KeyError(f"Unknown outbox sequence: {sequence}")
            if row.published_at is not None:
                raise ValueError("Published outbox events cannot be failed or replayed")
            self._require_claim(row, worker_id)
            row.last_error = self._safe_error(error)
            row.available_at = now + timedelta(seconds=retry_after_seconds)
            row.claimed_by = None
            row.claimed_until = None
            session.flush()
            return self._event(row)

    def publish_batch(
        self,
        *,
        worker_id: str,
        deliver: Callable[[dict[str, Any]], None],
        limit: int = 50,
        lease_seconds: int = 60,
        as_of: datetime | None = None,
    ) -> dict[str, Any]:
        events = self.claim_batch(
            worker_id=worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
            as_of=as_of,
        )
        published: list[str] = []
        failed: list[str] = []
        now = self._utc(as_of)
        for event in events:
            try:
                deliver(asdict(event))
            except Exception as exc:
                delay = min(300, 2 ** min(event.attempt_count, 8))
                self.mark_failed(
                    sequence=event.sequence,
                    worker_id=worker_id,
                    error=str(exc),
                    retry_after_seconds=delay,
                    failed_at=now,
                )
                failed.append(event.event_id)
            else:
                self.mark_published(sequence=event.sequence, worker_id=worker_id, published_at=now)
                published.append(event.event_id)
        return {"claimed": len(events), "published": published, "failed": failed}

    def status(self, *, as_of: datetime | None = None) -> dict[str, int]:
        now = self._utc(as_of)
        with Session(self.engine) as session:
            total = int(session.scalar(select(func.count()).select_from(EventRow)) or 0)
            published = int(
                session.scalar(select(func.count()).select_from(EventRow).where(EventRow.published_at.is_not(None)))
                or 0
            )
            ready = int(
                session.scalar(
                    select(func.count())
                    .select_from(EventRow)
                    .where(
                        EventRow.published_at.is_(None),
                        EventRow.available_at <= now,
                        or_(EventRow.claimed_until.is_(None), EventRow.claimed_until <= now),
                    )
                )
                or 0
            )
            claimed = int(
                session.scalar(
                    select(func.count())
                    .select_from(EventRow)
                    .where(EventRow.published_at.is_(None), EventRow.claimed_until > now)
                )
                or 0
            )
            failed_waiting = int(
                session.scalar(
                    select(func.count())
                    .select_from(EventRow)
                    .where(
                        EventRow.published_at.is_(None),
                        EventRow.last_error.is_not(None),
                        EventRow.available_at > now,
                    )
                )
                or 0
            )
        return {
            "total": total,
            "published": published,
            "ready": ready,
            "claimed": claimed,
            "failed_waiting": failed_waiting,
        }

    @staticmethod
    def payload_valid(event: OutboxEvent) -> bool:
        encoded = json.dumps(
            event.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
        return hashlib.sha256(encoded).hexdigest() == event.payload_hash

    @staticmethod
    def _require_claim(row: EventRow, worker_id: str) -> None:
        if row.claimed_by != worker_id:
            raise PermissionError("Outbox event is not claimed by this worker")

    @staticmethod
    def _safe_error(error: str) -> str:
        value = " ".join(error.replace("\r", " ").replace("\n", " ").split())
        return (value or "delivery failed")[:1000]

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        if value.tzinfo is None:
            raise ValueError("Outbox timestamps must include a timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _event(row: EventRow) -> OutboxEvent:
        return OutboxEvent(
            row.sequence,
            row.event_id,
            row.event_type,
            row.aggregate_id,
            row.payload_json,
            row.payload_hash,
            row.occurred_at.isoformat(),
            row.recorded_at.isoformat(),
            row.actor_id,
            row.source_evidence_id,
            row.schema_version,
            row.attempt_count,
        )
