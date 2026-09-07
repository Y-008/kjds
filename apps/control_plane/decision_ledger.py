"""Thread-safe, in-memory append-only decision event ledger.

This module is intentionally an adapter-free service.  It provides a stable
event seam for the control loop while leaving durable persistence to a later,
explicitly authorized adapter.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .data_fabric_contracts import ScopeRef


def _utc(value: Any) -> datetime:
    parsed = value
    if isinstance(parsed, str):
        parsed = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone")
    return parsed.astimezone(UTC)


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_canonical(item) for item in value]
    return value


class DecisionLedgerError(ValueError):
    """Raised when a ledger event would violate append-only invariants."""


class DecisionEvent(BaseModel):
    """An immutable event in a hash-chained decision ledger."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=1)
    event_id: str = Field(min_length=1, max_length=200)
    event_type: str = Field(min_length=1, max_length=120)
    decision_id: str = Field(min_length=1, max_length=200)
    scope: ScopeRef | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    actor_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=1, max_length=240)
    occurred_at: datetime
    previous_hash: str = Field(default="", max_length=64)
    event_hash: str = Field(min_length=64, max_length=64)

    @field_validator("event_type", "event_id", "decision_id", "actor_id", "idempotency_key", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("ledger identifiers cannot be blank")
        return normalized

    @field_validator("occurred_at", mode="before")
    @classmethod
    def normalize_time(cls, value: Any) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_hash_shape(self) -> DecisionEvent:
        if self.previous_hash and len(self.previous_hash) != 64:
            raise ValueError("previous_hash must be SHA-256")
        if any(char not in "0123456789abcdef" for char in self.previous_hash.lower()):
            raise ValueError("previous_hash must be lowercase SHA-256")
        if any(char not in "0123456789abcdef" for char in self.event_hash.lower()):
            raise ValueError("event_hash must be lowercase SHA-256")
        return self


def _event_hash(*, sequence: int, event_id: str, event_type: str, decision_id: str, scope: ScopeRef | None,
                payload: Mapping[str, Any], actor_id: str, idempotency_key: str, occurred_at: datetime,
                previous_hash: str) -> str:
    canonical = _canonical(
        {
            "sequence": sequence,
            "event_id": event_id,
            "event_type": event_type,
            "decision_id": decision_id,
            "scope": scope,
            "payload": payload,
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
            "occurred_at": occurred_at,
            "previous_hash": previous_hash,
        }
    )
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class DecisionLedger:
    """A small append-only event ledger with deterministic replay checks."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: list[DecisionEvent] = []
        self._by_idempotency: dict[str, DecisionEvent] = {}

    def append(
        self,
        event_type: str,
        *,
        decision_id: str,
        payload: Mapping[str, Any] | None = None,
        actor_id: str = "control_loop",
        idempotency_key: str | None = None,
        scope: ScopeRef | None = None,
        occurred_at: datetime | None = None,
    ) -> DecisionEvent:
        """Append an event, or return the same event for an exact retry.

        A reused idempotency key with changed content is rejected.  There are
        no update or delete methods by design.
        """

        normalized_event_type = str(event_type).strip()
        normalized_decision_id = str(decision_id).strip()
        normalized_actor = str(actor_id).strip()
        normalized_key = str(idempotency_key or f"{normalized_event_type}:{normalized_decision_id}:{uuid4().hex}").strip()
        if not normalized_event_type or not normalized_decision_id or not normalized_actor:
            raise DecisionLedgerError("event type, decision id, and actor id are required")
        if not normalized_key:
            raise DecisionLedgerError("idempotency key cannot be blank")
        supplied_time = _utc(occurred_at) if occurred_at is not None else None
        event_payload = dict(payload or {})
        with self._lock:
            existing = self._by_idempotency.get(normalized_key)
            if existing is not None:
                if (
                    existing.event_type != normalized_event_type
                    or existing.decision_id != normalized_decision_id
                    or existing.scope != scope
                    or existing.payload != event_payload
                    or existing.actor_id != normalized_actor
                ):
                    raise DecisionLedgerError("idempotency key was reused with different event content")
                if supplied_time is not None and supplied_time != existing.occurred_at:
                    raise DecisionLedgerError("idempotency key was reused with a different occurred_at")
                return existing
            event_time = supplied_time or datetime.now(UTC)
            sequence = len(self._events) + 1
            previous_hash = self._events[-1].event_hash if self._events else ""
            event_id = f"dle_{uuid4().hex}"
            digest = _event_hash(
                sequence=sequence,
                event_id=event_id,
                event_type=normalized_event_type,
                decision_id=normalized_decision_id,
                scope=scope,
                payload=event_payload,
                actor_id=normalized_actor,
                idempotency_key=normalized_key,
                occurred_at=event_time,
                previous_hash=previous_hash,
            )
            event = DecisionEvent(
                sequence=sequence,
                event_id=event_id,
                event_type=normalized_event_type,
                decision_id=normalized_decision_id,
                scope=scope,
                payload=event_payload,
                actor_id=normalized_actor,
                idempotency_key=normalized_key,
                occurred_at=event_time,
                previous_hash=previous_hash,
                event_hash=digest,
            )
            self._events.append(event)
            self._by_idempotency[normalized_key] = event
            return event

    append_event = append

    def events(self, *, decision_id: str | None = None) -> tuple[DecisionEvent, ...]:
        with self._lock:
            if decision_id is None:
                return tuple(self._events)
            return tuple(item for item in self._events if item.decision_id == decision_id)

    def latest(self, *, decision_id: str | None = None) -> DecisionEvent | None:
        selected = self.events(decision_id=decision_id)
        return selected[-1] if selected else None

    def verify(self) -> bool:
        with self._lock:
            previous = ""
            for expected_sequence, event in enumerate(self._events, start=1):
                if event.sequence != expected_sequence or event.previous_hash != previous:
                    return False
                expected_hash = _event_hash(
                    sequence=event.sequence,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    decision_id=event.decision_id,
                    scope=event.scope,
                    payload=event.payload,
                    actor_id=event.actor_id,
                    idempotency_key=event.idempotency_key,
                    occurred_at=event.occurred_at,
                    previous_hash=event.previous_hash,
                )
                if event.event_hash != expected_hash:
                    return False
                previous = event.event_hash
            return True

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


__all__ = ["DecisionEvent", "DecisionLedger", "DecisionLedgerError"]
