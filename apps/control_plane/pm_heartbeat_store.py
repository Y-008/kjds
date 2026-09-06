"""Append-only persistence for autonomous project-manager heartbeats."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sql_repository import Base


class ProjectHeartbeatRow(Base):
    __tablename__ = "project_manager_heartbeats"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "revision",
            name="uq_pm_heartbeat_scope_revision",
        ),
        UniqueConstraint(
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "idempotency_key",
            name="uq_pm_heartbeat_scope_idempotency",
        ),
        CheckConstraint("revision >= 1", name="ck_pm_heartbeat_revision_positive"),
        Index("ix_pm_heartbeat_scope_revision", "tenant_id", "entity_id", "project_id", "revision"),
        Index("ix_pm_heartbeat_observed", "tenant_id", "entity_id", "observed_at"),
    )

    heartbeat_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    head: Mapped[str] = mapped_column(String(200), nullable=False)
    graph_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Explicit idempotency and liveness columns make the watchdog queryable
    # without parsing the opaque payload.  They are duplicated in the payload
    # hash so an old snapshot can be replayed byte-for-byte.
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    liveness_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    progress_cursor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expected_next_event: Mapped[str | None] = mapped_column(String(300), nullable=True)
    stuck_detector_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    compensation_action: Mapped[str | None] = mapped_column(String(300), nullable=True)
    recovery_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)


class ProjectHeartbeatConflict(ValueError):
    """A heartbeat request cannot be reconciled with the durable winner."""

    http_status_code = 409

    @property
    def http_detail(self) -> dict[str, str]:
        return {"code": "heartbeat_conflict", "message": str(self)}


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _text(value: str | None, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _request_payload(
    *,
    project_id: str,
    tenant_id: str,
    entity_id: str,
    store_ref: str,
    head: str,
    graph_snapshot_sha256: str,
    status: str,
    payload: Mapping[str, Any],
    observed_at: datetime,
    liveness_deadline: datetime | None,
    heartbeat_at: datetime | None,
    progress_cursor: str | None,
    expected_next_event: str | None,
    stuck_detector_version: str | None,
    compensation_action: str | None,
    recovery_ref: str | None,
) -> dict[str, Any]:
    """Return the immutable request identity used by idempotent writes."""

    return {
        "project_id": project_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "store_ref": store_ref,
        "head": head,
        "graph_snapshot_sha256": graph_snapshot_sha256,
        "status": status,
        "payload": dict(payload),
        "observed_at": observed_at.isoformat(),
        "liveness_deadline": liveness_deadline.isoformat() if liveness_deadline else None,
        "heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
        "progress_cursor": progress_cursor,
        "expected_next_event": expected_next_event,
        "stuck_detector_version": stuck_detector_version,
        "compensation_action": compensation_action,
        "recovery_ref": recovery_ref,
    }


class SqlProjectHeartbeatStore:
    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def for_url(cls, url: str) -> SqlProjectHeartbeatStore:
        engine = create_engine(url, future=True)
        Base.metadata.create_all(engine, tables=[ProjectHeartbeatRow.__table__])
        return cls(engine)

    @staticmethod
    def _scope_where(*, project_id: str, tenant_id: str, entity_id: str, store_ref: str):
        return (
            ProjectHeartbeatRow.project_id == project_id,
            ProjectHeartbeatRow.tenant_id == tenant_id,
            ProjectHeartbeatRow.entity_id == entity_id,
            ProjectHeartbeatRow.store_ref == store_ref,
        )

    @staticmethod
    def _validate_digest(value: str, field: str) -> str:
        normalized = value.strip().lower()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError(f"{field} must be a 64-character SHA-256 digest")
        return normalized

    @staticmethod
    def _resolve_existing(row: ProjectHeartbeatRow, request_sha256: str) -> dict[str, Any]:
        stored_request = (row.request_sha256 or "").lower()
        # Rows created before the hardening migration may not carry the new
        # request digest.  Their payload digest still provides a useful
        # immutable fallback; a migrated row is always checked strictly.
        if stored_request and stored_request != request_sha256:
            raise ProjectHeartbeatConflict(
                "heartbeat idempotency key conflicts with immutable request"
            )
        return SqlProjectHeartbeatStore._dump(row, idempotent=True)

    def record(
        self,
        *,
        project_id: str,
        tenant_id: str,
        entity_id: str,
        store_ref: str,
        head: str,
        graph_snapshot_sha256: str,
        status: str,
        payload: Mapping[str, Any],
        observed_at: datetime | None = None,
        heartbeat_id: str | None = None,
        idempotency_key: str | None = None,
        expected_revision: int | None = None,
        liveness_deadline: datetime | None = None,
        heartbeat_at: datetime | None = None,
        progress_cursor: str | None = None,
        expected_next_event: str | None = None,
        stuck_detector_version: str | None = None,
        compensation_action: str | None = None,
        recovery_ref: str | None = None,
    ) -> dict[str, Any]:
        """Append one heartbeat with idempotent, compare-and-swap semantics.

        The scope/revision unique constraint is the final arbiter when two PM
        workers race.  A losing worker retries with a fresh latest revision;
        an explicit ``expected_revision`` then turns stale work into a
        deterministic 409-style conflict instead of silently appending an
        observation to the wrong graph snapshot.
        """

        project_id = _text(project_id, "project_id", 200) or ""
        tenant_id = _text(tenant_id, "tenant_id", 160) or ""
        entity_id = _text(entity_id, "entity_id", 160) or ""
        store_ref = _text(store_ref, "store_ref", 160) or ""
        head = _text(head, "head", 200) or ""
        status = _text(status, "status", 40) or ""
        if expected_revision is not None and expected_revision < 0:
            raise ValueError("expected_revision must be non-negative")
        graph_snapshot_sha256 = self._validate_digest(
            graph_snapshot_sha256, "graph_snapshot_sha256"
        )
        observed = _aware(observed_at or datetime.now(UTC))
        heartbeat_observed = _aware(heartbeat_at) if heartbeat_at is not None else observed
        deadline = _aware(liveness_deadline) if liveness_deadline is not None else None
        payload_dict = dict(payload)
        progress_cursor = _text(progress_cursor, "progress_cursor", 500)
        expected_next_event = _text(expected_next_event, "expected_next_event", 300)
        stuck_detector_version = _text(stuck_detector_version, "stuck_detector_version", 100)
        compensation_action = _text(compensation_action, "compensation_action", 300)
        recovery_ref = _text(recovery_ref, "recovery_ref", 300)
        request_base = _request_payload(
            project_id=project_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            store_ref=store_ref,
            head=head,
            graph_snapshot_sha256=graph_snapshot_sha256,
            status=status,
            payload=payload_dict,
            observed_at=observed,
            liveness_deadline=deadline,
            heartbeat_at=heartbeat_observed,
            progress_cursor=progress_cursor,
            expected_next_event=expected_next_event,
            stuck_detector_version=stuck_detector_version,
            compensation_action=compensation_action,
            recovery_ref=recovery_ref,
        )
        request_sha256 = _hash(request_base)
        key = _text(idempotency_key, "idempotency_key", 300) or f"auto:{request_sha256}"
        heartbeat_id = _text(heartbeat_id, "heartbeat_id", 200) or f"pmhb_{request_sha256[:40]}"
        payload_sha = _hash(payload_dict)

        # A bounded retry is sufficient: PostgreSQL row locks serialize normal
        # operation, while the unique revision index resolves a first-insert
        # race where no row existed to lock.  We never retry an idempotency
        # conflict, because the request may have changed materially.
        for attempt in range(5):
            try:
                with Session(self.engine) as session, session.begin():
                    existing = session.scalar(
                        select(ProjectHeartbeatRow).where(
                            *self._scope_where(
                                project_id=project_id,
                                tenant_id=tenant_id,
                                entity_id=entity_id,
                                store_ref=store_ref,
                            ),
                            ProjectHeartbeatRow.idempotency_key == key,
                        )
                    )
                    if existing is not None:
                        return self._resolve_existing(existing, request_sha256)
                    by_id = session.get(ProjectHeartbeatRow, heartbeat_id)
                    if by_id is not None:
                        return self._resolve_existing(by_id, request_sha256)

                    latest = session.scalars(
                        select(ProjectHeartbeatRow)
                        .where(
                            *self._scope_where(
                                project_id=project_id,
                                tenant_id=tenant_id,
                                entity_id=entity_id,
                                store_ref=store_ref,
                            )
                        )
                        .order_by(ProjectHeartbeatRow.revision.desc())
                        .with_for_update()
                    ).first()
                    current_revision = latest.revision if latest is not None else 0
                    if expected_revision is not None and current_revision != expected_revision:
                        raise ProjectHeartbeatConflict(
                            f"heartbeat revision is stale: expected {expected_revision}, "
                            f"current {current_revision}"
                        )
                    revision = current_revision + 1
                    row = ProjectHeartbeatRow(
                        heartbeat_id=heartbeat_id,
                        project_id=project_id,
                        tenant_id=tenant_id,
                        entity_id=entity_id,
                        store_ref=store_ref,
                        revision=revision,
                        observed_at=observed,
                        head=head,
                        graph_snapshot_sha256=graph_snapshot_sha256,
                        status=status,
                        payload_json=payload_dict,
                        payload_sha256=payload_sha,
                        idempotency_key=key,
                        request_sha256=request_sha256,
                        liveness_deadline=deadline,
                        heartbeat_at=heartbeat_observed,
                        progress_cursor=progress_cursor,
                        expected_next_event=expected_next_event,
                        stuck_detector_version=stuck_detector_version,
                        compensation_action=compensation_action,
                        recovery_ref=recovery_ref,
                    )
                    # Keep the outer transaction usable if a concurrent worker
                    # wins the unique constraint during flush.
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                    return self._dump(row, idempotent=False)
            except ProjectHeartbeatConflict:
                raise
            except IntegrityError as exc:
                # Read the winner in a new transaction.  If it is this
                # idempotency key, compare the immutable request; otherwise a
                # revision race is safe to retry with a fresh latest row.
                with Session(self.engine) as session:
                    winner = session.scalar(
                        select(ProjectHeartbeatRow).where(
                            *self._scope_where(
                                project_id=project_id,
                                tenant_id=tenant_id,
                                entity_id=entity_id,
                                store_ref=store_ref,
                            ),
                            ProjectHeartbeatRow.idempotency_key == key,
                        )
                    )
                    if winner is not None:
                        return self._resolve_existing(winner, request_sha256)
                    by_id = session.get(ProjectHeartbeatRow, heartbeat_id)
                    if by_id is not None:
                        return self._resolve_existing(by_id, request_sha256)
                if attempt >= 4:
                    raise ProjectHeartbeatConflict(
                        "concurrent heartbeat revision conflict; retry from a fresh snapshot"
                    ) from exc

    def latest(self, *, project_id: str, tenant_id: str, entity_id: str, store_ref: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            row = session.scalars(
                select(ProjectHeartbeatRow)
                .where(*self._scope_where(project_id=project_id, tenant_id=tenant_id,
                                          entity_id=entity_id, store_ref=store_ref))
                .order_by(ProjectHeartbeatRow.revision.desc())
            ).first()
            return self._dump(row, idempotent=False) if row else None

    def history(self, *, project_id: str, tenant_id: str, entity_id: str, store_ref: str) -> tuple[dict[str, Any], ...]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ProjectHeartbeatRow)
                .where(*self._scope_where(project_id=project_id, tenant_id=tenant_id,
                                          entity_id=entity_id, store_ref=store_ref))
                .order_by(ProjectHeartbeatRow.revision)
            ).all()
            return tuple(self._dump(row, idempotent=False) for row in rows)

    def list_latest(
        self,
        *,
        tenant_id: str,
        entity_id: str | None = None,
        store_refs: tuple[str, ...] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return the latest heartbeat for each visible project/store scope.

        The watchdog must inspect a bounded, immutable projection rather than
        parsing every historical heartbeat.  Scope filters are applied in SQL
        before rows leave the persistence adapter; callers therefore cannot
        accidentally turn an observability query into a cross-tenant scan.
        """

        tenant_id = _text(tenant_id, "tenant_id", 160) or ""
        entity_id = _text(entity_id, "entity_id", 160)
        normalized_stores = tuple(
            dict.fromkeys(
                value
                for value in (
                    _text(item, "store_ref", 160) for item in (store_refs or ())
                )
                if value
            )
        )
        # ``None`` means the caller deliberately omitted a store filter;
        # an empty tuple means the caller has no visible stores.  Treating
        # both as unrestricted would turn an empty principal scope into a
        # cross-store read, so fail closed for the latter.
        if store_refs is not None and not normalized_stores:
            return ()
        conditions = [ProjectHeartbeatRow.tenant_id == tenant_id]
        if entity_id is not None:
            conditions.append(ProjectHeartbeatRow.entity_id == entity_id)
        if normalized_stores:
            conditions.append(ProjectHeartbeatRow.store_ref.in_(normalized_stores))

        with Session(self.engine) as session:
            rows = session.scalars(
                select(ProjectHeartbeatRow)
                .where(*conditions)
                .order_by(
                    ProjectHeartbeatRow.entity_id,
                    ProjectHeartbeatRow.project_id,
                    ProjectHeartbeatRow.store_ref,
                    ProjectHeartbeatRow.revision.desc(),
                )
            ).all()

        latest: dict[tuple[str, str, str], ProjectHeartbeatRow] = {}
        for row in rows:
            key = (row.entity_id, row.project_id, row.store_ref)
            # The query is ordered newest first within each scope.  Keeping
            # the first row makes the selection deterministic on SQLite and
            # PostgreSQL alike without relying on a dialect-specific window
            # function.
            latest.setdefault(key, row)
        return tuple(
            self._dump(row, idempotent=False)
            for _key, row in sorted(latest.items())
        )

    @staticmethod
    def _dump(row: ProjectHeartbeatRow, *, idempotent: bool) -> dict[str, Any]:
        observed = _aware(row.observed_at)
        return {
            "heartbeat_id": row.heartbeat_id,
            "project_id": row.project_id,
            "tenant_id": row.tenant_id,
            "entity_id": row.entity_id,
            "store_ref": row.store_ref,
            "revision": row.revision,
            "observed_at": observed.isoformat(),
            "head": row.head,
            "graph_snapshot_sha256": row.graph_snapshot_sha256,
            "status": row.status,
            "payload": dict(row.payload_json or {}),
            "payload_sha256": row.payload_sha256,
            "idempotency_key": row.idempotency_key,
            "request_sha256": row.request_sha256,
            "liveness_deadline": (
                _aware(row.liveness_deadline).isoformat()
                if row.liveness_deadline is not None
                else None
            ),
            "heartbeat_at": (
                _aware(row.heartbeat_at).isoformat()
                if row.heartbeat_at is not None
                else None
            ),
            "progress_cursor": row.progress_cursor,
            "expected_next_event": row.expected_next_event,
            "stuck_detector_version": row.stuck_detector_version,
            "compensation_action": row.compensation_action,
            "recovery_ref": row.recovery_ref,
            "idempotent": idempotent,
        }


__all__ = [
    "ProjectHeartbeatConflict",
    "ProjectHeartbeatRow",
    "SqlProjectHeartbeatStore",
]
