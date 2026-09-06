"""Durable, append-only storage for standing autonomous execution profiles.

The policy evaluator remains pure and issues only short-lived, command-bound
permits.  This adapter stores profile revisions and the governance events that
created, activated, suspended, or expired them so a restart cannot silently
change the standing policy.  It never stores provider credentials and never
executes an external action.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
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
    Numeric,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .autonomous_execution_profile import StandingAutonomousExecutionProfile
from .domain import new_id
from .sql_repository import Base


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str, allow_nan=False).encode()
    ).hexdigest()


def _aware(value: datetime, name: str = "timestamp") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        # SQLite drops timezone metadata on round-trip.  The writer always
        # normalizes to UTC, so restoring that marker is deterministic.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _required(value: str, name: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


class AutonomousExecutionProfileRevisionRow(Base):
    __tablename__ = "autonomous_execution_profile_revisions"
    __table_args__ = (
        UniqueConstraint("profile_id", "profile_version", name="uq_autonomy_profile_version"),
        CheckConstraint("max_permit_ttl_seconds BETWEEN 1 AND 3600", name="ck_autonomy_profile_ttl"),
        CheckConstraint("max_command_amount IS NULL OR max_command_amount >= 0", name="ck_autonomy_profile_amount"),
        Index("ix_autonomy_profile_scope", "tenant_ref", "entity_ref", "profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(200), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(80), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_refs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_channels_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_operations_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_permit_ttl_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_command_amount: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    max_command_amount_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    revision_event: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    compliance_id: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AutonomousExecutionProfileEventRow(Base):
    __tablename__ = "autonomous_execution_profile_events"
    __table_args__ = (
        UniqueConstraint("profile_id", "idempotency_key", name="uq_autonomy_profile_event_idempotency"),
        Index("ix_autonomy_profile_events_profile", "profile_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    compliance_id: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AutonomousExecutionProfileStore:
    """Append-only profile revision store with exact-scope reads."""

    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _identities(actor_id: str, reviewer_id: str, compliance_id: str) -> tuple[str, str, str]:
        identities = tuple(_required(item, name) for item, name in (
            (actor_id, "actor_id"), (reviewer_id, "reviewer_id"), (compliance_id, "compliance_id")))
        if len(set(identities)) != 3:
            raise ValueError("actor, reviewer, and compliance identities must be distinct")
        return identities

    @staticmethod
    def _payload(profile: StandingAutonomousExecutionProfile, event: str) -> dict[str, Any]:
        return {
            "profile_id": profile.profile_id,
            "profile_version": profile.profile_version,
            "tenant_ref": profile.tenant_ref,
            "entity_ref": profile.entity_ref,
            "store_refs": sorted(profile.store_refs),
            "allowed_channels": sorted(profile.allowed_channels),
            "allowed_operations": sorted(profile.allowed_operations),
            "enabled": profile.enabled,
            "activated_at": profile.activated_at.isoformat() if profile.activated_at else None,
            "expires_at": profile.expires_at.isoformat() if profile.expires_at else None,
            "max_permit_ttl_seconds": profile.max_permit_ttl_seconds,
            "max_command_amount": str(profile.max_command_amount) if profile.max_command_amount is not None else None,
            "profile_sha256": profile.profile_sha256,
            "event": event,
        }

    @classmethod
    def _row(cls, profile: StandingAutonomousExecutionProfile, *, event: str, actor_id: str,
             reviewer_id: str, compliance_id: str, now: datetime) -> AutonomousExecutionProfileRevisionRow:
        amount = profile.max_command_amount
        return AutonomousExecutionProfileRevisionRow(
            id=new_id("autonomy_profile_revision"), profile_id=profile.profile_id,
            profile_version=profile.profile_version, tenant_ref=profile.tenant_ref,
            entity_ref=profile.entity_ref, store_refs_json=sorted(profile.store_refs),
            allowed_channels_json=sorted(profile.allowed_channels),
            allowed_operations_json=sorted(profile.allowed_operations), enabled=profile.enabled,
            activated_at=profile.activated_at, expires_at=profile.expires_at,
            max_permit_ttl_seconds=profile.max_permit_ttl_seconds,
            max_command_amount=amount,
            max_command_amount_text=str(amount) if amount is not None else None,
            profile_sha256=profile.profile_sha256, revision_event=event,
            created_by=actor_id, reviewer_id=reviewer_id, compliance_id=compliance_id,
            created_at=now,
        )

    @staticmethod
    def _from_row(row: AutonomousExecutionProfileRevisionRow) -> StandingAutonomousExecutionProfile:
        amount = Decimal(row.max_command_amount_text) if row.max_command_amount_text is not None else None
        return StandingAutonomousExecutionProfile(
            profile_id=row.profile_id, tenant_ref=row.tenant_ref, entity_ref=row.entity_ref,
            store_refs=frozenset(row.store_refs_json), allowed_channels=frozenset(row.allowed_channels_json),
            allowed_operations=frozenset(row.allowed_operations_json), enabled=row.enabled,
            activated_at=_aware(row.activated_at, "activated_at") if row.activated_at else None,
            expires_at=_aware(row.expires_at, "expires_at") if row.expires_at else None,
            max_permit_ttl_seconds=row.max_permit_ttl_seconds, max_command_amount=amount,
            profile_version=row.profile_version,
        )

    def _append(self, profile: StandingAutonomousExecutionProfile, *, event: str,
                idempotency_key: str, actor_id: str, reviewer_id: str, compliance_id: str) -> StandingAutonomousExecutionProfile:
        actor_id, reviewer_id, compliance_id = self._identities(actor_id, reviewer_id, compliance_id)
        idempotency_key = _required(idempotency_key, "idempotency_key")
        now = datetime.now(UTC)
        payload = self._payload(profile, event)
        request_sha = _sha({"idempotency_key": idempotency_key, "payload": payload,
                            "actor_id": actor_id, "reviewer_id": reviewer_id, "compliance_id": compliance_id})
        with Session(self.engine) as session:
            existing = session.scalar(select(AutonomousExecutionProfileEventRow).where(
                AutonomousExecutionProfileEventRow.profile_id == profile.profile_id,
                AutonomousExecutionProfileEventRow.idempotency_key == idempotency_key))
            if existing is not None:
                if existing.request_sha256 != request_sha:
                    raise ValueError("profile event idempotency key conflicts")
                return self.current(profile_id=profile.profile_id, tenant_ref=profile.tenant_ref, entity_ref=profile.entity_ref)
        try:
            with Session(self.engine) as session, session.begin():
                session.add(self._row(profile, event=event, actor_id=actor_id, reviewer_id=reviewer_id,
                                      compliance_id=compliance_id, now=now))
                session.add(AutonomousExecutionProfileEventRow(
                    id=new_id("autonomy_profile_event"), profile_id=profile.profile_id, event_type=event,
                    idempotency_key=idempotency_key, request_sha256=request_sha, payload_json=payload,
                    actor_id=actor_id, reviewer_id=reviewer_id, compliance_id=compliance_id, created_at=now))
        except IntegrityError:
            with Session(self.engine) as session:
                existing = session.scalar(select(AutonomousExecutionProfileEventRow).where(
                    AutonomousExecutionProfileEventRow.profile_id == profile.profile_id,
                    AutonomousExecutionProfileEventRow.idempotency_key == idempotency_key))
                if existing is not None:
                    if existing.request_sha256 != request_sha:
                        raise ValueError("profile event idempotency key conflicts") from None
                else:
                    raise ValueError("profile already exists or profile version conflicts") from None
        return profile

    def create(self, profile: StandingAutonomousExecutionProfile, *, idempotency_key: str,
               actor_id: str, reviewer_id: str, compliance_id: str) -> StandingAutonomousExecutionProfile:
        if profile.enabled:
            raise ValueError("profile must be created disabled and activated by a separate governance event")
        return self._append(profile, event="created", idempotency_key=idempotency_key,
                            actor_id=actor_id, reviewer_id=reviewer_id, compliance_id=compliance_id)

    def current(self, *, profile_id: str, tenant_ref: str, entity_ref: str) -> StandingAutonomousExecutionProfile:
        profile_id = _required(profile_id, "profile_id")
        tenant_ref = _required(tenant_ref, "tenant_ref")
        entity_ref = _required(entity_ref, "entity_ref")
        with Session(self.engine) as session:
            row = session.scalar(select(AutonomousExecutionProfileRevisionRow).where(
                AutonomousExecutionProfileRevisionRow.profile_id == profile_id,
                AutonomousExecutionProfileRevisionRow.tenant_ref == tenant_ref,
                AutonomousExecutionProfileRevisionRow.entity_ref == entity_ref,
            ).order_by(AutonomousExecutionProfileRevisionRow.created_at.desc()))
        if row is None:
            raise KeyError("autonomous execution profile not found for exact scope")
        return self._from_row(row)

    def activate(self, *, profile_id: str, tenant_ref: str, entity_ref: str, idempotency_key: str,
                 actor_id: str, reviewer_id: str, compliance_id: str, now: datetime | None = None) -> StandingAutonomousExecutionProfile:
        current = self.current(profile_id=profile_id, tenant_ref=tenant_ref, entity_ref=entity_ref)
        if current.enabled:
            return current
        activated = _aware(now or datetime.now(UTC), "activated_at")
        next_version = str(int(current.profile_version) + 1) if current.profile_version.isdigit() else f"{current.profile_version}.1"
        updated = replace(current, enabled=True, activated_at=activated, profile_version=next_version)
        return self._append(updated, event="activated", idempotency_key=idempotency_key,
                            actor_id=actor_id, reviewer_id=reviewer_id, compliance_id=compliance_id)

    def suspend(self, *, profile_id: str, tenant_ref: str, entity_ref: str, idempotency_key: str,
                actor_id: str, reviewer_id: str, compliance_id: str) -> StandingAutonomousExecutionProfile:
        current = self.current(profile_id=profile_id, tenant_ref=tenant_ref, entity_ref=entity_ref)
        if not current.enabled:
            return current
        next_version = str(int(current.profile_version) + 1) if current.profile_version.isdigit() else f"{current.profile_version}.1"
        updated = replace(current, enabled=False, profile_version=next_version)
        return self._append(updated, event="suspended", idempotency_key=idempotency_key,
                            actor_id=actor_id, reviewer_id=reviewer_id, compliance_id=compliance_id)

    def history(self, *, profile_id: str, tenant_ref: str, entity_ref: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(select(AutonomousExecutionProfileRevisionRow).where(
                AutonomousExecutionProfileRevisionRow.profile_id == profile_id,
                AutonomousExecutionProfileRevisionRow.tenant_ref == tenant_ref,
                AutonomousExecutionProfileRevisionRow.entity_ref == entity_ref,
            ).order_by(AutonomousExecutionProfileRevisionRow.created_at.asc())).all()
        return [{"profile": self._from_row(row).profile_sha256, "profile_version": row.profile_version,
                 "enabled": row.enabled, "event": row.revision_event, "created_at": _aware(row.created_at).isoformat(),
                 "created_by": row.created_by, "reviewer_id": row.reviewer_id, "compliance_id": row.compliance_id}
                for row in rows]


__all__ = ["AutonomousExecutionProfileEventRow", "AutonomousExecutionProfileRevisionRow", "AutonomousExecutionProfileStore"]
