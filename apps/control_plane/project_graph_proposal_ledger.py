"""Durable, proposal-only ledger for project-graph planning requests.

The project graph ``dispatch-wave`` and ``invalidate`` endpoints intentionally
do not submit work to a queue or write to a marketplace.  They still need a
durable identity: a retry must return the exact proposal that won the first
request, even when the live graph has moved on.  This module is the append-only
authority for that identity and keeps the response replayable without making
the proposal an executable command.

Schema ownership remains with Alembic.  ``for_url`` is provided only for
isolated tests and local contract tools; normal runtime composition receives an
already migrated SQLAlchemy engine.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
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

PROPOSAL_KINDS = frozenset({"dispatch-wave", "invalidation"})


class ProjectGraphProposalRow(Base):
    """One immutable proposal response and its request identity."""

    __tablename__ = "project_graph_proposals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "kind",
            "idempotency_key",
            name="uq_graph_proposal_scope_idempotency",
        ),
        UniqueConstraint(
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "kind",
            "revision",
            name="uq_graph_proposal_scope_revision",
        ),
        CheckConstraint("revision >= 1", name="ck_graph_proposal_revision_positive"),
        CheckConstraint(
            "length(request_sha256) = 64", name="ck_graph_proposal_request_hash_shape"
        ),
        CheckConstraint(
            "length(proposal_sha256) = 64",
            name="ck_graph_proposal_proposal_hash_shape",
        ),
        CheckConstraint(
            "length(payload_sha256) = 64", name="ck_graph_proposal_payload_hash_shape"
        ),
        # A proposal is bookkeeping and planning evidence.  The database
        # itself rejects an accidentally elevated write flag as a second line
        # of defence behind the Python contract.
        CheckConstraint(
            "external_write_allowed = false",
            name="ck_graph_proposal_external_write_forbidden",
        ),
        Index(
            "ix_graph_proposal_scope_recorded",
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "recorded_at",
        ),
        Index(
            "ix_graph_proposal_scope_kind_revision",
            "tenant_id",
            "entity_id",
            "project_id",
            "store_ref",
            "kind",
            "revision",
        ),
    )

    proposal_id: Mapped[str] = mapped_column(String(220), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    graph_snapshot_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    status: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    external_write_allowed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    recorded_by: Mapped[str] = mapped_column(String(160), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProjectGraphProposalConflict(ValueError):
    """A proposal key or revision cannot be reconciled with the ledger."""

    http_status_code = 409

    @property
    def http_detail(self) -> dict[str, str]:
        return {"code": "project_graph_proposal_conflict", "message": str(self)}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _text(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be blank")
    if len(normalized) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return normalized


def _digest(value: str, field: str) -> str:
    normalized = _text(value, field, 64).lower()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise ValueError(f"{field} must be a 64-character SHA-256 digest")
    return normalized


def _json_safe(value: Any) -> Any:
    """Detach a proposal into JSON-safe, deterministic values.

    Decimal values are represented as strings so replay never loses money
    precision or depends on a database driver's JSON encoder.  Non-finite
    numeric values are rejected instead of becoming an apparently valid
    proposal.
    """

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("proposal contains a non-finite Decimal")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("proposal contains a non-finite number")
        return value
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    # Pydantic/enum-like values used in projections should expose their value
    # when possible; arbitrary objects are intentionally rejected rather than
    # stringifying an opaque authority object into an audit record.
    enum_value = getattr(value, "value", None)
    if enum_value is not None and enum_value is not value:
        return _json_safe(enum_value)
    raise ValueError(f"proposal contains unsupported JSON value: {type(value).__name__}")


def _canonical(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _scope_values(
    *, project_id: str, tenant_id: str, entity_id: str, store_ref: str, kind: str
) -> dict[str, str]:
    return {
        "project_id": _text(project_id, "project_id", 200),
        "tenant_id": _text(tenant_id, "tenant_id", 160),
        "entity_id": _text(entity_id, "entity_id", 160),
        "store_ref": _text(store_ref, "store_ref", 160),
        "kind": _text(kind, "kind", 80),
    }


def _proposal_id(
    *,
    project_id: str,
    tenant_id: str,
    entity_id: str,
    store_ref: str,
    kind: str,
    idempotency_key: str,
) -> str:
    return "pgp_" + _hash(
        {
            "project_id": project_id,
            "tenant_id": tenant_id,
            "entity_id": entity_id,
            "store_ref": store_ref,
            "kind": kind,
            "idempotency_key": idempotency_key,
        }
    )[:40]


def _dump(row: ProjectGraphProposalRow, *, replayed: bool) -> dict[str, Any]:
    payload = copy.deepcopy(row.payload_json or {})
    return {
        "proposal_id": row.proposal_id,
        "project_id": row.project_id,
        "tenant_id": row.tenant_id,
        "entity_id": row.entity_id,
        "store_ref": row.store_ref,
        "kind": row.kind,
        "revision": row.revision,
        "idempotency_key": row.idempotency_key,
        "request_sha256": row.request_sha256,
        "proposal_sha256": row.proposal_sha256,
        "payload_sha256": row.payload_sha256,
        "graph_snapshot_sha256": row.graph_snapshot_sha256,
        "status": row.status,
        "payload": payload,
        "external_write_allowed": False,
        "recorded_by": row.recorded_by,
        "observed_at": _aware(row.observed_at).isoformat(),
        "recorded_at": _aware(row.recorded_at).isoformat(),
        "replayed": replayed,
    }


class SqlProjectGraphProposalLedger:
    """Append-only SQL implementation with exact replay and CAS semantics."""

    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def for_url(cls, url: str) -> SqlProjectGraphProposalLedger:
        engine = create_engine(url, future=True)
        Base.metadata.create_all(engine, tables=[ProjectGraphProposalRow.__table__])
        return cls(engine)

    @staticmethod
    def _scope_where(**scope: str):
        return (
            ProjectGraphProposalRow.project_id == scope["project_id"],
            ProjectGraphProposalRow.tenant_id == scope["tenant_id"],
            ProjectGraphProposalRow.entity_id == scope["entity_id"],
            ProjectGraphProposalRow.store_ref == scope["store_ref"],
            ProjectGraphProposalRow.kind == scope["kind"],
        )

    @staticmethod
    def _by_key(
        session: Session, *, scope: Mapping[str, str], idempotency_key: str
    ) -> ProjectGraphProposalRow | None:
        return session.scalar(
            select(ProjectGraphProposalRow).where(
                *SqlProjectGraphProposalLedger._scope_where(**scope),
                ProjectGraphProposalRow.idempotency_key == idempotency_key,
            )
        )

    @staticmethod
    def _resolve_existing(
        row: ProjectGraphProposalRow, *, request_sha256: str
    ) -> dict[str, Any]:
        if row.request_sha256 != request_sha256:
            raise ProjectGraphProposalConflict(
                "proposal idempotency key was reused with a different request"
            )
        # Verify the immutable JSON itself before returning a replay.  This
        # catches storage tampering and prevents a corrupt row from becoming a
        # trusted planning input.
        SqlProjectGraphProposalLedger._verify_row(row)
        return _dump(row, replayed=True)

    @staticmethod
    def _verify_row(row: ProjectGraphProposalRow) -> None:
        """Validate an immutable row before exposing it to a caller."""

        try:
            payload_digest = _hash(row.payload_json or {})
        except (TypeError, ValueError) as exc:
            raise ProjectGraphProposalConflict(
                "stored proposal payload is not canonical JSON"
            ) from exc
        if row.payload_sha256 != payload_digest:
            raise ProjectGraphProposalConflict("stored proposal payload hash mismatch")
        embedded_digest = (row.payload_json or {}).get("proposal_sha256")
        if (
            embedded_digest is not None
            and str(embedded_digest).lower() != row.proposal_sha256
        ):
            raise ProjectGraphProposalConflict(
                "stored proposal digest does not match its payload"
            )

    def record(
        self,
        *,
        project_id: str,
        tenant_id: str,
        entity_id: str,
        store_ref: str,
        kind: str,
        idempotency_key: str,
        request_sha256: str,
        proposal: Mapping[str, Any],
        proposal_sha256: str | None = None,
        graph_snapshot_sha256: str | None = None,
        status: str | None = None,
        recorded_by: str = "system",
        observed_at: datetime | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        scope = _scope_values(
            project_id=project_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            store_ref=store_ref,
            kind=kind,
        )
        if kind not in PROPOSAL_KINDS:
            raise ValueError(f"unsupported project graph proposal kind: {kind}")
        key = _text(idempotency_key, "idempotency_key", 300)
        request_digest = _digest(request_sha256, "request_sha256")
        safe_proposal = _json_safe(dict(proposal))
        if not isinstance(safe_proposal, dict):  # pragma: no cover - Mapping above
            raise ValueError("proposal must be an object")
        external_write_flag = safe_proposal.get("external_write_allowed")
        if external_write_flag is not None and external_write_flag is not False:
            raise ValueError("project graph proposals cannot allow external writes")
        supplied_proposal_digest = proposal_sha256 or safe_proposal.get("proposal_sha256")
        if supplied_proposal_digest is None:
            supplied_proposal_digest = _hash(safe_proposal)
        proposal_digest = _digest(str(supplied_proposal_digest), "proposal_sha256")
        embedded_digest = safe_proposal.get("proposal_sha256")
        if (
            embedded_digest is not None
            and _digest(str(embedded_digest), "proposal.proposal_sha256")
            != proposal_digest
        ):
            raise ValueError("proposal_sha256 does not match the proposal payload")
        graph_digest = (
            _digest(graph_snapshot_sha256, "graph_snapshot_sha256")
            if graph_snapshot_sha256
            else None
        )
        actor = _text(recorded_by, "recorded_by", 160)
        state = _text(status or str(safe_proposal.get("status") or "proposed"), "status", 80)
        now = _aware(observed_at or datetime.now(UTC))
        if expected_revision is not None and expected_revision < 0:
            raise ValueError("expected_revision cannot be negative")
        proposal_id = _proposal_id(**scope, idempotency_key=key)
        payload_digest = _hash(safe_proposal)

        # A bounded retry handles the ordinary race where two workers compute
        # the same next revision.  The unique scope/revision and scope/key
        # constraints remain the final arbiter in PostgreSQL and SQLite.
        for attempt in range(5):
            try:
                with Session(self.engine) as session, session.begin():
                    existing = self._by_key(
                        session, scope=scope, idempotency_key=key
                    )
                    if existing is not None:
                        return self._resolve_existing(
                            existing, request_sha256=request_digest
                        )
                    latest = session.scalars(
                        select(ProjectGraphProposalRow)
                        .where(*self._scope_where(**scope))
                        .order_by(ProjectGraphProposalRow.revision.desc())
                    ).first()
                    current_revision = latest.revision if latest else 0
                    if (
                        expected_revision is not None
                        and expected_revision != current_revision
                    ):
                        raise ProjectGraphProposalConflict(
                            "proposal revision is stale; refresh the project graph"
                        )
                    next_revision = current_revision + 1
                    row = ProjectGraphProposalRow(
                        proposal_id=proposal_id,
                        **scope,
                        revision=next_revision,
                        idempotency_key=key,
                        request_sha256=request_digest,
                        proposal_sha256=proposal_digest,
                        graph_snapshot_sha256=graph_digest,
                        status=state,
                        payload_json=copy.deepcopy(safe_proposal),
                        payload_sha256=payload_digest,
                        external_write_allowed=False,
                        recorded_by=actor,
                        observed_at=now,
                        recorded_at=datetime.now(UTC),
                    )
                    session.add(row)
                    session.flush()
                    return _dump(row, replayed=False)
            except IntegrityError as exc:
                # A concurrent winner may have committed after our initial
                # lookup.  Resolve the winner in a fresh session before
                # deciding whether to retry the revision race.
                with Session(self.engine) as session:
                    winner = self._by_key(
                        session, scope=scope, idempotency_key=key
                    )
                    if winner is not None:
                        return self._resolve_existing(
                            winner, request_sha256=request_digest
                        )
                if attempt == 4:
                    raise ProjectGraphProposalConflict(
                        "concurrent proposal revision conflict; retry from a fresh snapshot"
                    ) from exc
        raise ProjectGraphProposalConflict("proposal ledger retry budget exhausted")

    def get(
        self,
        *,
        proposal_id: str,
        tenant_id: str,
        project_id: str,
        store_ref: str,
        entity_id: str | None = None,
    ) -> dict[str, Any]:
        proposal_id = _text(proposal_id, "proposal_id", 220)
        tenant_id = _text(tenant_id, "tenant_id", 160)
        project_id = _text(project_id, "project_id", 200)
        store_ref = _text(store_ref, "store_ref", 160)
        with Session(self.engine) as session:
            query = select(ProjectGraphProposalRow).where(
                ProjectGraphProposalRow.proposal_id == proposal_id,
                ProjectGraphProposalRow.tenant_id == tenant_id,
                ProjectGraphProposalRow.project_id == project_id,
                ProjectGraphProposalRow.store_ref == store_ref,
            )
            if entity_id is not None:
                query = query.where(
                    ProjectGraphProposalRow.entity_id == _text(entity_id, "entity_id", 160)
                )
            row = session.scalar(query)
            if row is None:
                raise KeyError(f"Unknown project graph proposal: {proposal_id}")
            self._verify_row(row)
            return _dump(row, replayed=False)

    def replay(
        self,
        *,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        store_ref: str,
        kind: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope = _scope_values(
            project_id=project_id,
            tenant_id=tenant_id,
            entity_id=entity_id,
            store_ref=store_ref,
            kind=kind,
        )
        key = _text(idempotency_key, "idempotency_key", 300)
        with Session(self.engine) as session:
            row = self._by_key(session, scope=scope, idempotency_key=key)
            if row is None:
                raise KeyError(f"Unknown project graph proposal key: {key}")
            self._verify_row(row)
            return _dump(row, replayed=True)

    def history(
        self,
        *,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        store_ref: str,
        kind: str | None = None,
        limit: int = 100,
    ) -> tuple[dict[str, Any], ...]:
        tenant_id = _text(tenant_id, "tenant_id", 160)
        project_id = _text(project_id, "project_id", 200)
        entity_id = _text(entity_id, "entity_id", 160)
        store_ref = _text(store_ref, "store_ref", 160)
        if kind is not None:
            kind = _text(kind, "kind", 80)
            if kind not in PROPOSAL_KINDS:
                raise ValueError(f"unsupported project graph proposal kind: {kind}")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with Session(self.engine) as session:
            query = select(ProjectGraphProposalRow).where(
                ProjectGraphProposalRow.tenant_id == tenant_id,
                ProjectGraphProposalRow.project_id == project_id,
                ProjectGraphProposalRow.entity_id == entity_id,
                ProjectGraphProposalRow.store_ref == store_ref,
            )
            if kind is not None:
                query = query.where(ProjectGraphProposalRow.kind == kind)
            rows = session.scalars(
                query.order_by(
                    # Replay/history follows the business observation time,
                    # rather than wall-clock insertion time.  This keeps
                    # late-arriving proposals in their logical order while
                    # the proposal id provides a stable tie-breaker.
                    ProjectGraphProposalRow.observed_at,
                    ProjectGraphProposalRow.proposal_id,
                ).limit(limit)
            ).all()
            for row in rows:
                self._verify_row(row)
            return tuple(_dump(row, replayed=False) for row in rows)

    def latest(
        self,
        *,
        tenant_id: str,
        project_id: str,
        entity_id: str,
        store_ref: str,
        kind: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the newest proposal for an exact graph scope.

        ``None`` is an explicit no-data result; callers must not turn it into
        an executable dispatch or an inferred healthy state.
        """

        tenant_id = _text(tenant_id, "tenant_id", 160)
        project_id = _text(project_id, "project_id", 200)
        entity_id = _text(entity_id, "entity_id", 160)
        store_ref = _text(store_ref, "store_ref", 160)
        if kind is not None:
            kind = _text(kind, "kind", 80)
            if kind not in PROPOSAL_KINDS:
                raise ValueError(f"unsupported project graph proposal kind: {kind}")
        with Session(self.engine) as session:
            query = select(ProjectGraphProposalRow).where(
                ProjectGraphProposalRow.tenant_id == tenant_id,
                ProjectGraphProposalRow.project_id == project_id,
                ProjectGraphProposalRow.entity_id == entity_id,
                ProjectGraphProposalRow.store_ref == store_ref,
            )
            if kind is not None:
                query = query.where(ProjectGraphProposalRow.kind == kind)
            row = session.scalars(
                query.order_by(
                    ProjectGraphProposalRow.observed_at.desc(),
                    ProjectGraphProposalRow.proposal_id.desc(),
                )
            ).first()
            if row is None:
                return None
            self._verify_row(row)
            return _dump(row, replayed=False)


__all__ = [
    "PROPOSAL_KINDS",
    "ProjectGraphProposalConflict",
    "ProjectGraphProposalRow",
    "SqlProjectGraphProposalLedger",
]
