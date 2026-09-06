"""Idempotent usage and cost ledger for AI skills and generated media."""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class SkillUsageEvent:
    event_id: str
    idempotency_key: str
    tenant_id: str
    customer_id: str
    skill_id: str
    units: Decimal
    unit_cost: Decimal
    currency: str = "USD"
    occurred_at: datetime = datetime.min.replace(tzinfo=UTC)
    asset_ref: str | None = None
    resource_type: str = "skill"
    provider_ref: str | None = None
    model_ref: str | None = None
    cost_center: str | None = None
    input_units: Decimal | None = None
    output_units: Decimal | None = None

    @property
    def total_cost(self) -> Decimal:
        return self.units * self.unit_cost


def _usage_fingerprint(event: SkillUsageEvent) -> str:
    """Return the immutable billing identity for an event.

    The event id, idempotency key, and observation time are transport metadata;
    the billable dimensions below define whether a retry is the same event.
    Keeping this canonicalizer shared by the memory and SQL adapters prevents
    a retry from being accepted by one adapter and rejected by the other.
    """

    return hashlib.sha256(
        json.dumps(
            {
                "tenant_id": event.tenant_id,
                "customer_id": event.customer_id,
                "skill_id": event.skill_id,
                "units": str(event.units),
                "unit_cost": str(event.unit_cost),
                "currency": event.currency,
                "asset_ref": event.asset_ref,
                "resource_type": event.resource_type,
                "provider_ref": event.provider_ref,
                "model_ref": event.model_ref,
                "cost_center": event.cost_center,
                "input_units": str(event.input_units) if event.input_units is not None else None,
                "output_units": str(event.output_units) if event.output_units is not None else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class SkillUsageLedger:
    def __init__(self) -> None:
        self._events: dict[str, SkillUsageEvent] = {}
        # Idempotency is tenant-scoped so one customer's retry key cannot
        # replay or reveal another customer's usage event.
        self._by_key: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()

    def record(self, event: SkillUsageEvent) -> SkillUsageEvent:
        if event.units < 0 or event.unit_cost < 0:
            raise ValueError("usage units and unit_cost must be non-negative")
        if len(event.currency) != 3:
            raise ValueError("currency must be a 3-letter code")
        if not event.resource_type.strip() or len(event.resource_type) > 80:
            raise ValueError("resource_type is required and must be <= 80 characters")
        for name, amount in (("input_units", event.input_units), ("output_units", event.output_units)):
            if amount is not None and amount < 0:
                raise ValueError(f"{name} cannot be negative")
        fingerprint = _usage_fingerprint(event)
        with self._lock:
            existing_id = self._by_key.get((event.tenant_id, event.idempotency_key))
            if existing_id is not None:
                existing = self._events[existing_id]
                existing_fingerprint = _usage_fingerprint(existing)
                if existing_fingerprint != fingerprint:
                    raise ValueError("usage idempotency key conflicts with immutable event")
                return existing
            if event.event_id in self._events:
                raise ValueError("event_id already exists")
            self._events[event.event_id] = event
            self._by_key[(event.tenant_id, event.idempotency_key)] = event.event_id
            return event

    def events_for(self, *, tenant_id: str, customer_id: str | None = None) -> tuple[SkillUsageEvent, ...]:
        with self._lock:
            rows = [
                event for event in self._events.values()
                if event.tenant_id == tenant_id and (customer_id is None or event.customer_id == customer_id)
            ]
        return tuple(sorted(rows, key=lambda item: (item.occurred_at, item.event_id)))

    def total_cost(self, *, tenant_id: str, customer_id: str | None = None, currency: str = "USD") -> Decimal:
        rows = self.events_for(tenant_id=tenant_id, customer_id=customer_id)
        if any(event.currency != currency for event in rows):
            raise ValueError("mixed currencies require an explicit FX snapshot")
        return sum((event.total_cost for event in rows), Decimal("0"))

    def invoice_preview(self, *, tenant_id: str, customer_id: str, currency: str = "USD") -> dict[str, object]:
        rows = self.events_for(tenant_id=tenant_id, customer_id=customer_id)
        total = self.total_cost(tenant_id=tenant_id, customer_id=customer_id, currency=currency)
        return {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "currency": currency,
            "event_count": len(rows),
            "total_cost": str(total),
            "event_ids": [event.event_id for event in rows],
        }


__all__ = ["SkillUsageEvent", "SkillUsageLedger"]
