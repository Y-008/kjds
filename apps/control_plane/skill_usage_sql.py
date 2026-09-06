"""Durable SQL adapter for the AI skill and generated-media usage ledger.

The in-process :class:`~apps.control_plane.skill_usage_ledger.SkillUsageLedger`
is useful for isolated contract tests, but a commercial usage event must survive
process restarts and concurrent workers.  This adapter keeps the same small
interface while making the event append-only and tenant-scoped in SQL.

Schema ownership stays with Alembic migrations.  ``for_url`` is intentionally a
test/development convenience; runtime composition only receives an existing
engine and never creates tables implicitly.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .skill_usage_ledger import (
    SkillUsageEvent,
    _legacy_usage_fingerprint,
    _normalize_cutoff,
    _usage_fingerprint,
)
from .sql_repository import Base


class SkillUsageEventRow(Base):
    """Append-only commercial usage event row.

    ``event_id`` is globally unique so an external receipt can unambiguously
    refer to one event.  Idempotency keys are scoped by tenant, which permits
    independent customers to use the same request key without leaking or
    replaying another tenant's event.
    """

    __tablename__ = "skill_usage_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_skill_usage_tenant_idempotency",
        ),
        # The entitlement link repeats the event scope.  Keep one database
        # identity that covers every repeated field so a composite FK can
        # reject a forged cross-tenant/customer binding before the adapter
        # ever reads it.
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "customer_id",
            "idempotency_key",
            "entitlement_receipt_ref",
            name="uq_skill_usage_entitlement_parent_identity",
        ),
        CheckConstraint("units >= 0", name="ck_skill_usage_units_nonnegative"),
        CheckConstraint(
            "unit_cost >= 0", name="ck_skill_usage_unit_cost_nonnegative"
        ),
        CheckConstraint(
            "length(currency) = 3", name="ck_skill_usage_currency_shape"
        ),
        CheckConstraint(
            "input_units IS NULL OR input_units >= 0",
            name="ck_skill_usage_input_units_nonnegative",
        ),
        CheckConstraint(
            "output_units IS NULL OR output_units >= 0",
            name="ck_skill_usage_output_units_nonnegative",
        ),
        CheckConstraint(
            "entitlement_receipt_ref IS NULL OR length(entitlement_receipt_ref) > 0",
            name="ck_skill_usage_entitlement_receipt_ref",
        ),
        Index(
            "ix_skill_usage_scope_occurred",
            "tenant_id",
            "customer_id",
            "occurred_at",
            "event_id",
        ),
        Index(
            "ix_skill_usage_skill_occurred",
            "tenant_id",
            "skill_id",
            "occurred_at",
        ),
        Index(
            "ix_skill_usage_entitlement_receipt",
            "tenant_id",
            "entitlement_receipt_ref",
            "occurred_at",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(200), nullable=False)
    units: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    # Numeric columns support bounded SQL reporting; text mirrors retain the
    # original Decimal exponent so invoice previews remain byte-for-byte
    # reproducible (``2 * 0.25`` must render as ``0.50``, not a DB-scale value).
    units_text: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_cost_text: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    asset_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False, default="skill")
    provider_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_center: Mapped[str | None] = mapped_column(String(160), nullable=True)
    input_units: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    output_units: Mapped[Decimal | None] = mapped_column(Numeric(38, 18), nullable=True)
    entitlement_receipt_ref: Mapped[str | None] = mapped_column(
        String(300), nullable=True
    )
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class SkillUsageEntitlementLinkRow(Base):
    """Immutable, tenant-scoped binding between usage and an admission receipt.

    The usage event remains the accounting fact and this table is the durable
    authorization edge.  Keeping the edge separate means legacy events can
    remain unbound while every explicitly admitted event has a queryable,
    append-only receipt reference.  Scope and idempotency columns are repeated
    intentionally: they make an accidental cross-tenant join visible and let
    the adapter verify the edge without trusting a caller supplied event id.
    """

    __tablename__ = "skill_usage_entitlement_links"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "usage_event_id",
            name="uq_skill_usage_entitlement_link_event",
        ),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_skill_usage_entitlement_link_idempotency",
        ),
        ForeignKeyConstraint(
            [
                "tenant_id",
                "usage_event_id",
                "customer_id",
                "idempotency_key",
                "entitlement_receipt_ref",
            ],
            [
                "skill_usage_events.tenant_id",
                "skill_usage_events.event_id",
                "skill_usage_events.customer_id",
                "skill_usage_events.idempotency_key",
                "skill_usage_events.entitlement_receipt_ref",
            ],
            name="fk_skill_usage_entitlement_link_exact_event",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        CheckConstraint(
            "length(entitlement_receipt_ref) > 0",
            name="ck_skill_usage_entitlement_link_receipt_ref",
        ),
        Index(
            "ix_skill_usage_entitlement_link_receipt",
            "tenant_id",
            "entitlement_receipt_ref",
            "recorded_at",
        ),
        Index(
            "ix_skill_usage_entitlement_link_scope",
            "tenant_id",
            "customer_id",
            "recorded_at",
            "usage_event_id",
        ),
    )

    link_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    usage_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(160), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(300), nullable=False)
    entitlement_receipt_ref: Mapped[str] = mapped_column(
        String(300), nullable=False
    )
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    @property
    def receipt_sha256(self) -> str:
        """Compatibility name for callers that call the ref a receipt hash."""

        return self.entitlement_receipt_ref


# Keep the longer spelling available to adapters that use the domain term
# "receipt" in their type names while retaining the concise table contract.
SkillUsageEntitlementReceiptLinkRow = SkillUsageEntitlementLinkRow


def _entitlement_link_fingerprint(event: SkillUsageEvent) -> str:
    """Hash the exact authorization edge, including its tenant boundary."""

    return hashlib.sha256(
        json.dumps(
            {
                "usage_event_id": event.event_id,
                "tenant_id": event.tenant_id,
                "customer_id": event.customer_id,
                "idempotency_key": event.idempotency_key,
                "entitlement_receipt_ref": event.entitlement_receipt_ref,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _aware(value: datetime) -> datetime:
    """Normalize database timestamps (SQLite drops timezone metadata)."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _event_from_row(row: SkillUsageEventRow) -> SkillUsageEvent:
    return SkillUsageEvent(
        event_id=row.event_id,
        idempotency_key=row.idempotency_key,
        tenant_id=row.tenant_id,
        customer_id=row.customer_id,
        skill_id=row.skill_id,
        units=Decimal(row.units_text) if row.units_text else Decimal(str(row.units)),
        unit_cost=(
            Decimal(row.unit_cost_text)
            if row.unit_cost_text
            else Decimal(str(row.unit_cost))
        ),
        currency=row.currency,
        occurred_at=_aware(row.occurred_at),
        asset_ref=row.asset_ref,
        resource_type=row.resource_type or "skill",
        provider_ref=row.provider_ref,
        model_ref=row.model_ref,
        cost_center=row.cost_center,
        input_units=Decimal(str(row.input_units)) if row.input_units is not None else None,
        output_units=Decimal(str(row.output_units)) if row.output_units is not None else None,
        entitlement_receipt_ref=row.entitlement_receipt_ref,
    )


