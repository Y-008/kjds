"""Durable, proposal-only media job core for BAS-183 phase A.

This module owns the durable header/event/link contract only. Public HTTP/SSE,
provider dispatch, usage settlement, and runtime wiring are deliberately later
phases and are not imported here.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade, EvidenceService
from .security import Principal
from .sql_repository import Base

MEDIA_JOB_STATES = frozenset(
    {
        "QUEUED",
        "DISPATCHED",
        "RUNNING",
        "UPLOADING",
        "SUCCEEDED",
        "LOGIN_REQUIRED",
        "LIMITED",
        "FAILED",
        "CANCELLED",
        "UNKNOWN_OUTCOME",
    }
)
TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN_OUTCOME"})
EVENT_STREAM = "job_state"
MEDIA_JOB_TRANSITIONS = {
    "QUEUED": frozenset({"DISPATCHED", "CANCELLED", "LIMITED", "LOGIN_REQUIRED"}),
    "DISPATCHED": frozenset({"RUNNING", "FAILED", "UNKNOWN_OUTCOME"}),
    "RUNNING": frozenset({"UPLOADING", "FAILED", "UNKNOWN_OUTCOME"}),
    "UPLOADING": frozenset({"SUCCEEDED", "FAILED", "UNKNOWN_OUTCOME"}),
    "LOGIN_REQUIRED": frozenset(
        {"DISPATCHED", "RUNNING", "FAILED", "UNKNOWN_OUTCOME"}
    ),
    "LIMITED": frozenset(
        {"DISPATCHED", "RUNNING", "FAILED", "UNKNOWN_OUTCOME"}
    ),
}
MEDIA_JOB_SAFE_REASON_BY_STATE = {
    "QUEUED": None,
    "DISPATCHED": None,
    "RUNNING": None,
    "UPLOADING": None,
    "SUCCEEDED": None,
    "LOGIN_REQUIRED": "connector_login_required",
    "LIMITED": "settled_entitlement_unavailable",
    "FAILED": "provider_failed",
    "CANCELLED": "cancelled_by_request",
    "UNKNOWN_OUTCOME": "provider_outcome_unknown",
}
EVENT_FUTURE_TOLERANCE = timedelta(minutes=5)
REQUEST_SOURCE = "governed-media-job-request"
REQUEST_CONTRACT = "kjds-governed-media-job-request-v1"


def _validate_json(value: Any, *, depth: int = 0) -> None:
    if depth > 32:
        raise ValueError("media_job_request_too_deep")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("media_job_request_non_finite")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError("media_job_request_key_invalid")
            _validate_json(item, depth=depth + 1)
        return
    raise ValueError("media_job_request_value_invalid")


def canonical_json(value: Any) -> bytes:
    _validate_json(value)
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > 1_048_576:
        raise ValueError("media_job_request_too_large")
    return encoded


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def event_seal(
    *,
    job: MediaJobRow | None,
    job_ref: str,
    tenant_ref: str,
    entity_ref: str,
    store_ref: str,
    authority_sha256: str,
    subject_actor_id: str,
    ordinal: int,
    stream_kind: str,
    state: str,
    safe_reason_code: str | None,
    previous_event_sha256: str | None,
    public_projection_json: Mapping[str, Any],
    occurred_at: datetime,
    recorded_at: datetime,
    command_idempotency_sha256: str,
    command_request_sha256: str,
) -> str:
    del job
    occurred = _utc_datetime(occurred_at).isoformat(timespec="microseconds")
    recorded = _utc_datetime(recorded_at).isoformat(timespec="microseconds")
    return sha256_bytes(
        canonical_json(
            {
                "command_idempotency_sha256": command_idempotency_sha256,
                "command_request_sha256": command_request_sha256,
                "entity_ref": entity_ref,
                "event_ref_scope": authority_sha256,
                "job_ref": job_ref,
                "ordinal": ordinal,
                "occurred_at": occurred,
                "previous_event_sha256": previous_event_sha256,
                "public_projection_json": public_projection_json,
                "recorded_at": recorded,
                "safe_reason_code": safe_reason_code,
                "state": state,
                "store_ref": store_ref,
                "stream_kind": stream_kind,
                "subject_actor_id": subject_actor_id,
                "tenant_ref": tenant_ref,
            }
        )
    )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _sha256_hex(value: Any, field: str) -> str:
    result = _required_text(value, field).lower()
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise ValueError(f"{field} must be a SHA-256 hex digest")
    return result


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class MediaJobScope:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    authority_sha256: str
    subject_actor_id: str

    def normalized(self) -> MediaJobScope:
        return MediaJobScope(
            tenant_ref=_required_text(self.tenant_ref, "tenant_ref"),
            entity_ref=_required_text(self.entity_ref, "entity_ref"),
            store_ref=_required_text(self.store_ref, "store_ref"),
            authority_sha256=_sha256_hex(self.authority_sha256, "authority_sha256"),
            subject_actor_id=_required_text(self.subject_actor_id, "subject_actor_id"),
        )


@dataclass(frozen=True, slots=True)
class MediaJobProjection:
    job_ref: str
    state: str
    tool_name: str
    connector_ref: str
    created_at: str
    last_event_ordinal: int
    safe_reason_code: str | None


@dataclass(frozen=True, slots=True)
class MediaJobEventProjection:
    event_ref: str
    job_ref: str
    ordinal: int
    state: str
    safe_reason_code: str | None
    occurred_at: str


class MediaJobRow(Base):
    __tablename__ = "media_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "idempotency_sha256",
            name="uq_media_job_exact_scope_idempotency",
        ),
        UniqueConstraint(
            "job_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_media_job_exact_identity",
        ),
        Index("ix_media_job_scope_created", "tenant_ref", "entity_ref", "store_ref", "created_at"),
    )

    job_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_actor_id: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    tool_version: Mapped[str] = mapped_column(String(160), nullable=False)
    project_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    brief_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(160), nullable=False)
    connector_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    connector_binding_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_evidence_id: Mapped[str] = mapped_column(Text, nullable=False)
    request_evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaJobEventRow(Base):
    __tablename__ = "media_job_events"
    __table_args__ = (
        UniqueConstraint("job_ref", "ordinal", name="uq_media_job_event_ordinal"),
        UniqueConstraint("job_ref", "event_sha256", name="uq_media_job_event_hash"),
        UniqueConstraint(
            "event_ref",
            "job_ref",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            name="uq_media_job_event_exact_identity",
        ),
        ForeignKeyConstraint(
            ["job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_event_exact_identity",
            ondelete="RESTRICT",
        ),
        Index("ix_media_job_event_job_recorded", "job_ref", "recorded_at", "ordinal"),
    )

    event_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    job_ref: Mapped[str] = mapped_column(Text, nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    stream_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    safe_reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    previous_event_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    command_idempotency_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    command_request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    public_projection_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaJobEvidenceLinkRow(Base):
    __tablename__ = "media_job_evidence_links"
    __table_args__ = (
        UniqueConstraint("job_ref", "purpose", "evidence_id", name="uq_media_job_evidence_purpose"),
        ForeignKeyConstraint(
            ["job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_jobs.job_ref",
                "media_jobs.tenant_ref",
                "media_jobs.entity_ref",
                "media_jobs.store_ref",
                "media_jobs.scope_grant_authority_sha256",
            ],
            name="fk_media_job_link_exact_job",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["event_ref", "job_ref", "tenant_ref", "entity_ref", "store_ref", "scope_grant_authority_sha256"],
            [
                "media_job_events.event_ref",
                "media_job_events.job_ref",
                "media_job_events.tenant_ref",
                "media_job_events.entity_ref",
                "media_job_events.store_ref",
                "media_job_events.scope_grant_authority_sha256",
            ],
            name="fk_media_job_link_exact_event",
            ondelete="RESTRICT",
        ),
        Index("ix_media_job_link_scope", "tenant_ref", "entity_ref", "store_ref", "job_ref"),
    )

    link_ref: Mapped[str] = mapped_column(Text, primary_key=True)
    job_ref: Mapped[str] = mapped_column(Text, nullable=False)
    event_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    evidence_id: Mapped[str] = mapped_column(Text, nullable=False)
    blob_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(160), nullable=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fresh_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GovernedMediaJobWorkspace:
    """Transactional durable core; provider execution is intentionally absent."""

    def __init__(
        self,
        engine,
        *,
        evidence: EvidenceService | None = None,
        authority: Any | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence or EvidenceService(engine)
        if authority is None:
            raise ValueError("media job scope authority is required")
        self.authority = authority
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("media job clock must be timezone-aware")
        return value.astimezone(UTC)

    def _resolve_current(self, *, principal: Principal, store_ref: str) -> MediaJobScope:
        store_ref = _required_text(store_ref, "store_ref")
        now = self._now()
        result = self.authority.current(
            principal=principal,
            store_ref=store_ref,
            as_of=now,
        )
        if not isinstance(result, Mapping):
            raise PermissionError("scope_authority_projection_invalid")
        authority_sha256 = result.get("authority_sha256")
        if (
            result.get("status") != "ready"
            or result.get("tenant_ref") != principal.tenant_ref
            or result.get("store_ref") != store_ref
            or not isinstance(result.get("entity_ref"), str)
            or not result["entity_ref"].strip()
            or not isinstance(authority_sha256, str)
        ):
            raise PermissionError("scope_authority_not_current")
        return MediaJobScope(
            tenant_ref=principal.tenant_ref,
            entity_ref=result["entity_ref"],
            store_ref=store_ref,
            authority_sha256=authority_sha256,
            subject_actor_id=principal.actor_id,
        ).normalized()

    @staticmethod
    def _request_bytes(request: Mapping[str, Any]) -> bytes:
        if not isinstance(request, Mapping) or not request:
            raise ValueError("request must be a non-empty object")
        return canonical_json(request)

    @staticmethod
    def _projection(row: MediaJobRow, event: MediaJobEventRow) -> MediaJobProjection:
        return MediaJobProjection(
            job_ref=row.job_ref,
            state=event.state,
            tool_name=row.tool_name,
            connector_ref=row.connector_ref,
            created_at=_utc_datetime(row.created_at).isoformat(),
            last_event_ordinal=event.ordinal,
            safe_reason_code=event.safe_reason_code,
        )

    def submit(
        self,
        *,
        principal: Principal,
        store_ref: str,
        request: Mapping[str, Any],
    ) -> MediaJobProjection:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        request_bytes = self._request_bytes(request)
        request_sha = sha256_bytes(request_bytes)
        tool_name = _required_text(request.get("tool_name"), "tool_name")
        tool_version = _required_text(request.get("tool_version", "unknown"), "tool_version")
        project_ref = _required_text(request.get("project_ref"), "project_ref")
        brief_ref = _required_text(request.get("brief_ref"), "brief_ref")
        provider = _required_text(request.get("provider"), "provider")
        connector_ref = _required_text(request.get("connector_ref"), "connector_ref")
        connector_binding = _sha256_hex(request.get("connector_binding_sha256"), "connector_binding_sha256")
        idempotency = _sha256_hex(request.get("idempotency_sha256"), "idempotency_sha256")
        scope_payload = {
            "tenant_ref": scope.tenant_ref,
            "entity_ref": scope.entity_ref,
            "store_ref": scope.store_ref,
            "authority_sha256": scope.authority_sha256,
            "subject_actor_id": scope.subject_actor_id,
        }
        fingerprint = sha256_bytes(
            canonical_json({"scope": scope_payload, "request": request})
        )
        scope_binding = sha256_bytes(canonical_json(scope_payload))
        now = self._now()
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            self._lock_idempotency_winner(
                session=session,
                scope=scope,
                idempotency_sha256=idempotency,
            )
            EvidenceService.lock_scope_authority_in_session(
                tenant_ref=scope.tenant_ref,
                store_ref=scope.store_ref,
                subject_actor_id=scope.subject_actor_id,
                session=session,
            )
            fresh_scope = self._resolve_current(principal=principal, store_ref=store_ref)
            if fresh_scope != scope:
                raise PermissionError("scope_authority_changed")
            existing = session.scalar(
                select(MediaJobRow).where(
                    MediaJobRow.tenant_ref == scope.tenant_ref,
                    MediaJobRow.entity_ref == scope.entity_ref,
                    MediaJobRow.store_ref == scope.store_ref,
                    MediaJobRow.scope_grant_authority_sha256 == scope.authority_sha256,
                    MediaJobRow.idempotency_sha256 == idempotency,
                )
            )
            if existing is not None:
                if existing.request_fingerprint_sha256 != fingerprint:
                    raise ValueError("media_job_idempotency_conflict")
                event = self._validate_event_chain(session, existing, scope)[-1]
                return self._projection(existing, event)
            evidence_record = self.evidence.capture_media_job_evidence(
                content=request_bytes,
                filename="media-job-request.json",
                content_type="application/json",
                source=REQUEST_SOURCE,
                source_ref=f"media-job://{scope_binding}/{idempotency}/request",
                grade=EvidenceGrade.B,
                effective_at=now.isoformat(),
                recorded_at=now.isoformat(),
                created_by=scope.subject_actor_id,
                metadata={
                    "contract_id": REQUEST_CONTRACT,
                    "media_job_request_fingerprint_sha256": fingerprint,
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                },
                session=session,
            )
            job_ref = new_id("media_job")
            row = MediaJobRow(
                job_ref=job_ref,
                tenant_ref=scope.tenant_ref,
                entity_ref=scope.entity_ref,
                store_ref=scope.store_ref,
                scope_grant_authority_sha256=scope.authority_sha256,
                subject_actor_id=scope.subject_actor_id,
                tool_name=tool_name,
                tool_version=tool_version,
                project_ref=project_ref,
                brief_ref=brief_ref,
                provider=provider,
                connector_ref=connector_ref,
                connector_binding_sha256=connector_binding,
                idempotency_sha256=idempotency,
                request_sha256=request_sha,
                request_fingerprint_sha256=fingerprint,
                request_evidence_id=evidence_record.id,
                request_evidence_sha256=evidence_record.sha256,
                created_at=now,
            )
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                winner = session.scalar(
                    select(MediaJobRow).where(
                        MediaJobRow.tenant_ref == scope.tenant_ref,
                        MediaJobRow.entity_ref == scope.entity_ref,
                        MediaJobRow.store_ref == scope.store_ref,
                        MediaJobRow.scope_grant_authority_sha256 == scope.authority_sha256,
                        MediaJobRow.idempotency_sha256 == idempotency,
                    )
                )
                if winner is None or winner.request_fingerprint_sha256 != fingerprint:
                    raise ValueError("media_job_idempotency_conflict") from None
                winner_event = self._validate_event_chain(session, winner, scope)[-1]
                return self._projection(winner, winner_event)
            event = self._append_event(
                session=session,
                job=row,
                scope=scope,
                state="QUEUED",
                reason=None,
                now=now,
                command_idempotency_sha256=idempotency,
                command_request_sha256=request_sha,
            )
            session.add(MediaJobEvidenceLinkRow(
                link_ref=new_id("media_link"), job_ref=job_ref, event_ref=None,
                tenant_ref=scope.tenant_ref, entity_ref=scope.entity_ref, store_ref=scope.store_ref,
                scope_grant_authority_sha256=scope.authority_sha256, purpose="request_input",
                evidence_id=evidence_record.id, blob_sha256=evidence_record.sha256,
                source=evidence_record.source, source_ref=evidence_record.source_ref,
                effective_at=now, recorded_at=now, fresh_until=None,
            ))
            return self._projection(row, event)

    @staticmethod
    def _lock_idempotency_winner(
        *,
        session: Session,
        scope: MediaJobScope,
        idempotency_sha256: str,
    ) -> None:
        """Serialize one exact-scope idempotency winner before Evidence writes."""

        if session.get_bind().dialect.name != "postgresql":
            return
        session.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended(concat_ws(chr(31), "
                "CAST(:tenant_ref AS text), CAST(:entity_ref AS text), "
                "CAST(:store_ref AS text), CAST(:authority_sha256 AS text), "
                "CAST(:idempotency_sha256 AS text)), 0))"
            ),
            {
                "tenant_ref": scope.tenant_ref,
                "entity_ref": scope.entity_ref,
                "store_ref": scope.store_ref,
                "authority_sha256": scope.authority_sha256,
                "idempotency_sha256": idempotency_sha256,
            },
        )

    def _append_event(
        self,
        *,
        session: Session,
        job: MediaJobRow,
        scope: MediaJobScope,
        state: str,
        reason: str | None,
        now: datetime,
        command_idempotency_sha256: str,
        command_request_sha256: str,
    ) -> MediaJobEventRow:
        if state not in MEDIA_JOB_STATES:
            raise ValueError("media_job_state_invalid")
        if reason != MEDIA_JOB_SAFE_REASON_BY_STATE[state]:
            raise ValueError("media_job_safe_reason_invalid")
        previous = session.scalar(select(MediaJobEventRow).where(MediaJobEventRow.job_ref == job.job_ref).order_by(MediaJobEventRow.ordinal.desc()))
        if previous is not None and (
            _utc_datetime(now) < _utc_datetime(previous.occurred_at)
            or _utc_datetime(now) < _utc_datetime(previous.recorded_at)
        ):
            raise ValueError("media_job_event_time_regressed")
        ordinal = (previous.ordinal + 1) if previous else 1
        previous_hash = previous.event_sha256 if previous else None
        public_projection = {
            "job_ref": job.job_ref,
            "ordinal": ordinal,
            "state": state,
            "safe_reason_code": reason,
        }
        event_hash = event_seal(
            job=job,
            job_ref=job.job_ref,
            tenant_ref=scope.tenant_ref,
            entity_ref=scope.entity_ref,
            store_ref=scope.store_ref,
            authority_sha256=scope.authority_sha256,
            subject_actor_id=scope.subject_actor_id,
            ordinal=ordinal,
            stream_kind=EVENT_STREAM,
            state=state,
            safe_reason_code=reason,
            previous_event_sha256=previous_hash,
            public_projection_json=public_projection,
            occurred_at=now,
            recorded_at=now,
            command_idempotency_sha256=command_idempotency_sha256,
            command_request_sha256=command_request_sha256,
        )
        event = MediaJobEventRow(
            event_ref=new_id("media_event"), job_ref=job.job_ref,
            tenant_ref=scope.tenant_ref, entity_ref=scope.entity_ref, store_ref=scope.store_ref,
            scope_grant_authority_sha256=scope.authority_sha256, ordinal=ordinal,
            stream_kind=EVENT_STREAM, state=state, safe_reason_code=reason,
            previous_event_sha256=previous_hash, event_sha256=event_hash,
            command_idempotency_sha256=command_idempotency_sha256,
            command_request_sha256=command_request_sha256,
            public_projection_json=public_projection,
            occurred_at=now, recorded_at=now,
        )
        session.add(event)
        session.flush()
        return event

    def _load_job(self, session: Session, scope: MediaJobScope, job_ref: str) -> MediaJobRow:
        row = session.scalar(
            select(MediaJobRow).where(
                MediaJobRow.job_ref == _required_text(job_ref, "job_ref"),
                MediaJobRow.tenant_ref == scope.tenant_ref,
                MediaJobRow.entity_ref == scope.entity_ref,
                MediaJobRow.store_ref == scope.store_ref,
                MediaJobRow.scope_grant_authority_sha256 == scope.authority_sha256,
                MediaJobRow.subject_actor_id == scope.subject_actor_id,
            )
        )
        if row is None:
            raise KeyError("media_job_not_visible")
        return row

    def _validate_event_chain(
        self,
        session: Session,
        job: MediaJobRow,
        scope: MediaJobScope,
    ) -> list[MediaJobEventRow]:
        rows = session.scalars(
            select(MediaJobEventRow)
            .where(MediaJobEventRow.job_ref == job.job_ref)
            .order_by(MediaJobEventRow.ordinal)
        ).all()
        previous: MediaJobEventRow | None = None
        future_limit = self._now() + EVENT_FUTURE_TOLERANCE
        for event in rows:
            occurred_at = _utc_datetime(event.occurred_at)
            recorded_at = _utc_datetime(event.recorded_at)
            transition_invalid = (
                event.state != "QUEUED"
                if previous is None
                else event.state not in MEDIA_JOB_TRANSITIONS.get(previous.state, frozenset())
            )
            if (
                event.tenant_ref != scope.tenant_ref
                or event.entity_ref != scope.entity_ref
                or event.store_ref != scope.store_ref
                or event.scope_grant_authority_sha256 != scope.authority_sha256
                or event.stream_kind != EVENT_STREAM
                or event.state not in MEDIA_JOB_STATES
                or event.safe_reason_code != MEDIA_JOB_SAFE_REASON_BY_STATE[event.state]
                or transition_invalid
                or occurred_at > recorded_at
                or occurred_at > future_limit
                or recorded_at > future_limit
                or (
                    previous is not None
                    and (
                        occurred_at < _utc_datetime(previous.occurred_at)
                        or recorded_at < _utc_datetime(previous.recorded_at)
                    )
                )
                or event.ordinal != (previous.ordinal + 1 if previous else 1)
                or event.previous_event_sha256 != (previous.event_sha256 if previous else None)
                or not isinstance(event.public_projection_json, dict)
                or set(event.public_projection_json) != {
                    "job_ref",
                    "ordinal",
                    "state",
                    "safe_reason_code",
                }
                or event.public_projection_json.get("job_ref") != job.job_ref
                or event.public_projection_json.get("ordinal") != event.ordinal
                or event.public_projection_json.get("state") != event.state
                or event.public_projection_json.get("safe_reason_code") != event.safe_reason_code
            ):
                raise RuntimeError("media_job_event_contract_drifted")
            expected_hash = event_seal(
                job=None,
                job_ref=event.job_ref,
                tenant_ref=event.tenant_ref,
                entity_ref=event.entity_ref,
                store_ref=event.store_ref,
                authority_sha256=event.scope_grant_authority_sha256,
                subject_actor_id=job.subject_actor_id,
                ordinal=event.ordinal,
                stream_kind=event.stream_kind,
                state=event.state,
                safe_reason_code=event.safe_reason_code,
                previous_event_sha256=event.previous_event_sha256,
                public_projection_json=event.public_projection_json,
                occurred_at=event.occurred_at,
                recorded_at=event.recorded_at,
                command_idempotency_sha256=event.command_idempotency_sha256,
                command_request_sha256=event.command_request_sha256,
            )
            if event.event_sha256 != expected_hash:
                raise RuntimeError("media_job_event_contract_drifted")
            previous = event
        if not rows:
            raise RuntimeError("media_job_event_missing")
        return rows

    def read(self, *, principal: Principal, store_ref: str, job_ref: str) -> MediaJobProjection:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        with Session(self.engine) as session:
            row = self._load_job(session, scope, job_ref)
            event = self._validate_event_chain(session, row, scope)[-1]
            return self._projection(row, event)

    def events(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        after_ordinal: int = 0,
        limit: int = 100,
    ) -> list[MediaJobEventProjection]:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        if after_ordinal < 0 or not 0 < limit <= 100:
            raise ValueError("media_job_event_page_invalid")
        with Session(self.engine) as session:
            row = self._load_job(session, scope, job_ref)
            self._validate_event_chain(session, row, scope)
            rows = session.scalars(select(MediaJobEventRow).where(MediaJobEventRow.job_ref == row.job_ref, MediaJobEventRow.ordinal > after_ordinal).order_by(MediaJobEventRow.ordinal).limit(limit)).all()
            return [
                MediaJobEventProjection(
                    e.event_ref,
                    e.job_ref,
                    e.ordinal,
                    e.state,
                    e.safe_reason_code,
                    _utc_datetime(e.occurred_at).isoformat(),
                )
                for e in rows
            ]

    def cancel(
        self,
        *,
        principal: Principal,
        store_ref: str,
        job_ref: str,
        idempotency_key: str,
    ) -> MediaJobProjection:
        scope = self._resolve_current(principal=principal, store_ref=store_ref)
        idempotency_key = _required_text(idempotency_key, "idempotency_key")
        command_request_sha = sha256_bytes(canonical_json({"job_ref": job_ref, "idempotency_key": idempotency_key}))
        command_idempotency_sha = sha256_bytes(idempotency_key.encode("utf-8"))
        now = self._now()
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            EvidenceService.lock_scope_authority_in_session(
                tenant_ref=scope.tenant_ref,
                store_ref=scope.store_ref,
                subject_actor_id=scope.subject_actor_id,
                session=session,
            )
            fresh_scope = self._resolve_current(principal=principal, store_ref=store_ref)
            if fresh_scope != scope:
                raise PermissionError("scope_authority_changed")
            row = self._load_job(session, scope, job_ref)
            previous = self._validate_event_chain(session, row, scope)[-1]
            if previous.state == "CANCELLED":
                if previous.command_idempotency_sha256 == command_idempotency_sha:
                    return self._projection(row, previous)
                raise ValueError("media_job_cancel_idempotency_conflict")
            if previous.state != "QUEUED":
                raise ValueError("media_job_cancel_not_supported")
            event = self._append_event(
                session=session,
                job=row,
                scope=scope,
                state="CANCELLED",
                reason="cancelled_by_request",
                now=now,
                command_idempotency_sha256=command_idempotency_sha,
                command_request_sha256=command_request_sha,
            )
            evidence_record = self.evidence.capture_media_job_evidence(
                content=canonical_json(event.public_projection_json),
                filename="media-job-transition.json",
                content_type="application/json",
                source="governed-media-job-transition",
                source_ref=f"media-job://{row.job_ref}/transition/{event.event_ref}",
                grade=EvidenceGrade.B,
                effective_at=now.isoformat(),
                recorded_at=now.isoformat(),
                created_by=scope.subject_actor_id,
                metadata={
                    "contract_id": "kjds-governed-media-job-transition-v1",
                    "tenant_ref": scope.tenant_ref,
                    "entity_ref": scope.entity_ref,
                    "store_ref": scope.store_ref,
                    "scope_grant_authority_sha256": scope.authority_sha256,
                    "subject_actor_id": scope.subject_actor_id,
                    "event_sha256": event.event_sha256,
                },
                session=session,
            )
            session.add(MediaJobEvidenceLinkRow(
                link_ref=new_id("media_link"), job_ref=row.job_ref, event_ref=event.event_ref,
                tenant_ref=scope.tenant_ref, entity_ref=scope.entity_ref, store_ref=scope.store_ref,
                scope_grant_authority_sha256=scope.authority_sha256, purpose="artifact_terminal",
                evidence_id=evidence_record.id, blob_sha256=evidence_record.sha256,
                source=evidence_record.source, source_ref=evidence_record.source_ref,
                effective_at=now, recorded_at=now, fresh_until=None,
            ))
            return self._projection(row, event)

    # The BAS-182 adapter seam is intentionally fail-closed until phase B wires a provider.
    def peek(self, **_: Any) -> Any:
        from .codex_app_server_worker import DurableDispatchPeek

        return DurableDispatchPeek(False, None, "", "", "", None, None, "", "", False)

    def claim(self, **_: Any) -> Any:
        raise RuntimeError("media_job_provider_dispatch_not_admitted")

    def record(self, **_: Any) -> str | None:
        raise RuntimeError("media_job_provider_dispatch_not_admitted")
