"""SQLAlchemy persistence adapter for the provider-neutral temporal kernel.

The in-memory :class:`~apps.control_plane.temporal_fact_store.TemporalFactStore`
is the reference implementation of the temporal contract.  This adapter keeps
the same append-only, versioned and scope-aware semantics while leaving schema
creation to Alembic in a composed runtime.  ``for_url`` is retained for small
isolated tools and tests that explicitly opt into creating the table.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .sql_repository import Base
from .temporal_fact_store import (
    FactNotFoundError,
    LineageEdge,
    LineageRef,
    QualityState,
    RevisionConflictError,
    ScopeRef,
    TemporalFactQueryResult,
    TemporalFactRevision,
    _project_quality_at_cutoff,
    _request_fingerprint,
    _scope_key,
    _scope_matches,
    _utc,
    lineage_edge_id,
)


class TemporalFactRow(Base):
    """One immutable canonical fact revision.

    The unique indexes are deliberately represented in the SQLAlchemy model as
    well as in migration ``20260906_0107``.  This means isolated SQLite tests
    exercise the same race-resistant identity rules as PostgreSQL deployments.
    Empty idempotency keys are stored as ``NULL`` by the adapter, allowing
    multiple legacy/non-idempotent imports while still enforcing uniqueness for
    real keys (the partial index is portable across PostgreSQL and SQLite).
    """

    __tablename__ = "temporal_fact_revisions"
    __table_args__ = (
        Index(
            "ix_temporal_fact_identity_revision",
            "tenant_id",
            "entity_id",
            "scope_key",
            "fact_type",
            "natural_key",
            "revision",
        ),
        Index("ix_temporal_fact_observed", "tenant_id", "entity_id", "observed_time"),
        Index(
            "uq_temporal_fact_identity_revision",
            "scope_key",
            "fact_type",
            "natural_key",
            "revision",
            unique=True,
        ),
        Index("uq_temporal_fact_id_revision", "fact_id", "revision", unique=True),
        Index(
            "uq_temporal_fact_scope_idempotency",
            "scope_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL AND idempotency_key <> ''"),
            sqlite_where=text("idempotency_key IS NOT NULL AND idempotency_key <> ''"),
        ),
    )

    revision_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    fact_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    fact_type: Mapped[str] = mapped_column(String(200), nullable=False)
    natural_key: Mapped[str] = mapped_column(String(300), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(500), nullable=False)
    store_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    warehouse_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    lineage_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settled_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quality_state: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_system: Mapped[str] = mapped_column(String(160), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(300), nullable=False)
    source_version: Mapped[str] = mapped_column(String(120), nullable=False)
    causation_id: Mapped[str] = mapped_column(String(300), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(300), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    permission_scope: Mapped[str | None] = mapped_column(String(500), nullable=True)
    revision_reason: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    supersedes_revision: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(160), nullable=False)


def _aware(value: datetime | None) -> datetime | None:
    """Normalize dialects (notably SQLite) that strip timezone metadata."""

    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _row_to_revision(row: TemporalFactRow) -> TemporalFactRevision:
    """Convert a row without allowing a mutable ORM object to escape."""

    return TemporalFactRevision(
        fact_id=row.fact_id,
        revision_id=row.revision_id,
        revision=row.revision,
        fact_type=row.fact_type,
        natural_key=row.natural_key,
        scope=ScopeRef(
            tenant_id=row.tenant_id,
            entity_id=row.entity_id,
            store_ids=tuple(row.store_ids_json or ()),
            warehouse_ids=tuple(row.warehouse_ids_json or ()),
        ),
        payload=dict(row.payload_json or {}),
        metadata=dict(row.metadata_json or {}),
        lineage=tuple(row.lineage_json or ()),
        event_time=_aware(row.event_time),
        observed_time=_aware(row.observed_time),
        effective_time=_aware(row.effective_time),
        settled_time=_aware(row.settled_time),
        fresh_until=_aware(row.fresh_until),
        quality_state=QualityState(row.quality_state),
        source_system=row.source_system or "unknown",
        source_record_id=row.source_record_id or row.natural_key,
        source_version=row.source_version or "1",
        causation_id=row.causation_id or "",
        correlation_id=row.correlation_id or "",
        idempotency_key=row.idempotency_key or "",
        permission_scope=row.permission_scope,
        revision_reason=row.revision_reason,
        supersedes_revision=row.supersedes_revision,
        created_by=row.created_by or "system",
    )


class SqlTemporalFactStore:
    """Append-only SQL adapter with the same read contract as the memory store."""

    def __init__(self, engine: Engine, *, clock: Callable[[], datetime] | None = None):
        self.engine = engine
        self._clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    def for_url(
        cls,
        url: str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> SqlTemporalFactStore:
        engine = create_engine(url, future=True)
        Base.metadata.create_all(engine, tables=[TemporalFactRow.__table__])
        return cls(engine, clock=clock)

    @staticmethod
    def _candidate(
        fact: TemporalFactRevision | Mapping[str, Any] | None,
        values: Mapping[str, Any],
    ) -> TemporalFactRevision:
        if fact is not None:
            if values:
                raise TypeError("append accepts either a fact or keyword fields, not both")
            candidate = fact if isinstance(fact, TemporalFactRevision) else TemporalFactRevision.model_validate(fact)
        else:
            candidate = TemporalFactRevision.model_validate(values)
        # Re-validation closes the Pydantic ``model_copy(update=...)`` escape
        # hatch and guarantees a detached, canonical payload before SQL write.
        return TemporalFactRevision.model_validate(candidate.model_dump(mode="python"))

    def append(
        self,
        fact: TemporalFactRevision | Mapping[str, Any] | None = None,
        **values: Any,
    ) -> TemporalFactRevision:
        """Append a first revision or correction with exact idempotency.

        A matching idempotency key is compared using the complete request
        fingerprint, rather than only ``payload_hash``.  This prevents a
        changed source version, timestamp, quality state or lineage from being
        silently discarded as a duplicate.
        """

        candidate = self._candidate(fact, values)
        scope_key = _scope_key(candidate.scope)
        identity_filter = (
            TemporalFactRow.scope_key == scope_key,
            TemporalFactRow.fact_type == candidate.fact_type,
            TemporalFactRow.natural_key == candidate.natural_key,
        )
        candidate_fingerprint = _request_fingerprint(candidate)

        try:
            with Session(self.engine) as session, session.begin():
                rows = session.scalars(
                    select(TemporalFactRow)
                    .where(*identity_filter)
                    .order_by(TemporalFactRow.revision)
                ).all()

                # Idempotency is scoped by the canonical scope, not merely by a
                # connector's global key.  Search all revisions so a retry of
                # an earlier import remains safe after later corrections.
                if candidate.idempotency_key:
                    keyed_rows = session.scalars(
                        select(TemporalFactRow)
                        .where(
                            TemporalFactRow.scope_key == scope_key,
                            TemporalFactRow.idempotency_key == candidate.idempotency_key,
                        )
                        .order_by(TemporalFactRow.revision)
                    ).all()
                    for keyed in keyed_rows:
                        existing = _row_to_revision(keyed)
                        if _request_fingerprint(existing) != candidate_fingerprint:
                            raise RevisionConflictError(
                                "idempotency key was reused with a different payload"
                            )
                        return existing

                for stored_row in rows:
                    stored = _row_to_revision(stored_row)
                    if (
                        stored.fact_id == candidate.fact_id
                        and stored.revision == candidate.revision
                        and _request_fingerprint(stored) == candidate_fingerprint
                    ):
                        return stored

                latest = rows[-1] if rows else None
                if latest is None:
                    if candidate.revision != 1:
                        raise RevisionConflictError("first SQL temporal revision must be 1")
                    row_fact = candidate
                else:
                    current = _row_to_revision(latest)
                    if candidate.fact_id != current.fact_id:
                        raise RevisionConflictError(
                            "natural fact identity is already bound to another fact_id"
                        )
                    if candidate.observed_time < current.observed_time:
                        raise RevisionConflictError("revision observed_time cannot move backwards")
                    row_fact = candidate.model_copy(
                        update={
                            "revision": current.revision + 1,
                            # Match the reference memory adapter: a caller
                            # that reuses a first-revision object must still
                            # receive a fresh immutable revision identity.
                            "revision_id": (
                                candidate.revision_id
                                if candidate.revision > 1
                                else f"{candidate.fact_id}-r{current.revision + 1}"
                            ),
                            "supersedes_revision": current.revision,
                        },
                        deep=True,
                    )

                row = TemporalFactRow(
                    revision_id=row_fact.revision_id,
                    fact_id=row_fact.fact_id,
                    revision=row_fact.revision,
                    fact_type=row_fact.fact_type,
                    natural_key=row_fact.natural_key,
                    tenant_id=row_fact.scope.tenant_id,
                    entity_id=row_fact.scope.entity_id,
                    scope_key=scope_key,
                    store_ids_json=list(row_fact.scope.store_ids),
                    warehouse_ids_json=list(row_fact.scope.warehouse_ids),
                    payload_json=row_fact.payload,
                    metadata_json=row_fact.metadata,
                    lineage_json=[item.model_dump(mode="json") for item in row_fact.lineage],
                    event_time=row_fact.event_time,
                    observed_time=row_fact.observed_time,
                    effective_time=row_fact.effective_time,
                    settled_time=row_fact.settled_time,
                    fresh_until=row_fact.fresh_until,
                    quality_state=row_fact.quality_state.value,
                    payload_hash=row_fact.payload_hash,
                    source_system=row_fact.source_system,
                    source_record_id=row_fact.source_record_id,
                    source_version=row_fact.source_version,
                    causation_id=row_fact.causation_id,
                    correlation_id=row_fact.correlation_id,
                    # Empty keys are NULL so the partial unique index does not
                    # turn non-idempotent imports into one global key.
                    idempotency_key=row_fact.idempotency_key or None,
                    permission_scope=row_fact.permission_scope,
                    revision_reason=row_fact.revision_reason,
                    supersedes_revision=row_fact.supersedes_revision,
                    created_by=row_fact.created_by,
                )
                session.add(row)
                session.flush()
                return _row_to_revision(row)
        except IntegrityError as exc:
            # Unique indexes turn concurrent duplicate writes into a safe
            # conflict rather than allowing two revisions for one identity.
            raise RevisionConflictError("SQL temporal revision conflicts with an existing write") from exc

    record = append
    add = append
    save = append
    put = append
    append_revision = append
    upsert = append

    def restate(
        self,
        fact_id: str,
        payload: Mapping[str, Any],
        *,
        correction_reason: str,
        observed_time: datetime | None = None,
        event_time: datetime | None = None,
        effective_time: datetime | None = None,
        settled_time: datetime | None = None,
        fresh_until: datetime | None = None,
        quality_state: QualityState | str | None = None,
        lineage: Iterable[LineageRef | Mapping[str, Any]] | None = None,
        source_version: str | None = None,
        causation_id: str | None = None,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_by: str | None = None,
    ) -> TemporalFactRevision:
        reason = str(correction_reason or "").strip()
        if not reason:
            raise ValueError("correction_reason is required for a restatement")
        current = self.get(fact_id)
        now = _utc(observed_time or self._clock(), "observed_time")
        candidate_values = current.model_dump(mode="python")
        candidate_values.update(
            {
                "revision_id": f"{current.fact_id}-r{current.revision + 1}",
                "revision": current.revision + 1,
                "payload": dict(payload),
                "payload_hash": None,
                "event_time": event_time if event_time is not None else current.event_time,
                "observed_time": now,
                "effective_time": effective_time if effective_time is not None else current.effective_time,
                "settled_time": settled_time if settled_time is not None else current.settled_time,
                "fresh_until": fresh_until if fresh_until is not None else current.fresh_until,
                "quality_state": quality_state if quality_state is not None else current.quality_state,
                "lineage": tuple(lineage) if lineage is not None else current.lineage,
                "source_version": source_version if source_version is not None else current.source_version,
                "causation_id": causation_id if causation_id is not None else current.causation_id,
                "correlation_id": correlation_id if correlation_id is not None else current.correlation_id,
                "idempotency_key": idempotency_key if idempotency_key is not None else "",
                "metadata": dict(metadata) if metadata is not None else current.metadata,
                "revision_reason": reason,
                "created_by": created_by if created_by is not None else current.created_by,
                "supersedes_revision": current.revision,
            }
        )
        return self.append(TemporalFactRevision.model_validate(candidate_values))

    correct = restate

    def history(self, fact_id: str) -> tuple[TemporalFactRevision, ...]:
        key = str(fact_id or "").strip()
        if not key:
            raise FactNotFoundError("fact_id is required")
        with Session(self.engine) as session:
            rows = session.scalars(
                select(TemporalFactRow)
                .where(TemporalFactRow.fact_id == key)
                .order_by(TemporalFactRow.revision)
            ).all()
        if not rows:
            raise FactNotFoundError(f"Unknown fact: {key}")
        return tuple(_row_to_revision(row) for row in rows)

    versions = history
    list_versions = history

    def get(
        self,
        fact_id: str,
        *,
        revision: int | None = None,
        version: int | None = None,
    ) -> TemporalFactRevision:
        selected_revision = revision if revision is not None else version
        if selected_revision is not None and selected_revision < 1:
            raise FactNotFoundError(f"Unknown fact revision: {fact_id}@{selected_revision}")
        rows = self.history(fact_id)
        if selected_revision is None:
            return rows[-1]
        for row in rows:
            if row.revision == selected_revision:
                return row
        raise FactNotFoundError(f"Unknown fact revision: {fact_id}@{selected_revision}")

    def get_as_of(
        self,
        fact_id: str,
        cutoff: datetime | None = None,
        *,
        as_of: datetime | None = None,
    ) -> TemporalFactRevision:
        if cutoff is None:
            cutoff = as_of
        if cutoff is None:
            raise ValueError("as_of cutoff is required")
        cutoff_utc = _utc(cutoff, "as_of")
        candidates = [item for item in self.history(fact_id) if item.observed_time <= cutoff_utc]
        if not candidates:
            raise FactNotFoundError(f"Fact is not visible at requested cutoff: {fact_id}")
        selected = max(candidates, key=lambda item: (item.observed_time, item.revision))
        return _project_quality_at_cutoff(selected, cutoff_utc)

    get_at = get_as_of
    version_at = get_as_of

    def list(
        self,
        *,
        fact_type: str | None = None,
        scope: ScopeRef | None = None,
        quality_state: QualityState | str | None = None,
    ) -> tuple[TemporalFactRevision, ...]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(TemporalFactRow).order_by(
                    TemporalFactRow.fact_type,
                    TemporalFactRow.natural_key,
                    TemporalFactRow.revision,
                )
            ).all()
        latest: dict[tuple[str, str, str], TemporalFactRevision] = {}
        for row in rows:
            item = _row_to_revision(row)
            key = (_scope_key(item.scope), item.fact_type, item.natural_key)
            latest[key] = item
        quality = QualityState(quality_state) if quality_state is not None else None
        selected = [
            item
            for item in latest.values()
            if (fact_type is None or item.fact_type == fact_type)
            and _scope_matches(item.scope, scope)
            and (quality is None or item.quality_state == quality)
        ]
        selected.sort(key=lambda item: (item.fact_type, item.natural_key, item.fact_id))
        return tuple(selected)

    def as_of(
        self,
        cutoff: datetime | None = None,
        *,
        as_of: datetime | None = None,
        scope: ScopeRef | None = None,
        fact_type: str | None = None,
        natural_key: str | None = None,
        quality_states: Iterable[QualityState | str] | None = None,
        event_start: datetime | None = None,
        event_end: datetime | None = None,
        include_stale: bool = True,
    ) -> tuple[TemporalFactRevision, ...]:
        if cutoff is None:
            cutoff = as_of
        if cutoff is None:
            raise ValueError("as_of cutoff is required")
        cutoff_utc = _utc(cutoff, "as_of")
        start = _utc(event_start, "event_start") if event_start is not None else None
        end = _utc(event_end, "event_end") if event_end is not None else None
        if start is not None and end is not None and end < start:
            raise ValueError("event_end must not precede event_start")
        allowed = {QualityState(value) for value in quality_states} if quality_states is not None else None

        with Session(self.engine) as session:
            rows = session.scalars(
                select(TemporalFactRow)
                .where(TemporalFactRow.observed_time <= cutoff_utc)
                .order_by(TemporalFactRow.observed_time, TemporalFactRow.revision)
            ).all()

        latest: dict[tuple[str, str, str], TemporalFactRevision] = {}
        for row in rows:
            item = _row_to_revision(row)
            if not _scope_matches(item.scope, scope):
                continue
            key = (_scope_key(item.scope), item.fact_type, item.natural_key)
            previous = latest.get(key)
            if previous is None or (item.observed_time, item.revision) >= (
                previous.observed_time,
                previous.revision,
            ):
                latest[key] = item

        visible: list[TemporalFactRevision] = []
        for item in latest.values():
            if fact_type is not None and item.fact_type != fact_type:
                continue
            if natural_key is not None and item.natural_key != natural_key:
                continue
            projected = _project_quality_at_cutoff(item, cutoff_utc)
            if allowed is not None and projected.quality_state not in allowed:
                continue
            if not include_stale and projected.quality_state == QualityState.STALE:
                continue
            if start is not None and item.event_time < start:
                continue
            if end is not None and item.event_time >= end:
                continue
            visible.append(projected)
        visible.sort(key=lambda item: (item.fact_type, item.natural_key, item.fact_id))
        return tuple(visible)

    list_as_of = as_of

    def query_as_of(
        self,
        cutoff: datetime | None = None,
        *,
        as_of: datetime | None = None,
        **filters: Any,
    ) -> TemporalFactQueryResult:
        if cutoff is None:
            cutoff = as_of
        if cutoff is None:
            raise ValueError("as_of cutoff is required")
        cutoff_utc = _utc(cutoff, "as_of")
        items = self.as_of(cutoff_utc, **filters)
        quality = QualityState.VALID
        if not items:
            quality = QualityState.NO_DATA
        elif any(item.quality_state == QualityState.BLOCKED for item in items):
            quality = QualityState.BLOCKED
        elif any(item.quality_state == QualityState.UNKNOWN_OUTCOME for item in items):
            quality = QualityState.UNKNOWN_OUTCOME
        elif any(item.quality_state == QualityState.STALE for item in items):
            quality = QualityState.STALE
        elif any(item.quality_state == QualityState.PARTIAL for item in items):
            quality = QualityState.PARTIAL
        return TemporalFactQueryResult(as_of=cutoff_utc, items=items, quality_state=quality)

    query = query_as_of
    replay = query_as_of

    def lineage(self, fact_id: str, *, revision: int | None = None) -> tuple[LineageRef, ...]:
        return self.get(fact_id, revision=revision).lineage

    def lineage_edges(self, fact_id: str, *, revision: int | None = None) -> tuple[LineageEdge, ...]:
        fact = self.get(fact_id, revision=revision)
        return tuple(
            LineageEdge(
                id=lineage_edge_id(
                    revision_id=fact.revision_id,
                    from_type=ref.kind,
                    from_id=ref.id,
                    relationship=ref.relationship,
                ),
                from_type=ref.kind,
                from_id=ref.id,
                from_sha256=ref.sha256,
                to_type="fact_revision",
                to_id=fact.revision_id,
                relationship=ref.relationship,
                created_by=fact.created_by,
                recorded_at=fact.observed_time,
                metadata={"fact_id": fact.fact_id, "revision": fact.revision},
            )
            for ref in fact.lineage
        )

    def snapshot(self) -> tuple[TemporalFactRevision, ...]:
        return self.list()

    def history_snapshot(self) -> tuple[TemporalFactRevision, ...]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(TemporalFactRow).order_by(
                    TemporalFactRow.fact_type,
                    TemporalFactRow.natural_key,
                    TemporalFactRow.fact_id,
                    TemporalFactRow.revision,
                )
            ).all()
        return tuple(_row_to_revision(row) for row in rows)


__all__ = ["SqlTemporalFactStore", "TemporalFactRow"]