class SqlSkillUsageLedger:
    """Append-only SQL implementation of ``SkillUsageLedger``'s read contract."""

    def __init__(self, engine: Engine):
        self.engine = engine

    @classmethod
    def for_url(cls, url: str) -> SqlSkillUsageLedger:
        """Build a store and create only its table for local tests.

        Production migrations remain the sole schema authority; callers using
        ``build_runtime`` should construct the class directly with an engine.
        """

        engine = create_engine(url, future=True)
        Base.metadata.create_all(
            engine,
            tables=[
                SkillUsageEventRow.__table__,
                SkillUsageEntitlementLinkRow.__table__,
            ],
        )
        return cls(engine)

    @staticmethod
    def _validate(event: SkillUsageEvent) -> None:
        if event.units < 0 or event.unit_cost < 0:
            raise ValueError("usage units and unit_cost must be non-negative")
        if len(event.currency) != 3:
            raise ValueError("currency must be a three-letter code")
        if not event.resource_type.strip() or len(event.resource_type) > 80:
            raise ValueError("resource_type is required and must be <= 80 characters")
        for name, amount in (("input_units", event.input_units), ("output_units", event.output_units)):
            if amount is not None and amount < 0:
                raise ValueError(f"{name} cannot be negative")

    @staticmethod
    def _by_idempotency(session: Session, event: SkillUsageEvent) -> SkillUsageEventRow | None:
        return session.scalar(
            select(SkillUsageEventRow).where(
                SkillUsageEventRow.tenant_id == event.tenant_id,
                SkillUsageEventRow.idempotency_key == event.idempotency_key,
            )
        )

    @staticmethod
    def _resolve_existing(
        row: SkillUsageEventRow,
        fingerprint: str,
    ) -> SkillUsageEvent:
        existing = _event_from_row(row)
        if (
            _usage_fingerprint(existing) != fingerprint
            or row.fingerprint_sha256
            not in {
                fingerprint,
                # Rows written before 0117 have no receipt column and use the
                # pre-binding digest.  They remain valid legacy retries.
                _legacy_usage_fingerprint(existing)
                if existing.entitlement_receipt_ref is None
                else fingerprint,
            }
        ):
            raise ValueError("usage idempotency key conflicts with immutable event")
        return existing

    @staticmethod
    def _verify_event_row(
        row: SkillUsageEventRow, event: SkillUsageEvent
    ) -> None:
        """Verify the stored event digest before exposing it to a caller."""

        accepted = {_usage_fingerprint(event)}
        if event.entitlement_receipt_ref is None:
            accepted.add(_legacy_usage_fingerprint(event))
        if row.fingerprint_sha256 not in accepted:
            raise ValueError("usage event fingerprint conflicts with immutable event")

    @staticmethod
    def _binding_for(
        session: Session, event: SkillUsageEvent
    ) -> SkillUsageEntitlementLinkRow | None:
        """Load an authorization edge only inside the event's tenant scope."""

        return session.scalar(
            select(SkillUsageEntitlementLinkRow).where(
                SkillUsageEntitlementLinkRow.tenant_id == event.tenant_id,
                SkillUsageEntitlementLinkRow.usage_event_id == event.event_id,
            )
        )

    @staticmethod
    def _verify_binding(
        session: Session, event: SkillUsageEvent
    ) -> None:
        """Fail closed when an explicit receipt edge is missing or altered.

        Legacy events intentionally have no edge.  The two states are kept
        disjoint so a stale/orphaned link cannot silently authorize a legacy
        retry, and an explicitly admitted event cannot be returned after its
        authorization edge has been deleted or rewritten.
        """

        if event.entitlement_receipt_ref is None:
            # The link table was introduced after the legacy event schema.  A
            # legacy read must remain usable even for a test/compatibility
            # database that has only the original event table.
            return
        binding = SqlSkillUsageLedger._binding_for(session, event)
        if binding is None:
            raise ValueError("entitlement receipt binding is missing")
        expected = _entitlement_link_fingerprint(event)
        if (
            binding.tenant_id != event.tenant_id
            or binding.customer_id != event.customer_id
            or binding.usage_event_id != event.event_id
            or binding.idempotency_key != event.idempotency_key
            or binding.entitlement_receipt_ref != event.entitlement_receipt_ref
            or binding.fingerprint_sha256 != expected
            or binding.link_id != expected
        ):
            raise ValueError("entitlement receipt binding conflicts with immutable usage event")

    @staticmethod
    def _new_binding(event: SkillUsageEvent) -> SkillUsageEntitlementLinkRow | None:
        if event.entitlement_receipt_ref is None:
            return None
        fingerprint = _entitlement_link_fingerprint(event)
        return SkillUsageEntitlementLinkRow(
            link_id=fingerprint,
            usage_event_id=event.event_id,
            tenant_id=event.tenant_id,
            customer_id=event.customer_id,
            idempotency_key=event.idempotency_key,
            entitlement_receipt_ref=event.entitlement_receipt_ref,
            fingerprint_sha256=fingerprint,
            recorded_at=datetime.now(UTC),
        )

    def record(self, event: SkillUsageEvent) -> SkillUsageEvent:
        """Insert one event, returning the idempotent winner on retries.

        The unique tenant/key constraint is the final arbiter under concurrent
        workers.  If a race wins after the initial lookup, a fresh read returns
        the winner and still compares its immutable fingerprint.
        """

        self._validate(event)
        fingerprint = _usage_fingerprint(event)
        occurred_at = _aware(event.occurred_at)
        try:
            with Session(self.engine) as session, session.begin():
                existing = self._by_idempotency(session, event)
                if existing is not None:
                    resolved = self._resolve_existing(existing, fingerprint)
                    self._verify_binding(session, resolved)
                    return resolved
                by_id = session.get(SkillUsageEventRow, event.event_id)
                if by_id is not None:
                    raise ValueError("event_id already exists")
                row = SkillUsageEventRow(
                    event_id=event.event_id,
                    idempotency_key=event.idempotency_key,
                    tenant_id=event.tenant_id,
                    customer_id=event.customer_id,
                    skill_id=event.skill_id,
                    units=event.units,
                    unit_cost=event.unit_cost,
                    units_text=str(event.units),
                    unit_cost_text=str(event.unit_cost),
                    currency=event.currency,
                    occurred_at=occurred_at,
                    asset_ref=event.asset_ref,
                    resource_type=event.resource_type,
                    provider_ref=event.provider_ref,
                    model_ref=event.model_ref,
                    cost_center=event.cost_center,
                    input_units=event.input_units,
                    output_units=event.output_units,
                    entitlement_receipt_ref=event.entitlement_receipt_ref,
                    fingerprint_sha256=fingerprint,
                    recorded_at=datetime.now(UTC),
                )
                session.add(row)
                session.flush()
                binding = self._new_binding(event)
                if binding is not None:
                    session.add(binding)
                    session.flush()
                return _event_from_row(row)
        except IntegrityError as exc:
            # A concurrent worker may have won either unique constraint.  Read
            # in a new transaction before deciding whether this is an ordinary
            # idempotent retry or an event-id collision.
            with Session(self.engine) as session:
                winner = session.scalar(
                    select(SkillUsageEventRow).where(
                        SkillUsageEventRow.tenant_id == event.tenant_id,
                        SkillUsageEventRow.idempotency_key == event.idempotency_key,
                    )
                )
                if winner is not None:
                    resolved = self._resolve_existing(winner, fingerprint)
                    self._verify_binding(session, resolved)
                    return resolved
                by_id = session.get(SkillUsageEventRow, event.event_id)
                if by_id is not None:
                    raise ValueError("event_id already exists") from exc
            raise

    def get(self, event_id: str) -> SkillUsageEvent:
        with Session(self.engine) as session:
            row = session.get(SkillUsageEventRow, event_id)
            if row is None:
                raise KeyError(f"Unknown usage event: {event_id}")
            event = _event_from_row(row)
            self._verify_event_row(row, event)
            self._verify_binding(session, event)
            return event

    def events_for(
        self, *, tenant_id: str, customer_id: str | None = None,
        as_of: datetime | None = None,
    ) -> tuple[SkillUsageEvent, ...]:
        cutoff = _normalize_cutoff(as_of)
        with Session(self.engine) as session:
            query = select(SkillUsageEventRow).where(
                SkillUsageEventRow.tenant_id == tenant_id
            )
            if customer_id is not None:
                query = query.where(SkillUsageEventRow.customer_id == customer_id)
            if cutoff is not None:
                query = query.where(SkillUsageEventRow.occurred_at <= cutoff)
            rows = session.scalars(
                query.order_by(
                    SkillUsageEventRow.occurred_at, SkillUsageEventRow.event_id
                )
            ).all()
            events: list[SkillUsageEvent] = []
            for row in rows:
                event = _event_from_row(row)
                self._verify_event_row(row, event)
                self._verify_binding(session, event)
                events.append(event)
        return tuple(events)

    def total_cost(
        self,
        *,
        tenant_id: str,
        customer_id: str | None = None,
        currency: str = "USD",
        as_of: datetime | None = None,
    ) -> Decimal:
        rows = self.events_for(tenant_id=tenant_id, customer_id=customer_id, as_of=as_of)
        if any(event.currency != currency for event in rows):
            raise ValueError("mixed currencies require an explicit FX snapshot")
        return sum((event.total_cost for event in rows), Decimal("0"))

    def invoice_preview(
        self, *, tenant_id: str, customer_id: str, currency: str = "USD",
        as_of: datetime | None = None,
    ) -> dict[str, object]:
        rows = self.events_for(tenant_id=tenant_id, customer_id=customer_id, as_of=as_of)
        total = self.total_cost(
            tenant_id=tenant_id, customer_id=customer_id, currency=currency, as_of=as_of
        )
        result = {
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "currency": currency,
            "event_count": len(rows),
            "total_cost": str(total),
            "event_ids": [event.event_id for event in rows],
        }
        if as_of is not None:
            result["as_of"] = as_of.astimezone(UTC).isoformat()
        return result


__all__ = [
    "SkillUsageEntitlementLinkRow",
    "SkillUsageEntitlementReceiptLinkRow",
    "SkillUsageEventRow",
    "SqlSkillUsageLedger",
]
